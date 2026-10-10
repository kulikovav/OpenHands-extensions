# GitLab Review and Ship

Run a structured review, close the key issues, and ship the changes through a merge request. Use when reviewing changes before shipping, closing critical issues, or opening or updating a merge request.

## Triggers

This skill is activated by the following keywords:

- `/gitlab-review-and-ship`
- `review-and-ship`
- `ship-mr`

## Details

Reviews changes, fixes critical issues, and ships through a merge request, using the `glab` CLI for the GitLab API.

```
Task Progress:
- [ ] Step 1: Review diff against base branch for behavior-impacting risks
- [ ] Step 2: Run or update tests for changed behavior
- [ ] Step 3: Fix critical issues before finalizing
- [ ] Step 4: Commit selective files with concise message
- [ ] Step 5: Push branch and open or update MR
```

Findings are classified as critical, warning, or note, and critical findings are fixed before the commit. Commits stay focused and never bypass failing hooks.