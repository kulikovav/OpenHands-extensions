# GitLab Commit, Push, and MR

Commit, push, and open a GitLab merge request through the GitLab API (`glab`). Use when asked to ship or open an MR on GitLab, or for MR-description-only flows such as writing, rewriting, or describing an MR body.

## Triggers

This skill is activated by the following keywords:

- `/gitlab-commit-push-mr`
- `commit-push-mr`
- `open-mr`

## Details

GitLab-compatible version of the Compound Engineering `ce-commit-push-pr` workflow. All GitLab operations go through `glab`; consult the `glab` skill for API mechanics.

Three modes are supported:

| Mode | What it does |
| --- | --- |
| Description-only | Composes and prints an MR title and body. It applies nothing unless asked. |
| Description update | Refreshes an existing MR's description with no commit or push intent. |
| Full workflow | Resolves the branch, commits, pushes, composes, and creates or updates the MR. |

The full workflow resolves the default branch, creates a feature branch when the checkout is on the default branch or detached, commits only the named files, and re-checks for an open MR immediately before `glab mr create` so a duplicate MR cannot be opened. Stacked MRs are out of scope, because GitLab has no first-class stacked-MR tooling.

After a new MR or new commits on an open MR, the run is not done until CI is green, the CI loop reports a residual, or the user stops the watch.