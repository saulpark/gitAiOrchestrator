#!/bin/sh
# pre-commit — thin hook: capture context, delegate to orchestrate.sh
. "$(git rev-parse --show-toplevel)/scripts/lib.sh"

# skip merge commits — post-merge covers them
[ -f "$(git rev-parse --git-path MERGE_HEAD)" ] && exit 0

HOOK_EVENT="pre-commit"
HOOK_BRANCH=$(git rev-parse --abbrev-ref HEAD)
HOOK_FILES=$(git diff --cached --name-only --diff-filter=ACM)
export HOOK_EVENT HOOK_BRANCH HOOK_FILES

_run_with_timeout "$(_hook_root)/scripts/orchestrate.sh"
EXIT=$?
[ "$EXIT" -ne 0 ] && printf '[hook warning] orchestration failed (exit %d)\n' "$EXIT" >&2
exit 0
