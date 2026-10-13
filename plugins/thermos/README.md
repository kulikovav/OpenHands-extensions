# Thermos Plugin

Thermo-nuclear branch review for OpenHands agents: deep correctness and security audits, harsh maintainability rubrics, and subagent orchestration. The plugin was created by Cursor and is vendored here from the upstream plugin.

## Provenance

| Field               | Value                                                                          |
| ------------------- | ------------------------------------------------------------------------------ |
| Upstream repository | [cursor/plugins](https://github.com/cursor/plugins) (`thermos`)                |
| Upstream version    | 1.0.0                                                                          |
| Upstream commit     | `c86f349b102feb91f1966f8a6a60882a4e601b50` (2026-10-13)                        |
| License             | MIT, Copyright (c) 2026 Cursor (see `LICENSE`)                                 |
| Vendored content    | `skills/` (3 skill directories) and `agents/` (2 subagent definitions)         |

Report problems with the upstream content to the upstream repository. Report problems with this vendored copy to [OpenHands/extensions](https://github.com/OpenHands/extensions).

## Skills

| Skill | Description |
|:------|:------------|
| `thermo-nuclear-review` | Deep branch audit (bugs, breakages, security, devex, feature-gate leaks). |
| `thermo-nuclear-code-quality-review` | Strict maintainability audit (code-judo, 1k-line rule, spaghetti, boundaries). |
| `thermos` | Run both review subagents and synthesize their findings. |

## Agents

| Agent | Description |
|:------|:------------|
| `thermo-nuclear-review-subagent` | Task subagent for the deep review rubric (diff-scoped). |
| `thermo-nuclear-code-quality-review-subagent` | Task subagent for the code-quality rubric (diff-scoped). |

## Usage

Load the plugin from the extensions registry:

```python
from openhands.sdk import Conversation
from openhands.sdk.plugin import PluginSource

conversation = Conversation(
    agent=agent,
    workspace=Path.cwd(),
    plugins=[
        PluginSource(
            source="github:OpenHands/extensions",
            repo_path="plugins/thermos",
        )
    ],
)
```

Each skill carries keyword triggers, so a request that names one activates it. Ask for a
"thermo-nuclear review" for the deep audit, a "thermo-nuclear code quality review" for the
maintainability audit, or "thermos" to run both.

**Double review (thermos):**

1. Gather `git diff main...HEAD` and the full contents of the changed files.
2. Invoke both subagents with the task tool, one call each, using
   `subagent_type: "thermo-nuclear-review-subagent"` and
   `subagent_type: "thermo-nuclear-code-quality-review-subagent"`. Each call blocks until
   the subagent returns.
3. Synthesize the prioritized, deduplicated findings.

**Single skill:** invoke `thermo-nuclear-review` or `thermo-nuclear-code-quality-review`
directly, or the matching subagent after gathering diff context.

## Changes made during vendoring

The upstream content is copied with these mechanical changes only:

- The manifest was rewritten to the Agent Plugins 1.0.0 format: it carries
  `$schema: https://agent-plugins.org/schemas/1.0.0/plugin.schema.json` and keeps only the
  fields that schema allows (`displayName`, `logo`, `category`, `tags`, `skills`, and
  `agents` were dropped; the `skills/` and `agents/` directories are discovered by
  convention). The description was trimmed to the content this copy ships, dropping
  upstream references to take-the-wheel and FSD merge-ready flows that are not part of
  the vendored files.
- A `triggers` list was added to every `SKILL.md`. Each skill also sets
  `disable-model-invocation`, so without a trigger a skill would never activate.
- The `thermos` skill and both agent definitions describe delegation through the OpenHands
  task tool (`subagent_type`), which runs subagents synchronously, instead of Cursor's
  background `Task` calls.
- Em dashes and en dashes in Markdown and YAML content were replaced with plain hyphens,
  per the [extensions repository punctuation style](../../AGENTS.md).

`disable-model-invocation` frontmatter is preserved: the OpenHands SDK supports the field,
and the skills activate through their keyword triggers.

## Updating the vendored copy

1. Check out the upstream commit to vendor.
2. Copy `skills/` and `agents/` into `plugins/thermos/`.
3. Apply the changes listed above.
4. Update the provenance table and the `version` in `.plugin/plugin.json`.
5. Run `python scripts/sync_extensions.py` and the repository test suite.

## License

MIT. See `LICENSE` for the upstream copyright notice.