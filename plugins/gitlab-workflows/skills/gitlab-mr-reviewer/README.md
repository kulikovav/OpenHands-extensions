# GitLab MR Reviewer

Create an automation that reviews GitLab merge requests when a trigger label is
applied, or on a scheduled scan of an outstanding reviewer request.

## Trigger

This skill is activated by:

- `/mr-reviewer:setup`

## Features

- Reviews MRs on demand from a label event, and an outstanding reviewer request
  on the catalog's scheduled scan once the requested head's pipeline is green
- Gates each scheduled review on the current head's GitLab pipelines before
  starting an agent: a completed `failed` or `canceled` pipeline blocks the
  review, an unfinished pipeline exits with a clear waiting-on-pipeline outcome
  instead of holding a slot, an unknown status fails closed, and a project
  without CI counts an absent pipeline as green
- Dispatches an explicit reviewer request even when CI is red or pending; the
  pipeline gate applies to scheduled discovery
- Ignores pipelines recorded against another push, so a stale failure cannot
  block the commit that fixed it
- Explicit reviewer requests include draft MRs in both event mode and scheduled
  scans; drafts without a request or trigger label remain excluded
- Reviews open, non-draft MRs that nobody requested on a scheduled scan once
  their current head is green and carries no review yet, keyed by
  project/MR/head so a repeat scan never duplicates a conversation or review
  and a changed head becomes eligible again
- Examines the whole unrequested backlog on each scheduled scan, while the
  global `max_new_per_run` quota limits only newly created review
  conversations; blocked or pending heads consume no launch slot
- Posts no managed gate note for an unrequested MR that is merely red or
  pending - the note answers an explicit request, so a scan over a large
  backlog cannot storm the MRs with notes
- Names the retry the deployment actually has in the waiting note: the next
  scheduled scan where a cron trigger exists, and removing and re-adding the
  reviewer where only the event trigger does
- Rewrites its own managed gate note in place when the retry wording changes,
  so switching a deployment from the event trigger to a cron scan updates the
  outstanding-request explanation instead of leaving the old instruction
- Watches several projects from a single automation, each with its own state,
  including self-managed instances through the `gitlab_api_url` setting
- Bounds a scheduled scan to a small, configurable number of new review
  conversations across all projects (default 2), draining the oldest
  outstanding reviewer requests first and reaching the rest on later scans
- Processes each review request or label application idempotently
- Supports re-review by re-applying the trigger label. Each explicit request
  refreshes mutable GitLab state (head, MR description, notes and threads,
  reviewers, linked issues, and current-head pipelines) instead of trusting
  what an earlier turn observed, so a same-head re-review sees a linked issue
  that has since gained or lost readiness, or a pipeline that has since moved.
  Repository analysis already done, such as reading `AGENTS.md`, is retained
- Binds the finished review to its exact head through a hidden marker in the
  summary note, because GitLab notes carry no commit attribute, and verifies on
  GitLab that it landed
- Suppresses stale reviews when the MR head commit changes mid-review
- Hands the agent the reviewed commit already checked out, and removes that
  checkout when the review ends, so nothing accumulates between runs
- Publishes a real merge request review, with inline diff notes where a finding
  maps to a changed line and an approval where there are no material findings
- Requires live evidence from the real app before approving a user-visible UI
  change when the repository's guidance demands it: unit tests, CSS-token
  assertions, generated mockups, and reconstructed captures cannot substitute.
  Missing evidence yields a review note that names the gap, so no approval and
  no maintainer handoff
- Posts acknowledgement notes with AI disclosure
- Configurable review tone, polling schedule, and token secret name
- Optional human handoff after an exact-head approval. The scanner ranks the
  configured maintainers by recent commits to changed paths (matched through
  the email their GitLab account reports), then by their open GitLab
  review-request count, and requests one without merging the MR. Use at least
  two project members so a maintainer can author an MR without leaving the
  handoff roster empty.

## Prerequisites

Set `GITLAB_TOKEN` in OpenHands Settings → Secrets. The token must carry the
`api` scope and at least the Developer role, because reading project members
and resources is only the start: the review is published through the merge
request API - notes, inline discussions, and approvals - and the optional
human reviewer is requested through the reviewers API, so read-only access is
not enough.

## Quick Start

Ask OpenHands for the setup:

> "Set up a GitLab MR review automation for my `myorg/backend` and
> `myorg/frontend` projects that reviews everything labelled
> `openhands-review`, using concise reviews."

After setup, apply the configured label on a merge request to queue a review.
To request another review later, remove and re-apply the label.

## See Also

- [SKILL.md](SKILL.md) - Full setup workflow reference