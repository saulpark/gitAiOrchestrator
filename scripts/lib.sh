#!/bin/sh
# lib.sh — shared helpers sourced by hook scripts. Not executed directly.

_hook_root() {
    git rev-parse --show-toplevel
}

# Translate the orchestration exit code into hook behavior (008 protocol):
# 10 = a configured block rule matched — abort the git operation.
# Any other non-zero = orchestration problem — warn but never block.
_finish_hook() {
    if [ "$1" -eq 10 ] 2>/dev/null; then
        printf '[hook blocked] git operation aborted by outcome rule\n' >&2
        exit 1
    fi
    [ "$1" -ne 0 ] 2>/dev/null && \
        printf '[hook warning] orchestration failed (exit %d)\n' "$1" >&2
    exit 0
}

# Run "$@" with a 5-second timeout. Prefers timeout/gtimeout; falls back to a
# POSIX watchdog subshell that kills the command when the timer fires.
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
        return "$_EXIT"
    fi
}
