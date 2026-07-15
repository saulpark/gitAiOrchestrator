#!/bin/sh
# orchestrate.sh — hook entry point: parse context, route workflows (003 + 004)
# Reads HOOK_EVENT, HOOK_BRANCH, HOOK_FILES [, HOOK_COMMITS] from the environment.
ROOT="$(git rev-parse --show-toplevel)"
python3 "$ROOT/src/parse_context.py" | python3 "$ROOT/src/route_workflows.py" \
    --config "$ROOT/config/routes.json" \
    --log "$ROOT/logs/hooks.log" \
    --skills-dir "$ROOT/skills" > /dev/null
