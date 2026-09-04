#!/bin/sh
# orchestrate.sh — hook entry point: parse context, route workflows (003 + 004)
# Reads HOOK_EVENT, HOOK_BRANCH, HOOK_FILES [, HOOK_COMMITS] from the environment.
#
# The whole runtime pipeline is this one pipe: the parser turns the hook
# environment into context JSON, the router decides what to run and runs it
# (delegating to 006/007) and records the run (008). The router's exit code is
# what reaches _finish_hook — notably 10 when a block rule matched.
ROOT="$(git rev-parse --show-toplevel)"
# stdout (the DispatchResult JSON) is discarded here: hooks report through
# logs/hooks.log, the run records, and stderr warnings. Redirect it to a file
# when debugging a route by hand.
python3 "$ROOT/src/parse_context.py" | python3 "$ROOT/src/route_workflows.py" \
    --config "$ROOT/config/routes.json" \
    --log "$ROOT/logs/hooks.log" \
    --skills-dir "$ROOT/skills" > /dev/null
