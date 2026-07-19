# Data Model: Run Observability

**Branch**: `008-run-observability` | **Date**: 2026-07-19

## Entity: OutcomeRule

`{"on_failure": "block" | "warn" | "skip"}` keyed by skill name under `outcomes` in
routes config v1.1. Missing/invalid → default warn (FR-009).

## Entity: OutcomeEvaluation (per skill)

| Field | Notes |
|-------|-------|
| `skill`, `status`, `duration_ms`, `detail` | copied from ExecutionResult (006) |
| `rule` | the matched rule object, or `null` (default applied) |
| `outcome` | `block` / `warn` / `skip` / `none` (success) |
| `reason` | human sentence naming rule + status (SC-003) |

## Entity: RunRecord / RunHistory

See [contracts/run-record.md](./contracts/run-record.md). Store: `logs/runs/`,
lexically-sortable ids, retention prune to `run_retention` (default 50) after each write.

## Interfaces (src/run_records.py)

```python
BLOCK_EXIT_CODE = 10
evaluate_outcomes(summary: dict, outcome_rules: dict, event: str)
    -> dict  # {"results": [OutcomeEvaluation…], "final_outcome", "block_downgraded", "notes"}
write_run_record(runs_dir: str, record: dict, retention: int) -> str | None  # path, best-effort
build_run_record(context, plan, summary, evaluation, warnings) -> dict
list_runs(runs_dir: str) -> list[dict]   # newest first, lightweight
load_run(runs_dir: str, run_id: str) -> dict | None
```

## Flow

```text
router main():
  plan = select_plan(...)            (004)
  summary = execute_plan(...)        (006)
  evaluation = evaluate_outcomes(summary, config["outcomes"], event)   ← 008
  record_path = write_run_record(logs/runs, build_run_record(...), retention)
  messages: block → "[hook blocked] …" stderr;  warn → "[router warning] …";  skip → none
  exit: BLOCK_EXIT_CODE if final block else 0
hook (_finish_hook): 10 → exit 1 (abort);  other non-zero → warn, exit 0;  0 → exit 0
```
