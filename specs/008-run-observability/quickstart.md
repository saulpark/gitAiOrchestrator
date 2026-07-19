# Quickstart: Run Observability

**Branch**: `008-run-observability`

## See the last run (SC-001)

```sh
python3 src/run_records.py show --last
python3 src/run_records.py list --limit 10
```

## Make a skill block commits (US3)

`config/routes.json`:

```json
{"version": "1.1",
 "routes": {"pre-commit": ["doc-check"]},
 "outcomes": {"doc-check": {"on_failure": "block"}}}
```

A failing `doc-check` now aborts the commit:

```text
[hook blocked] skill 'doc-check': exit 1: docs inconsistent
[hook blocked] commit aborted by outcome rule
```

Change `"block"` → `"warn"` (or delete the rule — warn is the default) and the next
commit proceeds with a visible warning instead. No reinstall (SC-005).

## Silence a noisy skill

```json
"outcomes": {"flaky-metrics": {"on_failure": "skip"}}
```

Failures stop printing warnings; they remain in the run record and hooks.log.

## Diagnose an outcome (US2/SC-003)

`show --last` prints, per skill: status, duration, matched rule, applied outcome, and the
reason sentence (e.g. `rule outcomes.doc-check.on_failure=block matched status 'failure'`).
The raw record is the JSON file named in the report (`logs/runs/<id>.json`).

## Tests

```sh
.venv/bin/pytest tests/test_run_records.py -v
.venv/bin/pytest tests/ -q && .venv/bin/ruff check src/ tests/
```
