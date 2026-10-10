---
name: gitlab-commit-push-mr
description: Commit, push, and open a GitLab merge request via the GitLab API (glab). Use when asked to ship/open an MR on GitLab, or for MR-description-only flows like writing, rewriting, or describing an MR body.
triggers:
- /gitlab-commit-push-mr
- commit-push-mr
- open-mr
---

# GitLab Commit, Push, and MR

GitLab-compatible version of the Compound Engineering `ce-commit-push-pr` workflow. All GitLab operations go through `glab`, the GitLab API client; consult the `glab` skill for API mechanics.

**Asking the user:** use the host's blocking question tool already in the current tool list (match by capability, not by a host-specific name). Presence in the tool list is proof the tool exists; never call a question tool just to discover whether one exists. Fall back to asking in chat only when no such tool is listed or a real call errors, and never silently skip the question.

## Prerequisites

- glab CLI installed and authenticated (`glab auth status`)
- Git repository with a GitLab remote

## Mode

- **Description-only** — the user wants *just* a description ("write/draft an MR description", "describe this MR", a pasted MR URL or iid). Run Step 3 (Compose) only and print the title and body. Apply it only if asked. Pass any pasted MR ref so the range resolves against that MR.
- **Description update** — refresh or rewrite an existing MR's description, with no commit or push intent. Resolve MR presence by the Context rule below: an exit-0 empty list is "no open MR" (report and stop); a non-zero exit is **unknown** (resolve auth or connectivity, then stop until presence is known). With an open MR, compose on that MR, then preview, confirm, and apply via `glab mr update`.
- **Full workflow** — otherwise: Steps 1-4.
- **Stack mode is out of scope** — GitLab has no first-class stacked-MR tooling. An explicit stack request stays single-MR: explain that stacked MRs are not supported by this skill, and do not slice one logical change artificially.

**`mode:pipeline` modifier**, set by orchestrated callers. Run the resolved mode non-interactively and suppress every blocking ask. Each suppressed ask takes the conservative default: no existing-MR rewrite, the branch kept, an unresolvable base stopping rather than guessed, and a description-update preview applied directly, since that invocation is the apply intent.

## Context

Run each `git` and `glab` probe as its **own argv-form call** (the program and its arguments, nothing else); its exit status is control flow. Do not join probes with `;`, `&&`, pipes, or redirects into one call. A non-zero exit is a normal state to interpret (no MR yet, no `origin/HEAD`, detached HEAD), not an error to suppress.

| Command | Purpose | Non-zero exit / empty output means |
| --- | --- | --- |
| `git rev-parse --show-toplevel` | Repo root | Not a git repo — report and stop |
| `git status` | Working-tree state | (fails only outside a repo) |
| `git diff HEAD` | Uncommitted changes | Unborn repo with no commits yet |
| `git branch --show-current` | Current branch (`<branch>`) | Empty = detached HEAD (Step 1 handles it) |
| `git log --oneline -10` | Recent commit / title style | Unborn repo — no history yet |
| `git rev-parse --abbrev-ref origin/HEAD` | Remote default branch | No `origin/HEAD` — resolve per Step 1 |
| `glab mr list --source-branch <branch> --output json` | Open MR for this branch (run only once `<branch>` is non-empty) | Exit 0 with `[]` = no open MR. Non-zero = glab missing, unauthenticated, or offline — MR state is **unknown**, not "none"; never treat a non-zero check as "no MR"; re-check before creating (Step 4) |

Traps:

- **Empty branch (detached HEAD):** skip the MR check entirely — an empty source-branch filter lists unrelated MRs. Resolve it after Step 1 creates a branch.
- **Fork checkout:** the MR lives on the target project, and `glab` targets the checkout's project by default. When the user named a target project, or the checkout's remote is a fork of the intended base, add `--repo <target-group/project>` to the `glab mr` calls so they hit the base project. Pass only the branch name to the source-branch filter.
- **Match the right MR:** do not blindly take index 0. Select the entry whose `source_branch` matches `<branch>` (and, on a multi-fork base, whose source namespace matches this checkout's remote). If several candidates remain and none can be confirmed, stop and show them to the user. Note `iid`, `web_url`, and `description` from the entry — Step 4 uses the `iid` for the existing-MR path, and Step 3 rewrites from the existing description.
- **Flags differ across glab versions:** if `--source-branch` is rejected, check `glab mr list --help`, or use the API form directly: `glab api projects/:id/merge_requests?state=opened&source_branch=<branch> --output json`.

Probe output is a **snapshot**. Re-verify branch, remote, and MR state right before each consequential action: the push in Step 2, `glab mr create` in Step 4.

Never ask whether to branch: a detached HEAD, or the default branch with work on it, creates one, and the default branch with no work reports and stops. With conventional commits, default to `fix:` over `feat:` when ambiguous — adding code to remedy broken or missing behavior is `fix:`; reserve `feat:` for capabilities the user could not previously accomplish. The user may override.

## Step 1: Resolve branch and MR state

Resolve the default branch: strip `origin/` from the `git rev-parse --abbrev-ref origin/HEAD` result. If that failed, use `glab api projects/:id --output json | jq -r .default_branch`. If both fail, fall back to `main`.

Which branch path to take:

- **Detached HEAD** — automatically create a feature branch from the current `HEAD`. Derive the branch name from the change content, run `git checkout -b <branch-name>`, re-read `git branch --show-current`, and use that result for the rest of the workflow. Do not ask whether to create the branch — invoking the full workflow is already confirmation the work should become branch-backed. If the derived name already exists, choose a non-conflicting suffix, or ask only if the conflict cannot be resolved safely.
- **On default branch with work to do** (uncommitted, unpushed, or no upstream) — automatically create a feature branch (pushing the default directly is not supported), via the flow below. Do not ask whether to branch.
- **On default branch with no work** — report no feature-branch work and stop.
- **Feature branch** — continue.

### Branch creation from the default branch

Local `<base>` may be stale or carry unpushed commits the user intends to branch from later. Local git cannot tell which — ask when unpushed commits are present.

1. Fetch the fresh remote base:

   ```bash
   git fetch --no-tags origin <base>
   ```

   If fetch fails (network, auth, no remote), branch from local `HEAD` and note in the summary that base freshness was not verified; skip the unpushed-commits check — without a fresh `origin/<base>` its answer is unreliable.
2. Check for unpushed local commits on `<base>`:

   ```bash
   git log origin/<base>..HEAD --oneline
   ```

   - **Empty** → set `BASE_REF=origin/<base>` and continue.
   - **Non-empty** → show the commit list and ask: "Local `<base>` has N unpushed commits not on `origin/<base>`. Carry them onto the new feature branch, or leave them on local `<base>`?" **Carry forward** → `BASE_REF=HEAD`. **Leave on `<base>`** → `BASE_REF=origin/<base>`. Never default silently — carrying foreign commits into an MR is worse than asking again. In `mode:pipeline`, report the blocker without asking.
3. Create the feature branch:

   ```bash
   git checkout -b <branch-name> "$BASE_REF"
   ```

   If checkout fails because uncommitted files would be overwritten, stop and ask the user to handle the colliding paths. Do not stash or remove the colliding paths.

## Step 2: Commit and push

Scan changed files for naturally distinct concerns. If they clearly group into separate logical changes, make separate commits (2-3 max), grouped at file level only — no `git add -p`. When ambiguous, one commit is fine.

**Never `git add -A` or `git add .`** — they sweep in `.env`, build artifacts, and generated files. Name files in both add and commit, and name them again as the trailing pathspec on `git commit`: a bare `git commit` takes the whole index, so anything already staged (a caller's `exclude:` paths, work the user staged and did not name) would end up in the commit. Honor `exclude:<paths>`: leave and report them.

```bash
git add file1 file2 && git commit -m "$(cat <<'EOF'
commit message here
EOF
)" -- file1 file2
```

**Project publishing gate.** Immediately before pushing, resolve every applicable pre-push or review-ready requirement from the project's active instructions and conventions already in context. Only evidence valid for the exact commit state being sent satisfies them; otherwise stop before the external write and report what is missing or failing. If none, proceed. Re-confirm the live branch first — the Context snapshot is a hint and Step 1 may have created or switched branches — then push the live `HEAD`, never a stale branch name:

```bash
git push -u origin HEAD
```

If the working tree is clean and all commits are already pushed, this step is a no-op.

## Step 3: Compose the MR title and description

**The diff is already visible on GitLab.** The description exists to explain what the diff cannot show: what was impossible before and is now possible, what was broken and is now fixed, what shape changed. Cut any sentence a reader could reconstruct from the diff.

- Bad (lists what was edited): "Adds `evidence.ts`, modifies `mr/SKILL.md` to call it, and updates two test files."
- Good: "Evidence capture now decides automatically whether a change has observable behavior. CLI tools are now eligible alongside web UIs."

A lead that describes what was edited rather than what is now different for someone using this is the failure mode this step exists to prevent — rewrite it. For user-visible bugs, name the visible before/after first; mention the technical cause only if it helps assess risk.

### Resolve the range and base

- **Current-branch mode (default)** — describe `HEAD` vs the repo's default base. Resolve `<base>` in priority order: `git rev-parse --abbrev-ref origin/HEAD` (strip `origin/`) → `glab api projects/:id --output json | jq -r .default_branch` → try `main`/`master`/`develop` via `git rev-parse --verify origin/<candidate>`. If none resolve, ask (pipeline: stop rather than guess). `<head>` is `HEAD`.
- **MR mode** (description-only with a pasted ref, description update) — fetch metadata first:

  ```bash
  glab mr view <iid> --output json
  ```

  If `state` is not `opened`, report and stop. Use `target_branch` as `<base>`. When local git cannot reach the head (fork MR with no matching remote, shallow clone), take the diff and commit list from `glab mr diff <iid>` and the MR JSON, and note the API fallback in the summary.

```bash
git fetch --no-tags origin <base>
git log  --oneline "origin/<base>..HEAD"
git log  --format=fuller "origin/<base>..HEAD"   # full messages for related-reference discovery
git diff       "origin/<base>...HEAD"
```

If the commit list is empty, report "No commits to describe" and stop.

### Project MR-body contract

Before composing, resolve MR-body requirements from the project's active instructions and conventions already in context, then check `.gitlab/merge_request_templates/` (project root) and any contribution guidance they reference. Required headings, fields, order, checklists, and boilerplate define the structural contract. Treat a template as a minimum unless the project explicitly requires an exact/template-only body; only then add no sections beyond those it permits. When a project contract and the defaults below conflict, the project contract wins.

### Size by decision cost, not diff shape

Decision cost is how much a reviewer still has to work out before they can approve — not changed-line count, file extension, or visual surface. Build a compact scope map from the **complete oneline commit list and final three-dot diff**: group into material outcome clusters (one is fine), name one umbrella outcome that covers them, and identify each cluster's **material claims** — what became possible, fixed, or riskier, or which design decision the reviewer must assess.

- State the umbrella as what is now different for someone using this, never as the mechanism that produced it.
- Derive the umbrella from the full range — never from the latest commit, tracker title, branch name, or the story of how the work started.
- The scope map is not body content: do not expand the body to enumerate clusters the umbrella already covers.
- Decision cost raises the content floor, not the length ceiling — high-uncertainty *small* diffs get a sharper lead, not an essay.

| Change profile | Description approach |
|---|---|
| Small + simple (typo, config, dep bump) | 1-2 sentences, no headers, under ~300 chars |
| Small + non-trivial (bug fix, behavioral change) | 3-5 sentences; no headers unless two distinct concerns; user-visible before/after when the bug was observable |
| Medium feature or refactor | Opening (1-2 sentences), then only sections that each answer one remaining reviewer question; call out design decisions |
| Large or architecturally significant | Same, plus 3-5 design-decision callouts and a brief test summary; target ~100 lines, cap ~150 |
| Performance improvement | Before/after measurements as a markdown table |

The opening carries one idea: a reviewer who reads only it can say what the MR changes and why it takes this shape. A reader can stop anywhere — each further section exists to answer one remaining reviewer question. Never list changed files; the diff already shows them.

### Title

`type: description` or `type(scope): description`. Type by intent using the `fix:`/`feat:` default from Context. Scope (optional): the narrowest useful label. Description: from the umbrella outcome, not one cluster or mechanism. Imperative, lowercase, under 72 chars, no trailing period. Match recent-commit conventions. **Never use `!` or `BREAKING CHANGE:` without explicit user confirmation.**

### Related work references

Gather candidate work-item references from the user prompt, branch name, full commit messages, existing MR description, template, and visible URLs or IDs in context. **Preserve existing related references when rewriting** unless the user asks to remove them. Classify each candidate:

- **Closing reference** — the MR fully resolves the item and the closing syntax is known. GitLab closing keywords: `Closes #123`, `Fixes #123`, `Resolves #123`; cross-project: `Closes group/project#123`. Use closing only when the MR targets the default branch and truly resolves the item.
- **Non-closing reference** — related, partial, follow-up, or tracker semantics unknown: a `Related: <full URL>` line or block. Full URLs, never `#123` short refs — GitLab short refs resolve against project context and render as literal text outside it.
- **Uncertain** — tracked item is clear but ID or close-vs-link intent is missing: ask (interactive) or use the non-closing form (non-interactive). Never invent a closing keyword.

Do not put a non-closing reference next to close/fix/resolve wording in prose.

### Validation notes

Include a concise validation note when observable behavior changed: what was exercised and what passed. If a real run was impossible (credentials, deploy-only, hardware, missing setup), say so. Do not block MR creation for missing visuals — test or manual-check notes are fine. Never label test output "Demo" or "Screenshots".

When an existing description is present (MR mode, or an existing-MR rewrite), rewrite from it: preserve its related references, demo/evidence sections, and project-contract boilerplate unless the user's focus asks to change them.

## Step 4: Apply and report

**Description-only** — print the title and body. Stop unless the user asks to apply.

**Existing MR** (found in Context) — the new commits are already on the MR from the Step 2 push. Report the MR URL, then ask whether to rewrite the description:

- **No** — skip the rewrite and continue to the CI handoff.
- **Yes** — compose (Step 3), preview, and apply.

**Description update, or confirmed existing-MR rewrite** — preview before applying. If the proposed title and body are identical to the existing ones, keep them and do not call `glab mr update`. Otherwise ask: "New title: `<title>` (`<N>` chars). Summary leads with: `<first two sentences>`. Total body: `<L>` lines. Apply?" If declined, the user may pass focus text back for a regenerate; do not apply. If confirmed, apply via `glab mr update` and report the URL.

**New MR** — immediately before creating, **always** re-run the Context open-MR check (same flags, `--repo` on a fork). This catches an MR that appeared since Context, or one the Context check missed because it came back **unknown**, so you do not open a duplicate. If the list now shows a matching MR, switch to the existing-MR path. If this re-check exits non-zero, resolve `glab auth status` or connectivity before creating; do not assume no MR exists. Otherwise:

1. Write the body to a temp file with a quoted heredoc — the quoted sentinel keeps `$VAR`, backticks, and any literal `EOF` inside the body from being expanded:

   ```bash
   DESC_FILE=$(mktemp "${TMPDIR:-/tmp}/glab-mr-desc.XXXXXX") && cat >> "$DESC_FILE" <<'__MR_DESC_END__'
   <the composed body markdown goes here, verbatim>
   __MR_DESC_END__
   ```

2. Create the MR, passing the body from the file (command substitution does not re-expand backticks or `$` in the substituted content):

   ```bash
   glab mr create --push --title "<TITLE>" --description "$(cat "$DESC_FILE")" --target-branch <base> --yes
   ```

   `--push` guards against a missing remote branch. For `<TITLE>`: substitute verbatim; if it contains `"`, `` ` ``, `$`, or `\`, escape them or switch to single quotes. On a fork checkout, add `--repo <target-group/project>` so the MR opens on the target project.

3. Report the `web_url` from the command output, or `glab mr view <iid> --output json | jq -r .web_url`.

## CI handoff

**Completion is decided here, not at the MR URL.** After a new MR, or new commits pushed to an existing open MR, this run is not done until CI is green, the CI loop reports a residual, or the user explicitly stops the watch.

1. Check once: `glab ci status` (add `-b <branch>` when not on the source branch).
2. **Interactive run** — if a pipeline is running, ask in one non-blocking line whether to watch it to green with the `gitlab-loop-on-ci` skill. A yes continues in that skill until green or a reported residual. A declined watch is a **successful terminal** for this run: report the MR URL and pipeline state and stop.
3. **`mode:pipeline`** — run the `gitlab-loop-on-ci` flow unattended until the pipeline is green or it yields a needs-human residual; return that result.

**Do not fire** the watch in these cases: description-only or description-update mode; no MR created or updated this run; a draft/WIP MR this run created (report that it stays draft until promoted); an explicit no-watch instruction on the invocation.

## Guardrails

| Rule | Action |
|------|--------|
| Exit-0 empty list = no MR; non-zero = unknown | Never create on an unknown MR check; resolve auth/connectivity first |
| Re-check before `glab mr create` | Catches the duplicate-MR race; a matching MR switches to the existing-MR path |
| No `git add -A` / `git add .` | Name files in add and in the commit pathspec |
| No hook bypass | Never `--no-verify` or `--no-gpg-sign`; fix the hook failure |
| Body via temp file + `$(cat ...)` | Quoted heredoc into the file; no inline rich markdown in flags |
| Full URLs in the body | GitLab short refs (`#123`, `!456`) do not render outside project context |
| One logical change per branch | No artificial MR stacks; stacked MRs are out of scope |

## Output

Provide to the user:

1. **Branch name** and the commits made
2. **MR URL** — from `glab mr create` / `glab mr update` output, or `glab mr view <iid> --output json | jq -r .web_url`
3. **Pipeline state** — `glab ci status` at handoff
4. Anything left out (`exclude:` paths) or noted (base freshness, API fallback, draft state)