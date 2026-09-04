#!/bin/sh
# post-merge — thin hook: capture context, delegate to orchestrate.sh
#
# Feature 002. Runs after a merge has already been recorded, so nothing here
# can block: outcome rules that say "block" are downgraded to warn (008).
. "$(git rev-parse --show-toplevel)/scripts/lib.sh"

HOOK_EVENT="post-merge"
HOOK_BRANCH=$(git rev-parse --abbrev-ref HEAD)
# ORIG_HEAD is the pre-merge tip, so ORIG_HEAD..HEAD is exactly what the merge
# brought in. 2>/dev/null: ORIG_HEAD may be absent (e.g. a first merge) — an
# empty file list is a valid context, not an error.
HOOK_FILES=$(git diff-tree -r --name-only --no-commit-id ORIG_HEAD HEAD 2>/dev/null)
export HOOK_EVENT HOOK_BRANCH HOOK_FILES

_run_with_timeout "$(_hook_root)/scripts/orchestrate.sh"
_finish_hook $?
