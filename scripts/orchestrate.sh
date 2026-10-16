#!/bin/sh
# orchestrate.sh — hook entry point: parse context, route workflows (003 + 004)
# Reads HOOK_EVENT, HOOK_BRANCH, HOOK_FILES [, HOOK_COMMITS] from the environment.
#
# The whole runtime pipeline is this one pipe: the parser turns the hook
# environment into context JSON, the router decides what to run and runs it
# (delegating to 006/007) and records the run (008). The router's exit code is
# what reaches _finish_hook — notably 10 when a block rule matched.
ROOT="$(git rev-parse --show-toplevel)"

# Use the first interpreter that actually runs Python 3.10+. Probing, rather
# than trusting the name, matters on Windows: there `python3` is usually the
# Microsoft Store stub, which exists on PATH but only prints an install hint.
# Same candidates, same order as HOOK_PYTHON_CANDIDATES in install.py.
PYTHON=""
for _cand in python3 python "py -3"; do
    # $_cand unquoted on purpose: "py -3" is a command plus an argument.
    if $_cand -c 'import sys; sys.exit(sys.version_info < (3, 10))' >/dev/null 2>&1; then
        PYTHON=$_cand
        break
    fi
done
if [ -z "$PYTHON" ]; then
    # Logged, not printed: since 009 the terminal shows only blocks.
    mkdir -p "$ROOT/logs" 2>/dev/null
    printf '[%s] hook warning no Python 3.10+ found (tried: python3, python, py -3)\n' \
        "$(date -u +%Y-%m-%dT%H:%M:%SZ)" >> "$ROOT/logs/hooks.log" 2>/dev/null
    exit 127   # any non-10 code → _finish_hook logs it and lets git proceed
fi

# stdout (the DispatchResult JSON) is discarded here: hooks report through
# logs/hooks.log, the run records and _aioutput/. Redirect it to a file when
# debugging a route by hand.
$PYTHON "$ROOT/src/parse_context.py" | $PYTHON "$ROOT/src/route_workflows.py" \
    --config "$ROOT/config/routes.json" \
    --log "$ROOT/logs/hooks.log" \
    --root "$ROOT" \
    --skills-dir "$ROOT/skills" > /dev/null
