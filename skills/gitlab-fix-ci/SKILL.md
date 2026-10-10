---
name: gitlab-fix-ci
description: Find failing CI jobs, inspect logs, and apply focused fixes. Use when branch CI is failing and needs a fast, iterative path to green checks.
triggers:
- /gitlab-fix-ci
- fix-ci
- failing-pipeline
---

# GitLab Fix CI

Iterate on failing CI until checks pass. Uses glab CLI.

## Prerequisites

- glab installed and authenticated (`glab auth status`)
- Current branch pushed to origin

## Workflow

1. **Identify latest run**: `glab ci status` (or `glab ci status -b <branch>`)
2. **Inspect failed jobs**: `glab ci trace <job-name>` (omit job name for interactive selection)
3. **Apply smallest safe fix** for the first actionable error
4. **Push and re-run**: `git add ... && git commit -m "..." && git push`
5. **Repeat** until green

## Commands

| Command | Purpose |
|---------|---------|
| `glab ci status` | Pipeline status for current branch |
| `glab ci status --live` | Wait until pipeline completes |
| `glab ci trace [job-name]` | View job logs |
| `glab ci retry [job-name]` | Retry job (for suspected flakiness) |

## Guardrails

- Fix one actionable failure at a time
- Prefer minimal, low-risk changes before broader refactors
- Do not use `--no-verify` or skip hooks when pushing

## Output

At each iteration report:

- **Primary failing job** and root error excerpt
- **Fixes applied** in iteration order (job, error, fix, commit)
- **Current CI status** and next action (fix X, retry, or done)
