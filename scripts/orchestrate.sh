#!/bin/sh
# orchestrate.sh — stub entry point (fully implemented in 003/004)
# Contract: specs/002-git-hook-scripts/contracts/orchestration-interface.md
# Reads HOOK_EVENT, HOOK_BRANCH, HOOK_FILES from the environment.
TIMESTAMP=$(date -u +"%Y-%m-%dT%H:%M:%SZ" 2>/dev/null || date -u)
LOG="$(git rev-parse --show-toplevel)/logs/hooks.log"
mkdir -p "$(dirname "$LOG")"
printf '[%s] %s branch=%s files=%d\n' \
    "$TIMESTAMP" "$HOOK_EVENT" "$HOOK_BRANCH" \
    "$(printf '%s' "$HOOK_FILES" | grep -c .)" >> "$LOG" 2>/dev/null || true
exit 0
