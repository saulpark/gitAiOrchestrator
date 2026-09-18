#!/bin/sh
# lib.sh — shared helpers sourced by hook scripts. Not executed directly.
#
# Feature 002. Everything here exists to keep one promise: the orchestrator may
# fail in any way it likes without breaking someone's git workflow. The single
# exception is an explicitly configured block rule (feature 008), which arrives
# as the reserved exit code 10.

# Repo root. Hooks run with the working directory set to the top level, but
# resolving it explicitly keeps the scripts callable by hand and from subdirs.
_hook_root() {
    git rev-parse --show-toplevel
}

# Translate the orchestration exit code into hook behavior (008 protocol):
# 10 = a configured block rule matched — abort the git operation.
# Any other non-zero = orchestration problem — warn but never block.
#
# The asymmetry is deliberate: blocking must be something the operator opted
# into per skill, never a side effect of a crash, a timeout, or a bad config.
_finish_hook() {
    if [ "$1" -eq 10 ] 2>/dev/null; then
        printf '[hook blocked] git operation aborted by outcome rule\n' >&2
        exit 1   # any non-zero aborts the git operation; git ignores the value
    fi
    # 2>/dev/null: a non-numeric "$1" makes [ fail loudly — treat it as a warning.
    [ "$1" -ne 0 ] 2>/dev/null && \
        printf '[hook warning] orchestration failed (exit %d)\n' "$1" >&2
    exit 0
}

# Run "$@" with a 5-second timeout. Prefers timeout/gtimeout; falls back to a
# POSIX watchdog subshell that kills the command when the timer fires.
#
# The ceiling is on the hook, not on the skills: even if the Python pipeline
# hangs, the developer's commit is delayed by 5 seconds, not indefinitely.
# `timeout` is not in POSIX and macOS ships without it (gtimeout comes from
# coreutils), hence the three-way fallback.
_run_with_timeout() {
    if command -v timeout >/dev/null 2>&1; then
        timeout 5 "$@"
    elif command -v gtimeout >/dev/null 2>&1; then
        gtimeout 5 "$@"
    else
        # Watchdog: run the command in the background and poll it, killing it
        # when the ceiling is reached.
        #
        # It polls (rather than racing a single `sleep N`) and is detached from
        # the caller's stdio for two reasons: a plain `( sleep N; kill ) &`
        # inherits the caller's stdout and holds that pipe open for the WHOLE
        # timeout even after the command has finished — a piped `git push` then
        # appears to hang for N seconds — and it leaves a stray `sleep` behind.
        # This version exits within a second of the command finishing.
        "$@" & _PID=$!
        (
            _WAITED=0
            while kill -0 "$_PID" 2>/dev/null; do
                if [ "$_WAITED" -ge 5 ]; then
                    kill "$_PID" 2>/dev/null
                    break
                fi
                sleep 1
                _WAITED=$((_WAITED + 1))
            done
        ) >/dev/null 2>&1 & _WATCHDOG=$!
        wait "$_PID" 2>/dev/null; _EXIT=$?
        kill "$_WATCHDOG" 2>/dev/null
        wait "$_WATCHDOG" 2>/dev/null
        return "$_EXIT"
    fi
}
