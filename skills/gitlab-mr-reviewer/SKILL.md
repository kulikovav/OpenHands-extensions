---
name: gitlab-mr-reviewer
description: >
  Create an automation that reviews GitLab merge requests when a configured
  trigger label is applied. Starts one OpenHands review conversation per label
  event with the merge request's exact head checked out, and publishes the
  review to GitLab.
triggers:
  - /mr-reviewer:setup
---

# GitLab MR Reviewer Automation

## Agent Canvas catalog

For new Agent Canvas installations, use the **GitLab code review** catalog
entry. Its deterministic `worker.py` delegates each requested exact head to a
stable conversation using the selected agent profile. It supports GitLab
reviewer-request events and scheduled label scans. The manual upload flow below
remains for existing deployments and is deprecated for new installations.

Create a cron automation that watches one or more GitLab projects for merge
requests with a review trigger label, starts an OpenHands review conversation
once per label event, and publishes the AI review to GitLab.

The automation script is deterministic: MR discovery, label-event tracking,
head eligibility, state persistence, stale-result suppression, the repository
checkout, and its removal are all handled in Python. The LLM is invoked only for
the review itself.

Before any review conversation is created, a scheduled scan evaluates the
current head's pipelines on GitLab. The head pipeline is the merge-policy
signal this gate can read without project-level configuration:

- A pipeline that finishes `failed` or `canceled` blocks the review. An
  unrecognized pipeline status fails closed as a block, so a status this
  automation does not know can never silently approve.
- A pipeline that finishes `success` or `skipped` does not block.
- A pipeline that is `created`, `preparing`, `pending`, `scheduled`,
  `waiting_for_resource`, `manual`, or `running` makes the run exit with a
  **waiting on pipeline** outcome. Unfinished is never approval. The worker does
  not hold a slot polling; the next scheduled scan or a new reviewer request
  retries.
- A project with no CI configured counts an absent pipeline as green, so a
  project without pipelines is still reviewable.
- Only the latest pipeline per `ref`/`source` pair decides, so a re-run on an
  obsolete push cannot block the push that fixed it.

A reviewer request is the intake-policy exception: the caller asked for that
head by name, so the request dispatches even when the head pipeline is red or
pending, and the gate leaves no explanatory note. The Agent Canvas catalog
entry supports GitLab reviewer-request events for this path; this manual setup
flow reviews trigger labels on a cron.

The gate needs no configured list of pipeline names. When it stops a review it
leaves one concise explanation on the MR, identified by a hidden marker carrying
the head SHA and gate category, so a later run for a different head updates that
note instead of posting another. Only a marker this reviewer account authored
counts as its own note; every other MR note is untrusted and can neither
suppress the explanation nor be edited. If the project's own workflow already
posted a deterministic remediation note that names the same current-head
pipelines, the gate adds nothing; a disclosure about some other pipeline does
not suppress it.

Each label application is a fresh review. The conversation for an MR is reused
where the deployment supports it, but its earlier turns must not be trusted as
current: before deciding a verdict the reviewer re-fetches the mutable GitLab
state (the exact head, the MR description, notes and threads, reviewers, the
linked issues' descriptions and labels, and the current-head pipeline results)
and ignores any earlier finding, verdict, or label/priority claim that state no
longer supports. Repository analysis the conversation already did, such as
reading `AGENTS.md`, stays useful and is not repeated.

## Review identity on GitLab

GitLab notes carry no commit attribute the way GitHub reviews do, so a finished
review binds itself to its exact head through a hidden marker the agent puts in
the summary note body: `<!-- openhands-mr-review {sha} -->`. The note ends with
a verdict line (`✅ APPROVED`, `🔄 CHANGES REQUESTED`, or
`🛑 MAINTAINER DECISION REQUIRED`). Only notes authored by the token's own
account are matched, so a marker someone else pasted can never impersonate a
finished review. This marker is what the scanner dedupes on, what a repeat scan
reconciles, and what the maintainer handoff reads as the standing verdict.

When an MR's trigger label is applied again, the latest matching GitLab
resource label event is a new review request, and the head-bound marker of that
MR is checked before any conversation starts: a head this account already
reviewed, with no clarifying note by someone else since, is reconciled (its
verdict is confirmed and any configured handoff runs) instead of being reviewed
a second time.

## Scope, evidence, and the maintainer decision

The review prompt starts with a scope gate: using the repository's own guidance
(its scope categories and ownership boundaries, not a list of MR numbers), the
reviewer decides whether the change belongs in this repository and has the
product/architecture direction it needs. When it does not, the review stops
with a single summary note that says whether the change should move
repositories, close, or receive a maintainer decision, and ends with the
`🛑 MAINTAINER DECISION REQUIRED` verdict. That outcome is **neither an
approval nor a change request**: it does not approve or merge the MR. The
completion handler recognizes the verdict and requests one configured
maintainer through the same handoff used after an approval.

Before approving a change to user-visible UI behavior, the prompt requires live
evidence from a real running application when the repository's guidance demands
it: a screenshot, screen recording, or equivalent capture of the running app.
Unit tests, CSS-token or contract assertions, generated mockups, and
reconstructed captures may support the review but cannot substitute for that
evidence. When the required evidence is missing, the reviewer publishes one
summary note naming exactly what is missing and ends with
`🔄 CHANGES REQUESTED`, so approval is withheld and the deterministic
maintainer handoff does not fire.

## Bounded intake per scheduled scan

The manual flow polls on a cron, and each new label event starts exactly one
conversation. The catalog entry (`automations/catalog/gitlab-mr-reviewer/`)
adds the scheduled backlog scan on top, which reviews an unrequested open
non-draft MR once its current head is green and unreviewed, keyed by
project/MR/head so repeated scans reuse one conversation and one review. That
scan drains the backlog oldest-first under the `max_new_per_run` quota, which
limits only newly created conversations across every configured project.

The script prepares each review's workspace before the agent starts: the MR's
head commit is downloaded as an archive and extracted to a directory of its
own, which becomes the conversation's working directory. The agent is told not
to clone, fetch, check out, or delete anything - in this manual flow the code
is already at the head SHA - and the script removes the checkout once the
conversation has stopped. Nothing accumulates between runs.

---

The script imports shared GitLab transport from `scripts/gitlab_client.py`,
installed with this skill. Include it beside `main.py` when packaging manually,
as shown below; catalog bundles include it automatically.

## Prerequisites

### Required secret

Verify that the following secret is set in **OpenHands Settings → Secrets**:

| Secret name    | Token type          | Minimum permissions                                                          |
| -------------- | ------------------- | ---------------------------------------------------------------------------- |
| `GITLAB_TOKEN` | Personal access token | `api` scope, at least the Developer role on every monitored project        |

Merge-request **write** access is required because the agent publishes a review
note, inline discussions, and an approval, not just a read. The Agent Canvas
catalog worker may also request a configured human reviewer after approval.
A token with only read access will poll happily and then fail at the point of
publishing or requesting the handoff.

When several projects are monitored, the token must cover all of them.

Check with:
```bash
curl -s https://gitlab.com/api/v4/user \
  -H "PRIVATE-TOKEN: $GITLAB_TOKEN" \
  | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('username') or d.get('message'))"
```

For a self-managed instance, replace `https://gitlab.com/api/v4` with your own
API root, such as `https://gitlab.example.com/api/v4`.

If the token is missing or invalid, inform the user and stop.

---

## Setup Workflow

Follow these steps in order.

### Step 1 - Verify `GITLAB_TOKEN`

Run the `curl` check above against the right API root.

- If absent: *"GITLAB_TOKEN is not set. Please add it in OpenHands Settings →
  Secrets."* Stop.
- If the API returns an authentication error: tell the user the token is
  invalid and ask them to update it. Stop.

### Step 2 - Collect projects

Ask: *"Which GitLab projects should be monitored?
(Format: `group/project`, subgroups written in full as `group/sub/project`.
List several separated by commas to review them all from one automation.)"*

Validate access to **each** project:
```bash
curl -s "https://gitlab.com/api/v4/projects/${GROUP}%2F${PROJECT}" \
  -H "PRIVATE-TOKEN: $GITLAB_TOKEN" \
  | python3 -c "
import json, sys
d = json.load(sys.stdin)
if 'message' in d:
    print('ERROR:', d['message'])
else:
    print(f\"Accessible. Private: {d.get('visibility') != 'public'}. \"
          f\"Default branch: {d.get('default_branch')}\")
"
```

Record every accepted project into `PROJECTS = ["{group}/{project}", ...]`. If
one project fails the check, say which and ask whether to continue without it.

Each project is polled independently and keeps its own state, so merge-request
IIDs never collide between them. The trigger label, tone, and schedule are
shared by all of them; a project needing different settings wants its own
automation.

### Step 3 - Collect trigger label

Ask: *"Which MR label should trigger a review?
(Press Enter for the default: `openhands-review`.)"*

Record the answer as `TRIGGER_LABEL`. If the label does not exist yet, tell the
user that GitLab will still record the event once the label is created and
applied to an MR.

The automation reviews an MR when it sees the latest matching GitLab resource
label event for that label. To request another review later, remove and
re-apply the label.

### Step 4 - Collect review tone

Ask: *"What review tone should the reviewer use?
  1. Thorough (default) - comprehensive coverage of correctness, security, tests, style
  2. Concise - high-signal only, skips minor style feedback
  3. Friendly - constructive and encouraging
(Press Enter for Thorough, or type your choice or any custom style description)"*

Map the choice to `REVIEW_TONE`:

| Answer                              | `REVIEW_TONE` | `REVIEW_STYLE_INSTRUCTIONS` |
| ----------------------------------- | ------------- | --------------------------- |
| 1 / Enter                           | `"thorough"`  | `""`                        |
| 2                                   | `"concise"`   | `""`                        |
| 3                                   | `"friendly"`  | `""`                        |
| Custom text, e.g. `strict but kind` | `"thorough"`  | the custom text verbatim    |

### Step 5 - Collect cron schedule

Ask: *"How often should the automation poll for labeled MRs?
(Press Enter for the default: every 15 minutes.
Use a cron expression for a different interval, e.g. `0 * * * *` = hourly)"*

Default: `*/15 * * * *`.

Record as `CRON_SCHEDULE`.

### Step 6 - Generate the automation script

Read `scripts/main.py` from this skill's directory. Apply exactly these
constant substitutions near the top of the file:

> The script also reads a `config.json` shipped beside it, if there is one, over
> these constants. That is how the catalog entry
> (`automations/catalog/gitlab-mr-reviewer/`) configures an unmodified copy,
> since a declarative host cannot rewrite Python. This setup path substitutes
> the constants and ships no `config.json`, so the two never collide.

| Placeholder                                       | Replace with                                                                                                                              |
| ------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------- |
| `PROJECTS = ["group/project"]`                    | `PROJECTS = [{project_list}]` - one entry per project collected in Step 2                                                                  |
| `TRIGGER_LABEL = "openhands-review"`              | `TRIGGER_LABEL = "{trigger_label}"`                                                                                                       |
| `REVIEW_TONE = "thorough"`                        | `REVIEW_TONE = "{review_tone}"`                                                                                                           |
| `REVIEW_STYLE_INSTRUCTIONS = ""`                  | `REVIEW_STYLE_INSTRUCTIONS = "{style_instructions}"`                                                                                      |
| `REPO_REVIEW_GUIDE_PATH = ".agents/skills/custom-codereview-guide.md"` | leave unchanged to auto-load a repo review guide at this path, or set to `""` to disable                             |
| `MAX_NEW_PER_RUN = 2`                             | leave unchanged, or raise it if the deployment can hold more agents at once                                                                |
| `DEFAULT_OPENHANDS_URL = "http://localhost:8000"` | leave unchanged unless the user has a preference                                                                                          |
| `GITLAB_API_URL = "https://gitlab.com/api/v4"`    | leave unchanged on GitLab.com, or set to the self-managed instance's API root                                                             |
| `GITLAB_TOKEN_SECRET = "GITLAB_TOKEN"`            | leave unchanged, or set to the name of the saved secret the deployment uses                                                               |

Use a safe string writer such as `json.dumps(value)` when inserting
user-provided project paths, labels, or style instructions into Python string
literals. `json.dumps(list_of_projects)` produces the whole `PROJECTS` list
safely in one step.

Run these commands from this skill's directory and write the customized script
to a temporary build directory:
```bash
mkdir -p /tmp/mr-reviewer-build
cp -L scripts/gitlab_client.py /tmp/mr-reviewer-build/gitlab_client.py
# write the customized main.py to /tmp/mr-reviewer-build/main.py
```

Validate syntax before packaging:
```bash
python3 -m py_compile /tmp/mr-reviewer-build/main.py && echo "Syntax OK"
```

Fix any syntax errors before proceeding.

### Step 7 - Package and upload

Determine the Automation backend URL and auth from the `<RUNTIME_SERVICES>`
block in your system context:
- **OPENHANDS_HOST**: the Automation backend `url_from_agent`
- **Auth**: `X-Session-API-Key: $OPENHANDS_AUTOMATION_API_KEY`

```bash
tar -czf /tmp/mr-reviewer.tar.gz -C /tmp/mr-reviewer-build .

TARBALL_PATH=$(curl -s -X POST \
  "${OPENHANDS_HOST}/api/automation/v1/uploads?name=gitlab-mr-reviewer" \
  -H "X-Session-API-Key: $OPENHANDS_AUTOMATION_API_KEY" \
  -H "Content-Type: application/gzip" \
  --data-binary @/tmp/mr-reviewer.tar.gz \
  | python3 -c "import json,sys; print(json.load(sys.stdin)['tarball_path'])")

echo "Uploaded: $TARBALL_PATH"
```

### Step 8 - Register the automation

```bash
curl -s -X POST "${OPENHANDS_HOST}/api/automation/v1" \
  -H "X-Session-API-Key: $OPENHANDS_AUTOMATION_API_KEY" \
  -H "Content-Type: application/json" \
  -d "{
    \"name\": \"GitLab MR Reviewer: {project_summary} label {trigger_label}\",
    \"trigger\": {\"type\": \"cron\", \"schedule\": \"{cron_schedule}\"},
    \"tarball_path\": \"$TARBALL_PATH\",
    \"entrypoint\": \"python3 main.py\",
    \"timeout\": 900
  }" | python3 -m json.tool
```

Use the single project path as `{project_summary}` when there is one, and
something like `3 projects` when there are several. A poll now downloads an
archive per queued review, so the timeout allows for that; a run never waits
for a review to finish, only for it to be started.

Record the returned `id`.

### Step 9 - Confirm

Tell the user:

> ✅ **GitLab MR Reviewer** is running!
>
> - Automation ID: `{id}`
> - Projects: `group/project`, ... (one line each)
> - Trigger label: `{trigger_label}`
> - Review tone: `{tone}`
> - Polling schedule: `{cron_schedule}`
> - State file per project:
>   `~/.openhands/workspaces/automation-state/gitlab_mr_reviewer_label_event_{id}_{group}__{project}.json`
>
> Apply the `{trigger_label}` label to a merge request to queue a review. Each
> label event is processed once. To request another review, remove and re-apply
> the label.
>
> The review is published as a merge request note bound to the head commit,
> with inline diff notes where a finding maps to a changed line, and an
> approval where there are no material issues.

---

## Runtime Behaviour (per poll)

Each cron run executes `main.py`, which resolves and validates `GITLAB_TOKEN`
once, then processes every project in `PROJECTS` independently. One project
failing does not stop the others; the run fails only if every project fails.

For each project:

1. Loads that project's state (see `references/state-schema.md`).
2. Verifies project access.
3. Lists open MRs, oldest-updated first.
4. For each open MR carrying `TRIGGER_LABEL`:
   - Refetches current MR metadata to avoid acting on stale list data.
   - Finds the latest matching GitLab resource label event.
   - Skips the event if it has already been tracked.
   - Downloads the MR's head commit as an archive and extracts it to
     `{WORKSPACE_BASE}/repositories/{group}__{project}/mr-{iid}-{sha12}`. The
     archive is checked as it is unpacked: a single root, no absolute or `..`
     paths, and symlinks skipped rather than materialised.
   - Starts an OpenHands conversation **whose working directory is that
     checkout**, with a review prompt carrying MR metadata, the exact head SHA,
     label event details, and the requirement to re-fetch the current mutable
     GitLab state before deciding a verdict.
   - Posts an acknowledgement note with the label event, head SHA, and
     conversation link.
   - Records the review in state with `status: "active"` and the checkout path.
   - If the checkout or the conversation cannot be created, the checkout is
     removed and nothing is recorded, so the next poll retries the label event.
5. For each active review conversation:
   - Marks it closed without posting if the MR has closed or merged.
   - Suppresses stale results if the MR head SHA changed after the review was
     queued.
   - When the conversation reaches `idle`, `finished`, `error`, or `stuck`,
     asks GitLab whether a review note by the token's own account exists for
     that head SHA (through the head marker). If it does, the review is
     complete. If it does not, the agent's final response is posted as a note
     so the work is not lost.
   - Abandons a conversation that has not reached a terminal status within two
     hours, so its checkout can be reclaimed.
6. Removes the checkout of every finished review, but only after confirming the
   conversation has stopped - deleting it under a running agent would remove
   its working directory. When that cannot be confirmed the directory is left
   alone and the next poll tries again.
7. Saves that project's state atomically.

The completion callback fires once for the whole run.

---

## Additional Resources

- **`references/state-schema.md`** - State JSON schema, field definitions, and
  review lifecycle diagram.
- **`scripts/main.py`** - The complete automation script. Customize the
  constants at the top before packaging.
- **`tests/test_main.py`** - Unit tests for the checkout, its removal, and
  state handling. Run them from the skill root with `python -m pytest tests/`
  after editing the script.

---

## Troubleshooting

| Symptom                                           | Likely cause                                                                    | Fix                                                                                                                               |
| ------------------------------------------------- | ------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------- |
| Bot never queues reviews                          | Trigger label not present or no matching resource label event                   | Apply the configured label to the MR                                                                                              |
| Authentication error in run logs                  | Token expired or lacks the `api` scope                                          | Rotate and update `GITLAB_TOKEN`                                                                                                  |
| 404 on project access                             | Project path wrong or no access                                                 | Re-check the entry in `PROJECTS` and the token's permissions                                                                      |
| One project is skipped, others work               | That project failed its access check                                            | Read the `=== group/project ===` block in the run log                                                                             |
| Same MR not reviewed after new commits            | Label event was already processed                                               | Remove and re-apply the trigger label                                                                                             |
| Review paused with a failing-pipeline note        | The current head's pipeline reported `failed` or `canceled`                     | Fix the pipeline and push; the review starts on the new head, or request the reviewer account directly                            |
| Review reported waiting on the pipeline           | The current head's pipeline has not finished                                    | No action; a later scan or a new reviewer request retries                                                                         |
| CI-less project reviewed without waiting          | No pipeline exists, so the gate counts the head as green                        | No action; add CI to the project to gate reviews                                                                                  |
| Only a few reviews start on a large backlog       | The per-scan `max_new_per_run` bound (default 2) reached                        | No action; later scans drain the remaining oldest eligible MRs, or raise `max_new_per_run` if the deployment can hold more agents |
| Review result never posts                         | Conversation still running or stuck                                             | Open the conversation link from the acknowledgement note                                                                          |
| Stale review suppressed                           | MR head SHA changed while the agent was reviewing                               | Re-apply the trigger label after the latest commit                                                                                |
| Review arrives as a plain note, not an approval   | The approval was refused, or the review had findings                            | Expected: findings post as `🔄 CHANGES REQUESTED`; self-approval may be refused by project policy                                 |
| Agent reports it cannot fetch the repo            | The workspace is already the checkout in the manual flow                        | No action - the code is at the head SHA in its working directory                                                                  |
| Checkouts remain under `repositories/`            | Their conversations had not stopped yet                                         | They are removed by a later poll once the conversation is terminal                                                                |