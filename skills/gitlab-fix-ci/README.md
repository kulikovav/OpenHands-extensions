# GitLab Fix CI

Find failing CI jobs, inspect their logs, and apply focused fixes. Use when branch CI is failing and needs a fast, iterative path to green checks.

## Triggers

This skill is activated by the following keywords:

- `/gitlab-fix-ci`
- `fix-ci`
- `failing-pipeline`

## Details

Iterates on failing CI until the checks pass, using the `glab` CLI:

1. Identify the latest pipeline with `glab ci status`, or `glab ci status -b <branch>`.
2. Inspect the failed job with `glab ci trace <job-name>`.
3. Apply the smallest safe fix for the first actionable error.
4. Push and re-run.
5. Repeat until green.

The skill fixes one actionable failure at a time, prefers minimal low-risk changes, and never skips hooks with `--no-verify`.