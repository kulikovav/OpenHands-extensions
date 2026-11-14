# GitLab Loop on CI

Watch GitLab CI runs on the current branch and iterate on failures until every check passes. Use when the user needs to watch branch CI, iterate on failures until green, or fix CI until all checks pass.

## Triggers

This skill is activated by the following keywords:

- `/gitlab-loop-on-ci`
- `loop-on-ci`
- `watch-ci`

## Details

Uses the `glab` CLI to monitor pipeline status, inspect failed job logs, apply focused fixes, and report the result.

```
Task Progress:
- [ ] Step 1: Find current branch and latest pipeline
- [ ] Step 2: Wait for CI completion
- [ ] Step 3: If failed, inspect logs and fix
- [ ] Step 4: Commit and push (no hook bypass)
- [ ] Step 5: Repeat until green
```

`glab ci status --live` waits for the pipeline and its exit code reflects the result. A job that fails with a different error, or passes on retry, counts as flaky after one `glab ci retry`; a second failure is treated as real. The skill never bypasses hooks.