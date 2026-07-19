# Contract: Run Record & Outcome Enforcement

**Branch**: `008-run-observability` | **Date**: 2026-07-19
**Schema versions**: run-record `1.0`; routes config `1.1`; DispatchResult `1.2`

## RunRecord (`logs/runs/<id>.json`, `run-record@1.0`)

```json
{
  "schema_version": "1.0",
  "id": "20260719T120301.123456Z-pre-commit",
  "event": "pre-commit",
  "timestamp": "2026-07-19T12:03:01Z",
  "branch": "feature-x",
  "context_summary": {"files": 3, "commits": 0, "partial": false},
  "plan": ["doc-sync", "changelog"],
  "results": [
    {"skill": "doc-sync", "status": "failure", "duration_ms": 210,
     "detail": "exit 1: docs inconsistent",
     "rule": {"on_failure": "block"}, "outcome": "block",
     "reason": "rule outcomes.doc-sync.on_failure=block matched status 'failure'"}
  ],
  "final_outcome": "block",
  "block_downgraded": false,
  "duration_ms": 1234,
  "warnings": []
}
```

- Written for **every** run — empty plans, all-skipped, error-interrupted (best-effort)
- Per-skill entries carry the diagnostic chain: output detail → matched rule → applied
  outcome → reason (FR-004/SC-003)
- `final_outcome`: `block` \| `warn` \| `none` (strongest across skills; `skip`-ruled
  results never escalate)

## Outcome rules (routes config v1.1, additive)

```json
{"version": "1.1",
 "routes": {"pre-commit": ["doc-sync"]},
 "outcomes": {"doc-sync": {"on_failure": "block"}},
 "run_retention": 50}
```

| Rule | Applies to statuses | Effect |
|------|--------------------|--------|
| `on_failure: block` | failure, timeout, skipped | abort git op (pre-commit/pre-push); downgraded to warn on post-merge |
| `on_failure: warn` (= default, FR-009) | failure, timeout, skipped | visible `[router warning]`, proceed |
| `on_failure: skip` | failure, timeout, skipped | silent; recorded in run record only |

Success → outcome `none` always. Invalid rule values → default warn + note in record.
Rules re-read every run (SC-005).

## Exit-code protocol (002 addendum)

| Orchestration exit | Hook behavior (`_finish_hook` in scripts/lib.sh) |
|--------------------|--------------------------------------------------|
| `0` | proceed, exit 0 |
| `10` | **block**: `[hook blocked]` to stderr, hook exits 1 → git operation aborts |
| any other (incl. 143 timeout) | `[hook warning]`, exit 0 — never blocks |

Exit 10 is reserved: only produced by a matched block rule, never by crashes.

## History CLI (FR-003)

```sh
python3 src/run_records.py list [--limit 10]   # newest first: <id>  <event>  <final>  ok=N fail=N
python3 src/run_records.py show --last          # human-readable report of the latest run
python3 src/run_records.py show <id>
```

## DispatchResult v1.2 (additive over v1.1)

Adds `final_outcome`, `outcomes` (the per-skill evaluations), `run_record` (path \| null).
