# pstack Plugin

Rigorous engineering skills for OpenHands agents: verification against real artifacts, root-cause fixes, hard review, plain prose, and 24 one-rule principles. The plugin was created by Lauren Tan (poteto) for Cursor and is vendored here from the upstream plugin, without its subagent-orchestration layer.

## Provenance

| Field               | Value                                                                    |
| ------------------- | ------------------------------------------------------------------------ |
| Upstream repository | [cursor/plugins](https://github.com/cursor/plugins) (`pstack`)           |
| Upstream version    | 0.15.25                                                                  |
| Upstream commit     | `850d7f2e9f5e55dff7eb00a0a479337fe79eb22f` (2026-10-14)                  |
| License             | MIT, Copyright (c) 2026 Lauren Tan (see `LICENSE`)                       |
| Vendored content    | `skills/` (49 skill directories: 25 workflow skills and 24 principles)   |

Report problems with the upstream content to the upstream repository. Report problems with this vendored copy to [OpenHands/extensions](https://github.com/OpenHands/extensions).

## What is not vendored

The upstream plugin centers on `poteto-mode`, a subagent orchestrator that routes work to `poteto-agent` and per-role models. This copy leaves that layer out:

- `poteto-mode` (the mode skill, its 23 playbooks, and its orchestration scripts).
- `arena`, `swarm`, and `interrogate` (parallel attempts, worker fan-out, and multi-model review panels).
- `setup-pstack` (per-role model routing through a Cursor always-applied rule).
- `agents/` (`poteto-agent` and `comment-sicko` subagent definitions).
- `automations/benny`, `docs/guide`, and `assets/` (a dormant automation pack, the Cursor walkthrough, and the logo the 1.0.0 manifest no longer references).

The workflow skills below keep their upstream delegation steps, where they spawn one or a few Task subagents for fan-out or review.

## Skills

| Skill | Description |
|:------|:------------|
| `architect` | Sketch types, signatures, and module structure before code; implement against the chosen sketch. |
| `automate-me` | Draft or revise a personal `-mode` skill from the user's working habits. |
| `benchmark-checklist` | Vet a perf measurement before reporting or acting on it. |
| `blast-radius` | Find what a change could break outside the diff, and prove the one fact it is safe because of. |
| `bro` | Restate the last message in plain human language. |
| `correct` | Turn repeated agent mistakes into structure: architecture, types, lint, tests, and docs last. |
| `create-verification-skill` | Generate a project-local verification skill that drives the app the way a user does. |
| `figure-it-out` | Design an auditable workflow for work no narrower skill fits. |
| `how` | Explain how a subsystem works: architecture, runtime flow, placement, and ownership. |
| `in-your-own-words` | Restate the goal and the problem before starting. |
| `ketchup` | Catch the user up on what changed in this chat since their last message. |
| `maintain-verification-skill` | Keep a verification skill and its feature map honest with source and live passes. |
| `make-bot-ui` | Build a page whose buttons wake a Grok Bot over a webhook. |
| `no-comments` | Strip comments before review with a fresh reviewer, then fix accepted findings. |
| `poteto-help` | Route pstack questions to the right skill or principle. |
| `recall` | Rebuild recent working context from chat history and the shared record. |
| `reflect` | Mine the session for learnings and route each to a skill edit. |
| `sharpen` | Aim a task higher before starting: expert approach, real goal, right specificity. |
| `show-me-your-work` | Keep a reviewable decision trail for long or unattended runs. |
| `tdd` | Write the failing test first when a cheap local test path exists. |
| `teach` | Explain a body of work plainly, built from `how` and `why`. |
| `technical-writing` | Layered writing standard for docs, RFCs, readmes, PR descriptions, and commit messages. |
| `typescript-best-practices` | TypeScript discipline grounded in syntax. |
| `unslop` | Cut AI tells from any writing. |
| `why` | Investigate why code is shaped this way, with parallel evidence and citations. |

## Principles

Twenty-four one-rule skills. Agents read and cite them by name; each is also loadable on demand.

| Principle | Group | Rule |
|:----------|:------|:-----|
| `principle-laziness-protocol` | core | Bias toward deletion and the smallest change that solves the problem. |
| `principle-foundational-thinking` | core | Get the data structures right so downstream code becomes obvious. |
| `principle-redesign-from-first-principles` | core | Redesign as if the requirement had been a foundational assumption from day one. |
| `principle-attack-the-premise` | core | Question the premise instead of writing another fix that assumes it. |
| `principle-subtract-before-you-add` | core | Remove dead weight first, then build on the simpler base. |
| `principle-minimize-reader-load` | core | Count layers between question and answer; collapse one-caller wrappers. |
| `principle-outcome-oriented-execution` | core | Converge on the target architecture; do not preserve throwaway intermediate states. |
| `principle-experience-first` | core | Choose user delight over implementation convenience. |
| `principle-exhaust-the-design-space` | core | Build 2-3 competing prototypes and compare before committing. |
| `principle-build-the-lever` | core | Build the tool that does or proves the work; the tool is the artifact a reviewer reruns. |
| `principle-model-the-domain` | architecture | Encode the domain in a structure instead of scattered conditionals. |
| `principle-boundary-discipline` | architecture | Guards at system boundaries; trust internal types; keep business logic pure. |
| `principle-type-system-discipline` | architecture | Make illegal states unrepresentable; parse external data at boundaries. |
| `principle-make-operations-idempotent` | architecture | Converge to the same end state regardless of partial prior runs. |
| `principle-migrate-callers-then-delete-legacy-apis` | architecture | Migrate callers and delete the old API in the same wave. |
| `principle-separate-before-serializing-shared-state` | architecture | Eliminate sharing first; serialize only when one shared writer is a real invariant. |
| `principle-prove-it-works` | verification | Verify against the real artifact, not a proxy or a self-report. |
| `principle-fix-root-causes` | verification | Trace each symptom to its root cause and fix it there. |
| `principle-sequence-verifiable-units` | verification | Break work into small units that each end in a verifiable state. |
| `principle-test-behavior-not-implementation` | verification | Call the code the way its users do and assert the observed result. |
| `principle-explain-the-number` | verification | Find what limits a measured number before you trust or report it. |
| `principle-guard-the-context-window` | delegation | Route bulk to subagents; keep summaries in the main thread. |
| `principle-never-block-on-the-human` | delegation | Proceed, present the result, let the human course-correct. |
| `principle-encode-lessons-in-structure` | meta | Encode a repeated instruction as a lint, flag, check, or script instead of more text. |

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
            repo_path="plugins/pstack",
        )
    ],
)
```

Each skill carries keyword triggers, so a request that names one activates it. Ask a "how does X work" question for `how`, ask "why was it built this way" for `why`, ask for "tdd" or "unslop" by name, or say "poteto help" to route a question.

## Changes made during vendoring

The upstream content is copied with these changes:

- The manifest was rewritten to the Agent Plugins 1.0.0 format: it carries
  `$schema: https://agent-plugins.org/schemas/1.0.0/plugin.schema.json` and keeps only the
  fields that schema allows (`displayName`, `logo`, `category`, `tags`, `skills`, and
  `agents` were dropped; the `skills/` directory is discovered by convention). The
  description was trimmed to the content this copy ships.
- A `triggers` list was added to every `SKILL.md`. Every skill sets
  `disable-model-invocation`, so without a trigger a skill would never activate. The field
  is preserved: the OpenHands SDK supports it, and the skills activate through their
  keyword triggers.
- The subagent-orchestration layer was removed (see "What is not vendored"). References to
  it were rewritten to single-agent equivalents, or deleted where the step had no
  single-agent meaning: `architect` spawns two candidate runners directly instead of
  running `arena`, `blast-radius` asks a second model directly, `figure-it-out` and
  `poteto-help` point at this README's principle index instead of `poteto-mode`.
- Per-role model routing was removed. The `pstack-models.mdc` role lines and the Cursor
  model slugs are gone; the skills use the session's default model, or a per-subagent
  choice when the host offers one.
- `no-comments` spawns a `generalPurpose` reviewer with a new
  `references/comment-rules.md` brief, re-homed from the `comment-sicko` definition.
  `poteto-help` was retargeted to the vendored skill set, and its `references/recipes.md`
  and `references/prompting.md` were adapted to match.
- Em dashes, en dashes, and curly quotes in the Markdown content were replaced with plain
  ASCII, per the [extensions repository punctuation style](../../AGENTS.md).
- Host-environment references stay as upstream: the Cursor transcript paths in `recall`,
  `reflect`, `automate-me`, and `show-me-your-work`, and the `create-skill` and
  `.cursor/skills/` references in `automate-me` and `create-verification-skill`. They work
  in Cursor and are the first things to adapt for another host.

## Updating the vendored copy

1. Check out the upstream commit to vendor.
2. Copy the 25 workflow skills and the 24 `principle-*` skills into `plugins/pstack/skills/`.
3. Re-apply the changes listed above.
4. Update the provenance table and the `version` in `.plugin/plugin.json`.
5. Run `python scripts/sync_extensions.py` and the repository test suite.

## License

MIT. See `LICENSE` for the upstream copyright notice.