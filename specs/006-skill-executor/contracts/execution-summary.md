# Contract: Execution Summary & Executor CLI

**Branch**: `006-skill-executor` | **Date**: 2026-07-18
**Schema version**: execution-summary `1.0`; DispatchResult bumped to `1.1`

## Executor CLI (FR-009 — invocable in isolation)

```sh
python3 src/execute_skills.py [--skills-dir skills] [--default-budget 30] skill-a skill-b < context.json
```

- argv: ordered execution plan (skill identifiers)
- stdin: hook context JSON (003 schema) — passed **unmodified** to every skill (FR-002)
- stdout: one ExecutionSummary JSON line
- exit code: **always 0** (FR-007)

## ExecutionSummary (`execution-summary@1.0`)

```json
{
  "schema_version": "1.0",
  "event": "pre-commit",
  "overall": "partial-failure",
  "duration_ms": 1234,
  "results": [
    {"skill": "doc-sync", "status": "success", "duration_ms": 210,
     "detail": "3 docs regenerated", "result": {"schema_version": "1.0", "skill": "doc-sync", "status": "ok", "summary": "3 docs regenerated", "details": {}}},
    {"skill": "slow-one", "status": "timeout", "duration_ms": 30000,
     "detail": "exceeded time budget (30s)", "result": null},
    {"skill": "ghost", "status": "skipped", "duration_ms": 0,
     "detail": "'ghost' not registered", "result": null}
  ]
}
```

| Field | Rules |
|-------|-------|
| `overall` | `success` (all success) \| `partial-failure` (mixed) \| `failure` (all non-success) \| `empty` (zero skills) |
| `results[].status` | `success` \| `failure` \| `timeout` \| `skipped` |
| `results[].detail` | human-readable; skill's `summary` on success, error description otherwise |
| `results[].result` | parsed `skill-result@1.0` object, or `null` when unavailable |
| `results[].duration_ms` | wall-clock per skill; integer |

Every plan produces a summary — empty, all-fail, all-timeout included (SC-003), emitted
immediately after the last skill (SC-005).

## Per-skill execution rules

1. Resolve via `skills/registry.json` (005). Unresolvable → `skipped`, continue.
2. Budget: manifest `time_budget_seconds` if present, else `--default-budget` (30 s).
3. Run `skills/<dir>/run`, context JSON on stdin, cwd = repo root.
4. Exit 0 + parseable `skill-result@1.0` on stdout → `success`.
5. Exit 0 + malformed stdout → `failure` (`malformed output…`).
6. Non-zero exit → `failure` (`exit N: <stderr excerpt>`).
7. Budget exceeded → child killed, `timeout`.
8. Any executor-level exception for one skill → `failure`, remaining skills still run (FR-003).

## DispatchResult v1.1 (router stdout, supersedes 004 v1.0)

Additions: top-level `overall` and `execution` (the embedded ExecutionSummary); per-result
`status` and `duration_ms`. The 004 `outcome` vocabulary is preserved and derived:
success→`invoked`, skipped→`unresolvable`, failure/timeout→`failed`.

## Skill contract v1.1 addendum

`skill.json` may declare optional `time_budget_seconds` (number, 0 < n ≤ 600). Absent →
system default. Invalid value → registration violation `time-budget`.
