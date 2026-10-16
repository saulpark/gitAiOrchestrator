# Skill Contract — v2.0

> **Superseded in part by 010** — Claude may read the whole repository (the change set is the run's focus, not its limit), runs with its working directory pinned to the repo root, and `max_turns` defaults to 20. See `specs/010-repo-wide-context/plan.md`.

**Supersedes** `specs/005-skill-contract/contracts/skill-contract.md` (v1.1). This is a
major bump: executable skills are removed.

## What is a skill?

```text
skills/<dir>/
├── skill.json   # metadata manifest
└── prompt.md    # the task Claude performs, in plain language
```

A skill is **data**. It contains no code, and any executable file in the directory makes
the skill invalid. The framework sends the prompt to Claude with the hook context. Claude
can only read the repository, never change it. The framework then writes Claude's report
to `_aioutput/<name>/`.

Register exactly as before: `python src/skill_registry.py register skills/<dir>`.

## Manifest (`skill.json`)

| Field | Required | Rule |
|-------|----------|------|
| `name` | yes | `^[a-z0-9][a-z0-9-]{0,63}$`; not `registry`/`contract`/`skills` |
| `version` | yes | semver `X.Y.Z` |
| `description` | yes | non-empty |
| `input` | yes | `"hook-context@1.0"` |
| `time_budget_seconds` | no | `0 < n ≤ 600`; default 60 |

```json
{"name": "todo-check", "version": "1.0.0",
 "description": "Fails when staged files contain TODO-BLOCK markers",
 "input": "hook-context@1.0", "time_budget_seconds": 45}
```

## Prompt (`prompt.md`)

Describe what Claude should examine and what to report. The framework wraps it with:

- the event, the branch and the changed files;
- the instruction to examine only those files;
- the output instruction:
  - `verdict` — `pass`/`fail`;
  - `reason` — one line;
  - `report` — markdown, which becomes the body of the result file.

Write the prompt so that `fail` means "this change should not go in". It only blocks if
the operator configured the skill as `sync` + `on_failure: block`.

## What Claude can and cannot do

| Can | Cannot |
|-----|--------|
| Read, Grep, Glob any file inside the repository (010) | Write, Edit or delete any file |
| | Run shell commands or code |
| | Use the web or MCP servers |
| | Be widened by user/project Claude settings |

## How the skill runs — operator policy in `config/routes.json`, not here

- `mode: async` (default): detached. The git command never waits and never blocks.
- `mode: sync`: the git command waits, up to the budget and the sync ceiling. A `fail`
  verdict blocks only with `on_failure: block` on pre-commit/pre-push.

## Violations reported by `register` / `validate`

`name`, `name-reserved`, `version`, `description`, `input`, `time-budget`, `prompt`
(missing/empty), `executable-code` (any non-`.md` file besides `skill.json`, or any file
with an exec bit), `missing-manifest`.
