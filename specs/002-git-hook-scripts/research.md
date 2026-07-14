# Research: Git Hook Scripts

**Branch**: `002-git-hook-scripts` | **Date**: 2026-05-23

---

## Decision: Shell Dialect

**Decision**: `#!/bin/sh` (POSIX sh)
**Rationale**: CI environments vary — `/bin/bash` may be ancient on macOS (3.2, GPL-restricted) or absent in minimal containers. All required features (while loops, command substitution, exit codes, env vars) are POSIX-compliant. No bash-specific features (arrays, `[[`, `local`) are needed.
**Alternatives considered**:
- `#!/bin/bash` — rejected: CI portability risk; no needed features justify the dependency

---

## Decision: pre-commit File Context

**Decision**: `git diff --cached --name-only --diff-filter=ACM`
**Rationale**: `--cached` captures staged files (what will be committed). `--staged` is an alias but `--cached` has broader compatibility. `--diff-filter=ACM` limits to Added, Copied, Modified — excludes deleted files which have no content to document.
**Edge cases**:
- Initial commit: `--cached` works correctly; `ORIG_HEAD` does not exist but is not used here
- Merge commit in progress: detect with `[ -f .git/MERGE_HEAD ] && exit 0` to skip pre-commit during merge
**Alternatives considered**:
- `git diff --staged` — alias for `--cached`; works but less portable
- No `--diff-filter` — includes deleted files; produces noise for documentation triggers

---

## Decision: post-merge File Context

**Decision**: `git diff-tree -r --name-only --no-commit-id ORIG_HEAD HEAD`
**Rationale**: `git diff-tree` is a plumbing command — stable output, no color, no pager. `ORIG_HEAD` is set by git before a merge and is the correct pre-merge reference. `HEAD@{1}` uses the reflog which can be wrong if other operations ran between.
**Alternatives considered**:
- `git diff ORIG_HEAD HEAD --name-only` — porcelain, affected by color/pager settings in some environments
- `git diff HEAD@{1} HEAD --name-only` — reflog-based; incorrect if reflog has intermediate entries

---

## Decision: pre-push File Context

**Decision**: Parse stdin with a `while read` loop, derive changed **file paths** per ref
**Rationale**: The pre-push hook receives one line per ref on stdin: `<local_ref> <local_sha> <remote_ref> <remote_sha>`. Pure POSIX sh can parse this without external tools. Deletion pushes (local_sha = 40 zeros) are skipped. The contract requires `HOOK_FILES` to be file paths (same semantics as pre-commit/post-merge), so each ref line is resolved to changed files:

- Ref update (remote_sha exists): `git diff --name-only "$remote_sha" "$local_sha"`
- New ref (remote_sha = 40 zeros): `git rev-list "$local_sha" --not --remotes` piped through `git diff-tree` — files changed by commits not yet on any remote

```sh
ZERO="0000000000000000000000000000000000000000"
while read local_ref local_sha remote_ref remote_sha; do
    [ "$local_sha" = "$ZERO" ] && continue    # ref deletion — nothing to document
    if [ "$remote_sha" = "$ZERO" ]; then
        FILES=$(git rev-list "$local_sha" --not --remotes | while read c; do
            git diff-tree -r --name-only --no-commit-id "$c"; done | sort -u)
    else
        FILES=$(git diff --name-only "$remote_sha" "$local_sha")
    fi
    HOOK_FILES="${HOOK_FILES}${FILES}
"
done
```

> **Correction (2026-07-14)**: Originally `HOOK_FILES` was built from ref *names*, which
> contradicted the contract (newline-delimited file paths). Resolved in favour of the contract.

**Alternatives considered**:
- Ref names only — rejected: contradicts contract format; downstream router (004) needs file paths
- Reading from git log — more complex; diff against the pushed range is sufficient

---

## Decision: Branch Name Detection

**Decision**: `git rev-parse --abbrev-ref HEAD`
**Rationale**: Works in all git versions. `git branch --show-current` requires 2.22+ (released 2019) and is not universal in CI. Detached HEAD returns `HEAD` — hooks should handle this gracefully (pass as-is).
**Alternatives considered**:
- `git branch --show-current` — rejected: 2.22+ only
- `$GIT_BRANCH` env var — only set in some CI systems, not universal

---

## Decision: Timeout Implementation

**Decision**: Detect `timeout` → `gtimeout` → background+kill fallback
**Rationale**: macOS ships without GNU coreutils `timeout` by default; `gtimeout` is available via `brew install coreutils`. Linux has `timeout` natively. The fallback background+kill pattern is pure POSIX.

```sh
_run_with_timeout() {
    if command -v timeout >/dev/null 2>&1; then
        timeout 5 "$@"
    elif command -v gtimeout >/dev/null 2>&1; then
        gtimeout 5 "$@"
    else
        "$@" & _PID=$!
        ( sleep 5; kill "$_PID" 2>/dev/null ) & _WATCHDOG=$!
        wait "$_PID" 2>/dev/null; _EXIT=$?
        kill "$_WATCHDOG" 2>/dev/null
        wait "$_WATCHDOG" 2>/dev/null
        return $_EXIT
    fi
}
```

> **Correction (2026-07-14)**: The original fallback (`sleep 5 & wait $PID; kill $SLEEP_PID`)
> never killed the command — `wait $PID` blocks until the command finishes on its own, so the
> timeout was not enforced. The watchdog subshell above kills the command after 5s.

**Alternatives considered**:
- Require `timeout` — rejected: breaks on stock macOS without coreutils
- Always use background+kill — verbose; prefer native commands when available
- `sleep & wait` race without watchdog — rejected: does not actually enforce the timeout

---

## Decision: Async Fire-and-Forget Mode

**Decision**: `cmd </dev/null >>logs/hooks.log 2>&1 & disown $!`
**Rationale**: `disown` detaches from shell job table so process survives shell exit. `</dev/null` prevents background process from reading the terminal. Log file captures all output for debugging. Default mode for hooks where latency matters.
**Alternatives considered**:
- Synchronous with timeout — used when caller needs exit code; default is async for pre-commit/pre-push

---

## Decision: Error Handling Pattern

**Decision**: Capture exit code, warn to stderr with `[hook warning]` prefix, always `exit 0`
**Rationale**: pre-commit and pre-push abort git operations on non-zero exit. Warnings to stderr are visible in the terminal without polluting stdout. `[hook warning]` prefix makes messages identifiable. Never block git for orchestration failures (FR-004, constitution §6).

```sh
EXIT=$?
if [ $EXIT -ne 0 ]; then
    printf '[hook warning] orchestration failed (exit %d)\n' "$EXIT" >&2
fi
exit 0
```
**Alternatives considered**:
- Exit with orchestration code — rejected: violates FR-004 and constitution §6
- Silent failure — rejected: violates FR-005 and constitution §14

---

## Decision: Context Protocol

**Decision**: Environment variables (`HOOK_EVENT`, `HOOK_BRANCH`, `HOOK_FILES`)
**Rationale**: POSIX sh cannot generate JSON without external tools. Env vars are idiomatic, readable, and shell-native. `HOOK_FILES` uses newline-delimited paths (natural for shell output). Aligns with constitution §12 (structured I/O) without requiring jq.
**Alternatives considered**:
- CLI positional args — ambiguous for variable-length file lists
- JSON via stdin — requires `jq` or Python to generate; adds dependency
- Temp file with JSON — extra I/O; overkill for this data size

---

## Resolved: Hook Script Summary

| Hook | Event | Files command | Merge-commit guard |
|------|-------|--------------|-------------------|
| `pre-commit.sh` | staged → commit | `git diff --cached --name-only --diff-filter=ACM` | `[ -f .git/MERGE_HEAD ] && exit 0` |
| `post-merge.sh` | after merge | `git diff-tree -r --name-only --no-commit-id ORIG_HEAD HEAD` | N/A |
| `pre-push.sh` | before push | stdin loop → `git diff --name-only remote..local` (new refs: `rev-list --not --remotes`) | skip zero-sha deletions |
