# Agent Memory

Read remembered knowledge before starting a task and record an outcome before
finishing. The skill uses the deployment's shared memory service when
`MEMORY_API_URL` and `MEMORY_TOKEN` are set, and AGENTS.md files otherwise.

## Triggers

This skill is activated by the following keywords:

- `/remember`
- `/recall`

## Shared memory service

Both settings must be non-empty. The skill calls the service with
`/usr/bin/curl` and an argument list. It never uses a shell, never logs the
token, and never trusts the request to name a namespace.

| Command | Effect |
|---|---|
| `python3 <skill-dir>/scripts/memory.py mode` | Print `network` or `file` |
| `python3 <skill-dir>/scripts/memory.py recall` | Print the budgeted index inside `<MEMORY_CONTEXT>` |
| `python3 <skill-dir>/scripts/memory.py remember --fact "<fact>"` | Append one entry to the run's namespace |

The token claims, endpoint contract, idempotency key, and status semantics are
in [`references/api.md`](references/api.md).

## Repository memory

When `MEMORY_API_URL` or `MEMORY_TOKEN` is absent or empty, the skill keeps the
original AGENTS.md behaviour. See [`SKILL.md`](SKILL.md) for the file-mode
guidance.