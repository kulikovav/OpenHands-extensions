---
name: gitlab-loop-on-ci
description: Watches GitLab CI runs on the current branch and iterates on failures until all checks pass. Uses glab CLI to monitor pipeline status, inspect failed job logs, apply focused fixes, and report results. Use when the user needs to watch branch CI, iterate on failures until green, or fix CI until all checks pass.
triggers:
- /gitlab-loop-on-ci
- loop-on-ci
- watch-ci
---

# Gitlab Loop on CI

Watch branch CI and iterate on failures until all required checks pass. Uses glab CLI.

## Prerequisites

- glab CLI installed and authenticated (`glab auth status`)
- Git repository with GitLab remote
- Current branch pushed to origin

## Workflow

```
Task Progress:
- [ ] Step 1: Find current branch and latest pipeline
- [ ] Step 2: Wait for CI completion
- [ ] Step 3: If failed, inspect logs and fix
- [ ] Step 4: Commit and push (no hook bypass)
- [ ] Step 5: Repeat until green
```

### Step 1: Find branch and pipeline

```bash
git branch --show-current
glab ci status
```

### Step 2: Wait for CI completion

```bash
glab ci status --live
```

Use `--branch=<name>` if not on the target branch. Exit code reflects pipeline result.

### Step 3: Inspect failed job logs

When pipeline fails:

```bash
glab ci status
glab ci trace <job-name>
```

Run `glab ci trace` without args to interactively select a failed job, or pass the job name from the status output.

### Step 4: Fix and push

1. Implement a focused fix for the single failure cause
2. Commit with a descriptive message
3. Push normally (do not use `--no-verify` or skip hooks)

```bash
git add <files>
git commit -m "<message>"
git push
```

### Step 5: Repeat

After push, return to Step 2. Continue until `glab ci status --live` reports success.

## Guardrails

| Rule | Action |
|------|--------|
| **Scope fixes** | Address one failure cause per commit when possible. Multiple unrelated failures may require multiple commits. |
| **No hook bypass** | Never use `--no-verify`, `--no-gpg-sign`, or similar to skip pre-push hooks. Fix hook issues or get user approval. |
| **Flaky failures** | If the same job fails with a different error or passes on retry, run `glab ci retry <job-name>` once. If it passes, report: "Flaky: job X passed on retry." If it fails again, treat as a real failure. |

## Output

At each iteration, report:

**Current CI status**
- Branch name
- Pipeline status (running/passed/failed)
- Failed job names (if any)

**Failure summary and fixes applied**
- Job name and error excerpt
- Fix applied (brief)
- Commit SHA

**On success**
- MR URL: `glab mr view` (includes web URL in output). With jq: `glab mr view -F json | jq -r '.web_url'`

## glab CI commands reference

| Command | Purpose |
|--------|---------|
| `glab ci status` | Show pipeline status for current branch |
| `glab ci status --live` | Wait until pipeline completes |
| `glab ci status -b <branch>` | Check specific branch |
| `glab ci trace [job-name]` | View job logs (interactive if no job specified) |
| `glab ci retry [job-name]` | Retry a failed job (for flaky handling) |
| `glab ci view` | Interactive pipeline viewer |
