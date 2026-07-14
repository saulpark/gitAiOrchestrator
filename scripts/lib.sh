#!/bin/sh
# lib.sh — shared helpers sourced by hook scripts. Not executed directly.

_hook_root() {
    git rev-parse --show-toplevel
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
