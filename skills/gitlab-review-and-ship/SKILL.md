---
name: gitlab-review-and-ship
description: Run a structured review, close key issues, and ship changes via MR. Use when reviewing changes before shipping, closing critical issues, or opening/updating a merge request.
triggers:
- /gitlab-review-and-ship
- review-and-ship
- ship-mr
---

# GitLab Review and Ship

Review changes, fix critical issues, and ship via merge request. Uses glab CLI for GitLab API.

## Prerequisites

- glab CLI installed and authenticated (`glab auth status`)
- Git repository with GitLab remote

## Workflow

```
Task Progress:
- [ ] Step 1: Review diff against base branch for behavior-impacting risks
- [ ] Step 2: Run or update tests for changed behavior
- [ ] Step 3: Fix critical issues before finalizing
- [ ] Step 4: Commit selective files with concise message
- [ ] Step 5: Push branch and open or update MR
```

### Step 1: Review diff

```bash
git fetch origin main
git diff origin/main...HEAD
git status
```

Identify behavior-impacting risks: correctness, security, regressions. Classify findings as critical, warning, or note.

### Step 2: Run tests

Run tests that cover changed behavior. Update tests if behavior changed intentionally.

### Step 3: Fix critical issues

Address critical findings before committing. Do not bypass or defer critical fixes.

### Step 4: Commit

```bash
git add <selective-files>
git commit -m "<concise message>"
```

Keep commits focused. Avoid unrelated file changes.

### Step 5: Push and MR

```bash
git push origin HEAD
glab mr create -t "<title>" -d "<description>" -b main --yes
# Or if MR exists:
glab mr update
```

**Update existing MR**:

```bash
glab mr view
glab mr update -t "<title>" -d "<description>"
```

## Guardrails

- Prioritize correctness, security, and regressions over style-only comments
- Keep commits focused; avoid unrelated file changes
- If pre-commit checks fail, fix the issues rather than bypassing hooks

## Output

Provide to the user:

1. **Findings summary**:
   - Critical: Must fix
   - Warning: Should fix
   - Note: Optional improvement

2. **Tests run and outcomes**: What ran, pass/fail

3. **MR URL**: From `glab mr create` output or `glab mr view --web`
