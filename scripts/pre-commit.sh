#!/bin/sh
# pre-commit — thin hook: capture context, delegate to orchestrate.sh
#
# Feature 002. Hook scripts do exactly one thing: describe what changed, in
# environment variables. No business logic lives here — that keeps the shell
# layer trivial to read and everything testable in Python.
. "$(git rev-parse --show-toplevel)/scripts/lib.sh"

# skip merge commits — post-merge covers them
# (a merge commit would otherwise be seen twice, once per event)
[ -f "$(git rev-parse --git-path MERGE_HEAD)" ] && exit 0

HOOK_EVENT="pre-commit"
HOOK_BRANCH=$(git rev-parse --abbrev-ref HEAD)
# The staged change set only: --cached is what is about to be committed, and
# ACM (added/copied/modified) excludes deletions, which have no content to read.
HOOK_FILES=$(git diff --cached --name-only --diff-filter=ACM)
export HOOK_EVENT HOOK_BRANCH HOOK_FILES

_run_with_timeout "$(_hook_root)/scripts/orchestrate.sh"
_finish_hook $?   # exit 10 → abort the commit; anything else → warn and proceed
