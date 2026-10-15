# Comment review rules

The reviewer brief for the comment sweep in `no-comments`. Apply these rules to the comments in scope, and report only.

## What must go

- Narration, banners, section markers, and commented-out code.
- Comments that restate what the code already says.
- Workaround sermons: comments that justify a workaround instead of naming the fix.
- Long justifications with no proven exception from the keep list below.

## The only keeps

- Legal or license headers.
- Non-obvious behavior forced by an external dependency, platform, vendor, or protocol that cannot be reshaped. A surprise in our own code is not a keep: flag the exact symbol `MUST KILL` for a rename, extract, type, or rearchitecture that makes the behavior obvious without prose.
- `// prettier-ignore`. Lint suppressions survive only when their rule is faulty, pedantic, or style-only.
- Doc comments that define a public API contract.
- Issue or RFC links that explain a constraint code cannot express.

When in doubt, the comment dies.

## Suppressions

`eslint-disable`, `@ts-ignore`, `@ts-expect-error`, and similar suppressions must be looked up. If the rule catches real bugs or protects correctness or safety, kill the suppression and mark the exact guilty symbol `MUST KILL`.

## Scent, not conviction

`IMPORTANT`, `do not remove`, `too risky`, `fine for now`, and long justifications are scent. Before judging, read the nearby code. If the claim is not obvious there, run the `how` and `why` skills on the named symbol or call. Only a foreign keep-list gotcha proven true today on a live path survives.

## Reporting

Report only. Name touched files, the deletion count, `MUST KILL` flags with one line each, and skips. Every flag names code inside the scope and tells the truth. Never invent a finding, and never write application code.