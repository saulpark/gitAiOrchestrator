#!/bin/sh
# pre-push — thin hook: capture context, delegate to orchestrate.sh
#
# Feature 002/003. The only event that reports commits as well as files: git
# feeds this hook one line per ref being pushed on stdin, in the form
#   <local ref> <local sha> <remote ref> <remote sha>
# and the job here is to turn those ranges into the pushed commits and the
# union of the files they touch.
. "$(git rev-parse --show-toplevel)/scripts/lib.sh"

ZERO="0000000000000000000000000000000000000000"  # git's "this ref does not exist"
HOOK_EVENT="pre-push"
HOOK_BRANCH=$(git rev-parse --abbrev-ref HEAD)
HOOK_FILES=""
HOOK_COMMITS=""
while read -r local_ref local_sha remote_ref remote_sha; do
    [ "$local_sha" = "$ZERO" ] && continue   # branch deletion — nothing to inspect
    if [ "$remote_sha" = "$ZERO" ]; then
        # New branch on the remote: there is no "since" point, so take what
        # this branch has that no other remote-tracked branch already carries.
        REVS=$(git rev-list "$local_sha" --not --remotes)
    else
        # Normal update: exactly the commits this push adds.
        REVS=$(git rev-list "$remote_sha..$local_sha" 2>/dev/null)
    fi
    [ -z "$REVS" ] && continue   # already up to date
    # Files touched by any of those commits, de-duplicated across the range.
    FILES=$(printf '%s\n' "$REVS" | while read -r c; do
        git diff-tree -r --name-only --no-commit-id "$c"; done | sort -u)
    # Accumulate across refs — one push can update several. The trailing
    # newline in the assignment keeps entries on separate lines for the parser.
    HOOK_COMMITS="${HOOK_COMMITS}${REVS}
"
    [ -n "$FILES" ] && HOOK_FILES="${HOOK_FILES}${FILES}
"
done
export HOOK_EVENT HOOK_BRANCH HOOK_FILES HOOK_COMMITS

_run_with_timeout "$(_hook_root)/scripts/orchestrate.sh"
_finish_hook $?   # exit 10 → abort the push; anything else → warn and proceed
