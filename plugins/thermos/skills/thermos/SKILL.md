---
name: thermos
description: "Launch both thermo-nuclear review subagents, then synthesize their findings. Use for thermos, double thermo review, or combined bug/security and code-quality branch audits."
triggers:
  - thermos
  - double thermo review
  - thermo review
disable-model-invocation: true
---

# Thermos

Run the two thermo review passes as subagents, then synthesize their results.

## Workflow

1. Determine the review scope from the user request, PR, current branch, or relevant changed files.
2. Gather the diff and any file/context excerpts needed for reviewers to evaluate the change without guessing.
3. Launch both subagent reviews with the task tool, one call each, passing `subagent_type`:
   - `subagent_type: "thermo-nuclear-review-subagent"` for bugs, breakages, security, devex regressions, feature-flag leaks, and other branch-audit risks.
   - `subagent_type: "thermo-nuclear-code-quality-review-subagent"` for maintainability, structure, file-size growth, spaghetti, abstractions, and codebase-health risks.
   Each task call blocks until its subagent returns, so issue the calls one after the other. When the host supports parallel delegation, launch both in one message instead.
4. Pass each subagent the same scoped diff/file context and ask it to return prioritized findings with file references and evidence.
5. After both finish, synthesize the results with findings first, deduplicated across reviewers. Weight overlapping findings more heavily, resolve disagreements with your own judgment, and keep summaries brief.

If individual subagent summaries are already visible to the user, do not restate them wholesale. Surface the unified verdict, the highest-signal findings, and any remaining uncertainty.