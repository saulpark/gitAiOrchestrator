# Quickstart: Skill Executor

**Branch**: `006-skill-executor`

## Run a plan in isolation (FR-009)

```sh
HOOK_EVENT=pre-commit HOOK_BRANCH=main HOOK_FILES="a.py" \
  python3 src/parse_context.py | python3 src/execute_skills.py hello
```

Expected: one ExecutionSummary JSON line; exit 0 even if every skill fails.

## Empty plan (FR-008)

```sh
printf '{"event": "pre-commit"}' | python3 src/execute_skills.py
# → {"schema_version": "1.0", "event": "pre-commit", "overall": "empty", "duration_ms": 0, "results": []}
```

## See isolation + timeout live (US2)

Register three skills — `fails` (exit 1), `slow` (sleeps past its 1 s
`time_budget_seconds`), `works` (compliant) — route them on pre-commit, commit:

```sh
tail -1 logs/hooks.log
# route event=pre-commit failed=1 invoked=1 timeout=1 … overall=partial-failure
```

`works` still ran despite `fails` and `slow` before it (SC-002).

## Tests

```sh
.venv/bin/pytest tests/test_execute_skills.py -v
.venv/bin/pytest tests/ -q && .venv/bin/ruff check src/ tests/
```
