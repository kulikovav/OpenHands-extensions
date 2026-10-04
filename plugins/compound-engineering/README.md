# Compound Engineering Plugin

Compound Engineering is a set of 36 skills that structure agent work around one loop:
brainstorm the requirements, plan the implementation, work through the plan, simplify
what you wrote, review the result, then capture the learning so the next loop starts
smarter. The skills were created by Every and are vendored here from the upstream
plugin.

## Provenance

| Field               | Value                                                                                           |
| ------------------- | ----------------------------------------------------------------------------------------------- |
| Upstream repository | [EveryInc/compound-engineering-plugin](https://github.com/EveryInc/compound-engineering-plugin) |
| Upstream version    | 3.30.3                                                                                          |
| Upstream commit     | `9af474a70e7f2a844338519ad9e92aafbd92d4fb` (2026-10-01)                                         |
| License             | MIT, Copyright (c) 2025 Every (see `LICENSE.txt`)                                               |
| Vendored content    | `skills/` (36 skill directories)                                                                |

The upstream project is maintained by Kieran Klaassen and Trevin Chow. Report
problems with the upstream skills to the upstream repository. Report problems with
this vendored copy to [OpenHands/extensions](https://github.com/OpenHands/extensions).

## Skills

| Group              | Skills                                                                                                        |
| ------------------ | ------------------------------------------------------------------------------------------------------------- |
| Core loop          | `ce-brainstorm`, `ce-plan`, `ce-work`, `ce-simplify-code`, `ce-code-review`, `ce-compound`                    |
| Around the loop    | `ce-strategy`, `ce-product-pulse`, `ce-sweep`, `ce-compound-refresh`                                          |
| On demand          | `ce-ideate`, `ce-bakeoff`, `ce-pov`, `ce-debug`, `ce-explain`, `ce-doc-review`, `ce-optimize`, `ce-prototype` |
| Git workflow       | `ce-commit`, `ce-commit-push-pr`, `ce-babysit-pr`, `ce-resolve-pr-feedback`, `ce-worktree`                    |
| Autonomous         | `lfg`                                                                                                         |
| Testing and design | `ce-test-browser`, `ce-test-xcode`, `ce-polish`, `ce-dogfood`                                                 |
| Collaboration      | `ce-proof`, `ce-handoff`, `ce-promote`                                                                        |
| Utilities          | `ce-setup`, `ce-noslop`, `wtf`, `ce-retune`, `ce-riffrec-feedback-analysis`                                   |

## Usage

OpenHands loads each skill with a keyword trigger equal to its directory name, so a
request that mentions a skill name activates it. For example, ask the agent to run
`ce-plan` on a feature description, or `ce-code-review` on the current branch.

Keyword matching is whole-token, and `ce-commit` and `ce-compound` are prefixes of
`ce-commit-push-pr` and `ce-compound-refresh`. A request that names one of the longer
skills therefore also activates its shorter relative. Both skills load, and the
longer skill describes the complete flow, so follow it where the instructions
overlap.

The skills write their artifacts under `docs/plans/`, `docs/solutions/`, and
`docs/brainstorms/` by default, and read project configuration from
`.compound-engineering/config.yaml`. Run the `ce-setup` skill in a repository to
create that configuration and report optional tool capabilities.

## Changes made during vendoring

The upstream content is copied with these mechanical changes only:

- `argument-hint` frontmatter was removed. OpenHands does not use it.
- The manifest carries `$schema: https://agent-plugins.org/schemas/1.0.0/plugin.schema.json`.
  The Agent Plugins format requires this field and rejects a manifest without it.
- A `triggers` list with the skill name was added to every `SKILL.md`. Without a
  trigger, the OpenHands SDK loads a skill as always active, which would inject all
  36 skill bodies into every conversation.
- Em dashes in Markdown and YAML content were replaced with plain hyphens, per the
  [extensions repository punctuation style](../../AGENTS.md).

`allowed-tools` and `disable-model-invocation` frontmatter is preserved: the
OpenHands SDK supports both fields. Executable scripts under each skill's `scripts/`
directory are unchanged.

## Updating the vendored copy

1. Check out the upstream commit to vendor.
2. Copy `skills/*` into `plugins/compound-engineering/skills/`.
3. Apply the changes listed above.
4. Update the provenance table and the `version` in `.plugin/plugin.json`.
5. Run `python scripts/sync_extensions.py` and the repository test suite.

## License

MIT. See `LICENSE.txt` for the upstream copyright notice.
