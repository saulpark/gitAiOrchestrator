# Quickstart: Git Hook Scripts

**Branch**: `002-git-hook-scripts` | **Date**: 2026-05-23

## Prerequisites

- Feature 001 installed (`python3 install.py` completed successfully)
- `git config core.hooksPath` = `.githooks`
- `logs/` directory exists

---

## What This Feature Adds

Replaces the placeholder stubs from 001 with real hook scripts that:
1. Capture event context (event type, branch, changed files)
2. Delegate to `scripts/orchestrate.sh` with a 5-second timeout
3. Never block the git operation on failure

---

## Verify Hooks Fire

### pre-commit

```sh
echo "# test" >> README.md
git add README.md
git commit -m "test: verify pre-commit hook fires"
```

Expected: commit completes normally. Check `logs/hooks.log`:
```
[2026-05-23T10:45:01Z] pre-commit branch=002-git-hook-scripts files=1
```

### post-merge

```sh
git fetch origin
git merge origin/main  # or any branch merge
```

Expected: merge completes. Check `logs/hooks.log`:
```
[2026-05-23T10:45:05Z] post-merge branch=002-git-hook-scripts files=N
```

### pre-push

```sh
git push origin 002-git-hook-scripts
```

Expected: push proceeds. Check `logs/hooks.log`:
```
[2026-05-23T10:45:10Z] pre-push branch=002-git-hook-scripts files=1
```

---

## Verify Non-Blocking Behaviour

Break the orchestration stub temporarily:

```sh
# Make orchestrate.sh exit non-zero
echo "exit 1" >> scripts/orchestrate.sh

# Try a commit
echo "test" >> README.md
git add README.md
git commit -m "test: non-blocking"
```

Expected:
- Terminal shows: `[hook warning] orchestration failed (exit 1)`
- Commit **succeeds** (exit 0 from hook)
- Revert: `git checkout scripts/orchestrate.sh`

---

## Check Thin Hook Constraint

```sh
wc -l scripts/pre-commit.sh scripts/post-merge.sh scripts/pre-push.sh
```

Each script must be ≤ 30 lines (SC-004).

---

## Logs

```sh
tail -f logs/hooks.log
```

Each hook invocation appends one line with timestamp, event, branch, and file count.
