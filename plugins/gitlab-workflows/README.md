# GitLab workflows plugin

GitLab workflow skills built on the `glab` CLI: open merge requests, review and
ship, resolve review feedback, fix CI, loop on CI, and set up the MR-reviewer
automation. The official `gitlab` and `gitlab-issue-to-mr` skills stay in the
skill catalog.

## Skills

| Skill | Use for |
|-------|---------|
| `glab` | The `glab` CLI, its safe commands, and GitLab API calls. |
| `gitlab-commit-push-mr` | Commit, push, and open a merge request, including MR-description-only flows. |
| `gitlab-review-and-ship` | Review changes, close key issues, and ship via a merge request. |
| `gitlab-resolve-mr-feedback` | Judge MR feedback, apply valid fixes, and resolve review threads. |
| `gitlab-fix-ci` | Find failing CI jobs, read their logs, and apply focused fixes. |
| `gitlab-loop-on-ci` | Watch branch CI and iterate until all checks pass. |
| `gitlab-mr-reviewer` | Create the MR-reviewer automation for labelled merge requests. |

## Commands

| Command | Skill |
|---------|-------|
| `/gitlab-workflows:gitlab-commit-push-mr` | `gitlab-commit-push-mr` |
| `/gitlab-workflows:gitlab-review-and-ship` | `gitlab-review-and-ship` |
| `/gitlab-workflows:gitlab-resolve-mr-feedback` | `gitlab-resolve-mr-feedback` |
| `/gitlab-workflows:gitlab-fix-ci` | `gitlab-fix-ci` |
| `/gitlab-workflows:gitlab-loop-on-ci` | `gitlab-loop-on-ci` |
| `/gitlab-workflows:mr-reviewer-setup` | `gitlab-mr-reviewer` |

## Credentials

Set `GITLAB_TOKEN` as a personal or project access token with the `api` scope
and at least the Developer role. The MR-reviewer automation bundle also accepts
a connected GitLab MCP server or integration.