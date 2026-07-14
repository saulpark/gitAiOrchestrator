# Contract: Orchestration Interface

**Branch**: `002-git-hook-scripts` | **Date**: 2026-05-23

This contract defines how hook scripts invoke the orchestration entry point. It is the boundary between this feature (002) and the orchestration layer (003/004).

---

## Caller: Hook Scripts

`scripts/pre-commit.sh`, `scripts/post-merge.sh`, `scripts/pre-push.sh`

## Callee: Orchestration Entry Point

`scripts/orchestrate.sh`

---

## Invocation Protocol

Hook scripts invoke the orchestration entry point by setting environment variables and executing the script:

```sh
HOOK_EVENT="<event_type>" \
HOOK_BRANCH="<branch_name>" \
HOOK_FILES="<newline_delimited_files>" \
"$(git rev-parse --show-toplevel)/scripts/orchestrate.sh"
```

---

## Environment Variables

| Variable | Required | Format | Example |
|----------|----------|--------|---------|
| `HOOK_EVENT` | Yes | One of: `pre-commit`, `post-merge`, `pre-push` | `pre-commit` |
| `HOOK_BRANCH` | Yes | Branch name string; `HEAD` for detached state | `main` |
| `HOOK_FILES` | Yes | Newline-delimited file paths; empty string if none | `src/foo.py\nsrc/bar.py` |
| `HOOK_COMMITS` | pre-push only (v1.1, added by 003) | Newline-delimited full SHAs of pushed commits | `c9997cf…\nda44c5f…` |

> **v1.1 addendum (2026-07-14, feature 003)**: `pre-push.sh` additionally exports
> `HOOK_COMMITS` — see [003 context-schema contract](../../003-hook-context-parser/contracts/context-schema.md).

---

## Invocation Modes

### Synchronous (with timeout)

```sh
_run_with_timeout HOOK_EVENT="pre-commit" HOOK_BRANCH="$branch" HOOK_FILES="$files" \
    "$(git rev-parse --show-toplevel)/scripts/orchestrate.sh"
EXIT=$?
[ $EXIT -ne 0 ] && printf '[hook warning] orchestration failed (exit %d)\n' "$EXIT" >&2
exit 0
```

- Timeout: 5 seconds
- On timeout or error: emit `[hook warning]` to stderr, exit 0

### Asynchronous (fire-and-forget)

```sh
HOOK_EVENT="pre-commit" HOOK_BRANCH="$branch" HOOK_FILES="$files" \
    "$(git rev-parse --show-toplevel)/scripts/orchestrate.sh" \
    </dev/null >>"$(git rev-parse --show-toplevel)/logs/hooks.log" 2>&1 &
disown $!
```

- No timeout constraint
- Output redirected to `logs/hooks.log`
- Process detached from shell job table

---

## Exit Code Contract

| Exit Code | Meaning for hook caller |
|-----------|------------------------|
| `0` | Orchestration succeeded |
| non-zero | Orchestration failed — hook emits warning, still exits 0 |

**Hook scripts MUST always exit 0 regardless of orchestration exit code.**

---

## Orchestration Stub Behaviour (this feature)

Until 003/004 implement the full orchestration layer, `scripts/orchestrate.sh` logs the event and exits 0:

```sh
#!/bin/sh
# orchestrate.sh — stub (implemented in 003/004)
TIMESTAMP=$(date -u +"%Y-%m-%dT%H:%M:%SZ" 2>/dev/null || date -u)
LOG="$(git rev-parse --show-toplevel)/logs/hooks.log"
mkdir -p "$(dirname "$LOG")"
printf '[%s] %s branch=%s files=%d\n' \
    "$TIMESTAMP" "$HOOK_EVENT" "$HOOK_BRANCH" \
    "$(printf '%s' "$HOOK_FILES" | grep -c .)" >> "$LOG" 2>/dev/null || true
exit 0
```

---

## Non-Goals

- This contract does not define what `orchestrate.sh` does with the context (that is 003/004)
- This contract does not cover remote hooks or server-side events
- This contract does not define retry behaviour (out of scope for hooks)
