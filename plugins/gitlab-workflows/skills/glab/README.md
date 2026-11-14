# glab

GitLab CLI (glab) for working with GitLab from the command line. Read this skill before running any `glab` or GitLab API command. It applies to every GitLab operation, whether reading or writing: merge requests, issues, work items, discussions and threaded replies, comments, CI/CD pipelines, releases, packages, members, and project settings.

## Triggers

This skill is activated by the following keywords:

- `glab`
- `gitlab-cli`

## Details

`glab` is pre-configured and available in the environment. Prefer it over raw API calls for every GitLab operation.

The skill carries a quick reference for issues, merge requests, and CI/CD. It also names the failure modes that are easy to hit in a non-interactive agent shell:

- `-m` is required on `note` commands. Without it, the command opens `$EDITOR` and hangs.
- Long or Markdown bodies go through stdin or a file, never through inline flags.
- `glab api` auto-prepends `/api/v4/`, so paths stay relative.
- `-F` reads `@file` as a string; `-f` sends a literal value. A body that starts with `@` must use `-f`.
- `glab ci view` and `glab ci trace` block the shell. Use `glab ci status` or `glab ci get` instead.
- Short references such as `#123` render as literal text outside their project. Use full URLs in comment bodies.