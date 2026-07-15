# Quickstart: Workflow Router

**Branch**: `004-workflow-router`

## Route a context manually (FR-009)

```sh
HOOK_EVENT=pre-commit HOOK_BRANCH=main HOOK_FILES="a.py" \
  python3 src/parse_context.py | python3 src/route_workflows.py
```

Expected (with the default empty routes): `{"schema_version": "1.0", "event": "pre-commit",
"results": [], "warnings": []}` and exit 0.

## See config-driven dispatch work end-to-end (US1)

```sh
mkdir -p skills/demo
printf '#!/bin/sh\necho "demo ran" >&2\nexit 0\n' > skills/demo/run
chmod +x skills/demo/run
python3 - <<'EOF'
import json, pathlib
p = pathlib.Path("config/routes.json")
cfg = json.loads(p.read_text())
cfg["routes"]["pre-commit"] = ["demo"]
p.write_text(json.dumps(cfg, indent=2) + "\n")
EOF
git commit --allow-empty -m "test: routing demo"   # pre-commit hook fires → demo runs
git reset --soft HEAD~1                             # undo test commit
git checkout config/routes.json && rm -rf skills/demo
```

## Simulate failure visibility (US3 / SC-003)

```sh
printf '{"event": "pre-commit", "branch": "b", "files": []}' \
  | python3 src/route_workflows.py --config /nonexistent.json
echo $?   # → 0, with a [router warning] about the missing config on stderr
```

## Run the tests

```sh
.venv/bin/pytest tests/test_route_workflows.py -v
.venv/bin/ruff check src/ tests/
```
