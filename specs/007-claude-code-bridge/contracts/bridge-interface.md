# Contract: Bridge Interface

**Branch**: `007-claude-code-bridge` | **Date**: 2026-07-19
**Schema versions**: bridge-request `1.0`, bridge-result `1.0`, bridge config `1.0`

## CLI (what a skill calls)

```sh
python3 "$(git rev-parse --show-toplevel)/src/claude_bridge.py" < request.json
```

- stdin: BridgeRequest JSON
- stdout: BridgeResult JSON (single line)
- exit code: **always 0** — the skill inspects `status` and decides its own outcome
- cwd: repository root (skills already run there)

## BridgeRequest (`bridge-request@1.0`)

```json
{
  "schema_version": "1.0",
  "context": { "…the hook context exactly as received on the skill's stdin…": "…" },
  "task": "Update the module docs for the changed files.",
  "options": {"max_turns": 2}
}
```

| Field | Required | Notes |
|-------|----------|-------|
| `context` | yes | hook-context@1.0 object (003); passed through, bounded prompt derived from it |
| `task` | yes | non-empty instruction text from the skill |
| `options.max_turns` | no | overrides config `max_turns` for this call |
| `options.timeout_seconds` | no | overrides config `timeout_seconds` for this call |

## BridgeResult (`bridge-result@1.0`)

```json
{
  "schema_version": "1.0",
  "status": "ok",
  "output": {"…claude --output-format json payload…": "…"},
  "output_text": "the result text extracted for convenience",
  "error": "",
  "duration_ms": 812
}
```

| `status` | Meaning |
|----------|---------|
| `ok` | claude exited 0; `output` = parsed JSON payload (or `null` with raw text in `output_text`) |
| `error` | claude exited non-zero or emitted an error payload; `error` holds the description |
| `timeout` | invocation exceeded the effective timeout; child killed |
| `unavailable` | `claude` CLI not found on PATH — skill decides: fail, skip, or degrade |
| `bad-request` | request missing `context`/`task` — skill bug, described in `error` |

## Bridge configuration (`config/bridge.json`)

```json
{
  "version": "1.0",
  "claude_command": "claude",
  "max_turns": 4,
  "timeout_seconds": 120,
  "hooks_enabled": false,
  "extra_args": []
}
```

- Re-read on every invocation; missing/malformed → defaults + warning in result `error`? No —
  warnings surface on stderr; defaults apply (mirrors 004 config tolerance).
- `hooks_enabled: false` → bridge appends `--settings '{"disableAllHooks": true}'`
  (Claude Code's own hooks stay off for automated calls). `true` → project hook settings
  apply untouched (US3).
- `extra_args`: escape hatch appended verbatim to the claude argv (e.g. model pinning).

## Bounded prompt (FR-002/SC-005)

The prompt the bridge builds contains exactly: event, branch, changed files, commits,
partiality notes, the skill's task, and the constraint sentence
*"Only examine the files listed above. Do not scan or enumerate the rest of the
repository."* Nothing else is injected; the project's CLAUDE.md/settings are applied by
Claude Code itself via cwd (FR-004).

## Non-Goals

- Response caching (spec: fresh result per invocation)
- Parallel invocation orchestration (006 is sequential)
- Defining which skills call the bridge (that's routing/skill authorship)
