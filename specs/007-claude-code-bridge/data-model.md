# Data Model: Claude Code Bridge

**Branch**: `007-claude-code-bridge` | **Date**: 2026-07-19

## Entity: BridgeRequest / BridgeResult

See [contracts/bridge-interface.md](./contracts/bridge-interface.md).

## Entity: BridgeConfiguration (`config/bridge.json`)

| Field | Type | Default | Notes |
|-------|------|---------|-------|
| `version` | string | `"1.0"` | |
| `claude_command` | string | `"claude"` | resolved with `shutil.which` |
| `max_turns` | int | `4` | `--max-turns` |
| `timeout_seconds` | number | `120` | subprocess timeout |
| `hooks_enabled` | bool | `false` | false → `--settings '{"disableAllHooks": true}'` |
| `extra_args` | list[str] | `[]` | appended verbatim |

Tolerant load: missing/malformed file or wrong-typed field → default + stderr warning.

## Entity: BoundedInvocationContext

Derived from hook-context@1.0 only: `event`, `branch`, `files`, `commits`,
`partial`/`unavailable` notes. Rendered into the prompt; never a repo snapshot.

## Entity: Runner (injectable seam, FR-008)

```python
runner(argv: list[str], prompt_stdin: str | None, timeout: float)
    -> tuple[int, str, str]  # (returncode, stdout, stderr)
```

Default runner wraps `subprocess.run`. Tests inject fakes; CLI tests use fake `claude`
executables on PATH.

## Flow

```text
skill (run) ── BridgeRequest JSON ──→ claude_bridge.py
                                        │ load config/bridge.json (fresh)
                                        │ which(claude)? ── no ──→ status=unavailable
                                        │ build bounded prompt from request.context
                                        │ claude -p --output-format json --max-turns N
                                        │   [+ --settings '{"disableAllHooks": true}' if hooks off]
                                        │   [+ extra_args]  (cwd = repo root → project settings apply)
                                        ▼
                     BridgeResult JSON (ok/error/timeout/unavailable/bad-request)
```
