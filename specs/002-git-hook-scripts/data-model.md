# Data Model: Git Hook Scripts

**Branch**: `002-git-hook-scripts` | **Date**: 2026-05-23

Hook scripts are shell scripts — there is no object model or persistent state. Data flows as environment variables at invocation time.

---

## Entity: HookEvent

The in-memory data captured at hook invocation and passed to the orchestration layer.

| Field | Shell Variable | Type | Description |
|-------|---------------|------|-------------|
| `event` | `HOOK_EVENT` | string | Git event type: `pre-commit`, `post-merge`, `pre-push` |
| `branch` | `HOOK_BRANCH` | string | Current branch name (`git rev-parse --abbrev-ref HEAD`); `HEAD` in detached state |
| `files` | `HOOK_FILES` | newline-delimited string | Changed file paths relevant to the event; empty string if no files |

**Validation rules**:
- `HOOK_EVENT` must be one of the three defined values
- `HOOK_BRANCH` is passed as-is; `HEAD` is valid (detached state)
- `HOOK_FILES` may be empty (e.g., no staged files on pre-commit)

---

## Entity: HookScript

A versioned executable shell script in `scripts/` that handles one git event.

| Field | Value |
|-------|-------|
| `path` | `scripts/<event-name>.sh` |
| `shebang` | `#!/bin/sh` |
| `max_lines` | 30 (SC-004 constraint) |
| `exit_code` | Always 0 |
| `delegates_to` | `scripts/orchestrate.sh` |

**Invariants**:
- Contains no documentation logic, no file writes, no conditional business rules
- Single delegation call to orchestrate.sh per invocation
- Emits `[hook warning]` to stderr on failure; never to stdout

---

## Entity: HookLauncher

The thin `#!/bin/sh` file in `.githooks/` that delegates to `scripts/`.

| Field | Value |
|-------|-------|
| `path` | `.githooks/<event-name>` |
| `content` | `exec "$(git rev-parse --show-toplevel)/scripts/<event-name>.sh"` |
| `max_lines` | 2 (shebang + exec) |

---

## Entity: OrchestrationStub

`scripts/orchestrate.sh` in this feature — reads env vars and logs them. Fully implemented in 003/004.

| Field | Value |
|-------|-------|
| `path` | `scripts/orchestrate.sh` |
| `reads` | `HOOK_EVENT`, `HOOK_BRANCH`, `HOOK_FILES` |
| `behavior` | Logs event to `logs/hooks.log`; exits 0 |

---

## Data Flow

```
git operation
    │
    ▼
.githooks/<event>          ← thin launcher (2 lines)
    │  exec
    ▼
scripts/<event>.sh         ← context capture + delegation (≤30 lines)
    │  captures: event type, branch, changed files
    │  sets: HOOK_EVENT, HOOK_BRANCH, HOOK_FILES
    │  calls with timeout:
    ▼
scripts/orchestrate.sh     ← stub (this feature) / full impl (003/004)
    │
    ▼
exit 0                     ← git operation proceeds unconditionally
```

---

## Log Format

`logs/hooks.log` (async mode only):

```
[2026-05-23T10:45:01Z] pre-commit branch=002-git-hook-scripts files=3
[2026-05-23T10:45:02Z] orchestrate exit=0
```
