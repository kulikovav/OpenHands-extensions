# State Schema

The automation maintains a JSON state document **per project**, persisted
across polling runs. It is the source of truth for which trigger-label events
have queued reviews, which conversations are still active, and which project
checkouts are still on disk.

Each project in `PROJECTS` gets its own document, so merge-request IIDs from
different projects never share a bucket.

---

## Storage

**Primary (cloud):** The state is stored in the automation service's built-in KV
store under the key `state:{group}__{project}` - for example
`state:OpenHands__extensions`. The KV store is available when
`AUTOMATION_KV_TOKEN` is injected into the run environment. Each automation has
its own isolated namespace.

**Fallback (local/dev):** When the KV store is not available, the state is
written to a local JSON file at:

```
{WORKSPACE_BASE_ROOT}/automation-state/gitlab_mr_reviewer_label_event_{automation_id}_{group}__{project}.json
```

`WORKSPACE_BASE_ROOT` is derived by going two levels up from the `WORKSPACE_BASE`
environment variable, stripping `automation-runs/{run_id}`.

Example on a local install:

```
~/.openhands/workspaces/automation-state/gitlab_mr_reviewer_label_event_abc12345-..._myorg__backend.json
```

The `automation_id` is read from the `AUTOMATION_EVENT_PAYLOAD` environment
variable, field `automation_id`.

### Upgrading from a single-project automation

Earlier versions stored one document under the bare key `state` (or a filename
without the project suffix). On the first poll after an upgrade, that document
is adopted for the project named in its own `project` field, and written back
under the new per-project key. Reviews already handled are therefore not
re-run. A project that does not match the legacy document simply starts with
empty state.

---

## Top-Level Schema

```jsonc
{
  "version": 3,
  "project": "group/project",
  "trigger_label": "openhands-review",
  "updated_at": 1717200000.0,
  "reviews": {},
  "mrs": {}
}
```

---

## `reviews` Map

Key: `"{mr_iid}:label:{label_event_id}"`. This makes the latest GitLab
resource label event the idempotency key. Re-applying the trigger label creates
a new GitLab event and therefore a new review request.

Value: **ReviewRecord**

```jsonc
{
  "mr_iid": 42,
  "head_sha": "0123456789abcdef...",
  "trigger_label_event_id": 123456,
  "trigger_label_event_created_at": "2026-06-12T00:00:00Z",
  "web_url": "https://gitlab.com/group/project/-/merge_requests/42",
  "status": "active",
  "conversation_id": "550e8400-e29b-41d4-a716-446655440000",
  "workspace_dir": "/workspace/repositories/group__project/mr-42-0123456789ab",
  "last_activity": 1717200000.0
}
```

`status` values:

| Status | Meaning |
|---|---|
| `starting` | The label event is claimed and the checkout/conversation is being set up. Written and saved before that work begins, so a poll overlapping the claiming one skips this event instead of reviewing the same commit twice. Becomes `active` once the conversation exists, or the record is deleted if setup fails, so the next poll retries. A `starting` record older than `STALLED_CLAIM_SECONDS` (15 min) belongs to a poll that died mid-setup and is released. |
| `active` | Review conversation is running or waiting to be collected |
| `closed` | Final result was handled, or the MR closed before collection |
| `stale` | MR head SHA changed before the review completed, so the result was suppressed |
| `expired` | Conversation never reached a terminal status within `MAX_ACTIVE_AGE` (2 h) and was abandoned |

When a review becomes stale, `stale_reason` records the old and new head SHAs.
When a review closes after posting, `completed_at` records the completion time.
When a review expires, `expired_after` records how many seconds it had been
waiting.

### `workspace_dir`

The directory holding the reviewed commit, created by the script before the
conversation starts and used as that conversation's working directory. It is
removed once the conversation is confirmed stopped, and the key is deleted from
the record at the same time.

The key therefore doubles as the "still on disk" marker: a record carrying a
`workspace_dir` after it has left `active` is retried on every later poll until
the removal succeeds. A checkout is never removed while its conversation is
still running, and never outside `{WORKSPACE_BASE}/repositories/`.

---

## `mrs` Map

Key: `"{mr_iid}"`.

Value: latest MR snapshot observed during polling:

```jsonc
{
  "head_sha": "0123456789abcdef...",
  "label_present": true,
  "labels": ["openhands-review", "bug"],
  "last_seen": 1717200000.0
}
```

This snapshot is informational and helps diagnose whether an MR was skipped
because the trigger label was absent.

---

## Review Lifecycle

```
Trigger label applied on GitLab
        |
        v
[starting] - label event claimed and saved, before any slow work
        |
        +-- setup fails ----------------------------> record deleted, retried next poll
        |
        +-- claiming poll dies mid-setup -----------> released after 15 min
        |
        v
  checkout prepared at head SHA, conversation created
        |
        v
[active]  - acknowledgement note posted
        |
        +-- MR closes/merges before collection -----> [closed]  without posting
        |
        +-- MR head SHA changes before collection --> [stale]   without posting
        |
        +-- no terminal status within 2 h ----------> [expired] without posting
        |
        v
[closed]  - review confirmed on GitLab (the head-bound review marker), or the
            agent's text posted as a note
        |
        v
  checkout removed once the conversation has stopped
```

---

## Resetting State

To force the automation to reconsider previous label events, delete the state
for that project from the KV store (cloud) or the fallback file (local).

**Cloud (KV store):**
```bash
curl -X DELETE "${OPENHANDS_HOST}/api/automation/v1/kv/state:group__project" \
  -H "Authorization: Bearer ${AUTOMATION_KV_TOKEN}"
```

**Local (file fallback):**
```bash
rm ~/.openhands/workspaces/automation-state/gitlab_mr_reviewer_label_event_<id>_group__project.json
```

Resetting state also forgets which checkouts are outstanding, so remove any
leftover directories under `{WORKSPACE_BASE}/repositories/group__project/`
yourself.

Usually, prefer removing and re-applying the trigger label. That preserves
history while creating a new review request.