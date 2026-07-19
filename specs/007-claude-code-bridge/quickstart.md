# Quickstart: Claude Code Bridge

**Branch**: `007-claude-code-bridge`

## Invoke the bridge directly (FR-008)

```sh
python3 - <<'EOF' | python3 src/claude_bridge.py
import json
print(json.dumps({
    "schema_version": "1.0",
    "context": {"schema_version": "1.0", "event": "pre-commit", "branch": "main",
                "files": ["src/parse_context.py"], "commits": [], "partial": False,
                "unavailable": [], "errors": []},
    "task": "Reply with the single word OK.",
    "options": {"max_turns": 1}
}))
EOF
```

Expected: one BridgeResult line — `status: "ok"` with output if `claude` is installed,
`status: "unavailable"` otherwise. Exit 0 either way.

## Unavailability path (SC-003)

```sh
printf '{"schema_version":"1.0","context":{"event":"pre-commit"},"task":"x"}' \
  | python3 - <<'EOF'
import json, subprocess, sys
cfg = {"version": "1.0", "claude_command": "claude-definitely-not-installed"}
open("/tmp/bridge-test.json", "w").write(json.dumps(cfg))
EOF
printf '{"schema_version":"1.0","context":{"event":"pre-commit"},"task":"x"}' \
  | python3 src/claude_bridge.py --config /tmp/bridge-test.json
# → {"status": "unavailable", …}, exit 0
```

## Toggle Claude Code hooks (US3/SC-004)

Edit `config/bridge.json` → `"hooks_enabled": true`. Next bridge call omits the
`disableAllHooks` override so the project's Claude Code hooks fire. Set back to `false`
to suppress them again. No reinstallation.

## A skill using the bridge (SC-001)

```sh
#!/bin/sh
# skills/<name>/run — the whole Claude integration is one pipe:
CTX=$(cat)
printf '{"schema_version":"1.0","context":%s,"task":"Summarize the change set in one line."}' "$CTX" \
  | python3 "$(git rev-parse --show-toplevel)/src/claude_bridge.py"
# …then map the BridgeResult to a skill-result@1.0 on stdout.
```

## Tests

```sh
.venv/bin/pytest tests/test_claude_bridge.py -v
.venv/bin/pytest tests/ -q && .venv/bin/ruff check src/ tests/
```
