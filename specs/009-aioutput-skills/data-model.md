# Data Model: Declarative AI Skills with Sandboxed `_aioutput/` Results

**Branch**: `009-aioutput-skills` | **Date**: 2026-10-02

## Skill manifest — `skills/<name>/skill.json` (contract v2.0)

| Field | Type | Rule |
|-------|------|------|
| `name` | string | unchanged: `^[a-z0-9][a-z0-9-]{0,63}$`, not reserved |
| `version` | string | semver |
| `description` | string | non-empty |
| `input` | string | `"hook-context@1.0"` |
| `time_budget_seconds` | number, optional | `0 < n ≤ 600`; default 60 |

Removed from v1.1: `output`, `behaviors`, and the `run` entry point.

Required sibling: `prompt.md`, non-empty UTF-8.

**New violations**:

- `prompt`: missing or empty.
- `executable-code`: any file in the dir other than `skill.json` and `*.md`. On POSIX,
  any file with an exec bit is also flagged.

## Routing config — `config/routes.json` v2.0

```json
{
  "version": "2.0",
  "routes": {"pre-commit": ["todo-check"], "pre-push": ["review-notes"]},
  "skills": {
    "todo-check":   {"mode": "sync", "on_failure": "block"},
    "review-notes": {"mode": "async"}
  },
  "sync_ceiling_seconds": 120,
  "run_retention": 50,
  "output_retention": 50
}
```

- `skills.<name>.mode`: `sync` | `async`. Missing or invalid means `async`, with a warning
  if it is invalid.
- `skills.<name>.on_failure`: `block` | `warn` | `skip`; default `warn`. `block` on an
  async skill is ignored with a config warning.
- v1.x `outcomes` is still read as a fallback for `on_failure`, and triggers a deprecation
  warning.

## Bridge config — `config/bridge.json` v2.0

```json
{"version": "2.0", "claude_command": "claude", "model": "",
 "max_turns": 6, "timeout_seconds": 120}
```

`hooks_enabled` and `extra_args` are removed. If present, they are ignored with a warning.
They are never honored.

## Bridge result (bridge-result@2.0)

```json
{"schema_version": "2.0", "status": "ok|bad-request|unavailable|timeout|error",
 "verdict": "pass|fail|null", "reason": "", "report": "",
 "error": "", "duration_ms": 0}
```

- `status: ok` requires a valid structured output.
- A report without a valid verdict gives `status: error` with `verdict: null`.

## Executor statuses

| Status | Meaning | Blockable |
|--------|---------|-----------|
| `success` | sync: verdict pass | — |
| `failure` | sync: verdict fail | **yes** (sync + block rule + pre-commit/pre-push) |
| `error` | Claude unavailable/crashed/invalid output, write failure | no — warn |
| `timeout` | budget or sync ceiling exhausted | no — warn |
| `skipped` | unregistered / invalid skill | no — `block` downgraded |
| `dispatched` | async: handed to the worker | no |
| `dispatch-failed` | async: worker could not be started | no — warn |

## Result file — `_aioutput/<skill>/<YYYYMMDDTHHMMSSZ>-<event>[-N].md`

```markdown
---
skill: todo-check
skill_version: 1.0.0
event: pre-commit
branch: feature-x
mode: sync
verdict: fail
reason: "src/a.py contains TODO-BLOCK"
run_id: 20261002T101530.123456Z-pre-commit
timestamp: 2026-10-02T10:15:30Z
files:
  - src/a.py
---

<Claude's report, verbatim>
```

- Written to `<name>.tmp` first and then `os.replace`d. An existing name gets the next
  `-N` suffix.
- `verdict: invalid` is used when the report arrived but the verdict did not.

## Run record — run-record@1.1 (additive)

Per-skill entries gain these fields:

- `mode`
- `verdict`
- `output_file`: a repo-relative path or null.

The top level gains `async_job`, the job path, or null. Async worker records add
`parent_run` and are named `<parent-id>-async.json`.
