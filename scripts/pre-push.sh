#!/bin/sh
# pre-push — thin hook: capture context, delegate to orchestrate.sh
. "$(git rev-parse --show-toplevel)/scripts/lib.sh"

ZERO="0000000000000000000000000000000000000000"
HOOK_EVENT="pre-push"
HOOK_BRANCH=$(git rev-parse --abbrev-ref HEAD)
HOOK_FILES=""
while read -r local_ref local_sha remote_ref remote_sha; do
    [ "$local_sha" = "$ZERO" ] && continue
    if [ "$remote_sha" = "$ZERO" ]; then
        FILES=$(git rev-list "$local_sha" --not --remotes | while read -r c; do
            git diff-tree -r --name-only --no-commit-id "$c"; done | sort -u)
    else
        FILES=$(git diff --name-only "$remote_sha" "$local_sha" 2>/dev/null)
    fi
    [ -n "$FILES" ] && HOOK_FILES="${HOOK_FILES}${FILES}
"
done
export HOOK_EVENT HOOK_BRANCH HOOK_FILES

_run_with_timeout "$(_hook_root)/scripts/orchestrate.sh"
EXIT=$?
[ "$EXIT" -ne 0 ] && printf '[hook warning] orchestration failed (exit %d)\n' "$EXIT" >&2
exit 0
