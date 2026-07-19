#!/bin/sh
# post-merge — thin hook: capture context, delegate to orchestrate.sh
. "$(git rev-parse --show-toplevel)/scripts/lib.sh"

HOOK_EVENT="post-merge"
HOOK_BRANCH=$(git rev-parse --abbrev-ref HEAD)
HOOK_FILES=$(git diff-tree -r --name-only --no-commit-id ORIG_HEAD HEAD 2>/dev/null)
export HOOK_EVENT HOOK_BRANCH HOOK_FILES

_run_with_timeout "$(_hook_root)/scripts/orchestrate.sh"
_finish_hook $?
