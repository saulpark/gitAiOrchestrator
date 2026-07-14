# Tasks: Git Hook Scripts

**Input**: Design documents from `/specs/002-git-hook-scripts/`
**Prerequisites**: plan.md ✓, spec.md ✓, research.md ✓, data-model.md ✓, contracts/orchestration-interface.md ✓

**Organization**: Grouped by user story for independent implementation and testing.
**Tests**: Not requested in spec — no test tasks included.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: US1/US2/US3 maps to user stories from spec.md
- Exact file paths in all descriptions

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Scaffold new files, remove 001 stubs superseded by this feature.

- [x] T001 Remove `.githooks/post-commit` and `scripts/post-commit.sh` (001 stubs superseded by pre-commit per spec)
- [x] T001b Update `install.py` `hooks_to_install` list: replace `post-commit` with `pre-commit` so the installer no longer recreates the removed stub (FR-008)
- [x] T002 [P] Create `.githooks/pre-commit` thin launcher with content `#!/bin/sh\nexec "$(git rev-parse --show-toplevel)/scripts/pre-commit.sh"` and `chmod +x`
- [x] T003 [P] Create `scripts/orchestrate.sh` stub per `contracts/orchestration-interface.md`: read `HOOK_EVENT`, `HOOK_BRANCH`, `HOOK_FILES`; log one line to `logs/hooks.log` with timestamp, event, branch, file count; `exit 0`
- [x] T004 Create `scripts/lib.sh` with two helpers: `_hook_root()` returning `$(git rev-parse --show-toplevel)` and `_run_with_timeout()` detecting `timeout` → `gtimeout` → watchdog fallback (`(sleep 5; kill $PID) &` — see research.md correction; the old `sleep & wait` pattern did not enforce the timeout); `chmod +x scripts/lib.sh`

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Verify shared infrastructure works before any hook script is implemented.

**⚠️ CRITICAL**: No user story work can begin until this phase is complete.

- [x] T005 Verify `scripts/lib.sh` `_run_with_timeout()` works cross-platform: run `_run_with_timeout sleep 1 && echo ok` — confirm it exits 0; run `_run_with_timeout sleep 10` — confirm it exits within 6s
- [x] T006 Verify `.githooks/pre-commit` launcher is executable and resolves correct path: run `bash -n .githooks/pre-commit` (syntax check) and `test -x .githooks/pre-commit && echo ok`

**Checkpoint**: Shared infrastructure ready — hook implementation can begin.

---

## Phase 3: User Story 1 — Automatic Event Delegation (Priority: P1) 🎯 MVP

**Goal**: All three hooks fire on their respective git operations, capture event context, and delegate to `scripts/orchestrate.sh`. Developer's git workflow is unaffected.

**Independent Test**: Make a commit. Verify `logs/hooks.log` contains a `pre-commit` entry with correct branch name. Verify `scripts/orchestrate.sh` received `HOOK_EVENT=pre-commit`, `HOOK_BRANCH=<branch>`, `HOOK_FILES=<staged files>`.

- [x] T007 [P] [US1] Implement `scripts/pre-commit.sh`: source `lib.sh`; add merge-commit guard (`[ -f .git/MERGE_HEAD ] && exit 0`); capture `HOOK_BRANCH=$(git rev-parse --abbrev-ref HEAD)`; capture `HOOK_FILES=$(git diff --cached --name-only --diff-filter=ACM)`; export `HOOK_EVENT=pre-commit`; call `_run_with_timeout "$(_hook_root)/scripts/orchestrate.sh"`; capture exit; `[ "$EXIT" -ne 0 ]` (POSIX test — no `[[ ]]`) → print `[hook warning] orchestration failed (exit $EXIT)` to stderr; `exit 0`
- [x] T008 [P] [US1] Implement `scripts/post-merge.sh`: source `lib.sh`; capture `HOOK_BRANCH`; capture `HOOK_FILES=$(git diff-tree -r --name-only --no-commit-id ORIG_HEAD HEAD)`; export `HOOK_EVENT=post-merge`; call `_run_with_timeout`; capture exit + warn; `exit 0`
- [x] T009 [P] [US1] Implement `scripts/pre-push.sh`: source `lib.sh`; capture `HOOK_BRANCH`; read stdin with `while read local_ref local_sha remote_ref remote_sha` loop, skip zero-sha deletions, build `HOOK_FILES` as changed file paths per contract (`git diff --name-only remote_sha local_sha`; new refs: `git rev-list local_sha --not --remotes` → `git diff-tree`); export `HOOK_EVENT=pre-push`; call `_run_with_timeout`; capture exit + warn; `exit 0`
- [x] T010 [US1] Make all three scripts executable: `chmod +x scripts/pre-commit.sh scripts/post-merge.sh scripts/pre-push.sh`
- [x] T011 [US1] Verify delegation: stage a file and run `git commit -m "test"` → confirm `logs/hooks.log` has a new `pre-commit` line with correct branch and file count ≥ 1

**Checkpoint**: User Story 1 fully functional — all three hooks fire and delegate.

---

## Phase 4: User Story 2 — Non-Blocking on Orchestration Failure (Priority: P2)

**Goal**: When `scripts/orchestrate.sh` fails or times out, the git operation completes and the developer sees a `[hook warning]` — never blocked.

**Independent Test**: Append `exit 1` to `scripts/orchestrate.sh`. Make a commit. Verify: (1) commit succeeds, (2) terminal shows `[hook warning] orchestration failed (exit 1)`. Revert orchestrate.sh.

- [x] T012 [US2] Verify failure path: append `exit 1` to `scripts/orchestrate.sh`; run `git commit -m "test: failure path"`; confirm commit exits 0 and `[hook warning]` appears on stderr; revert `scripts/orchestrate.sh`
- [x] T013 [US2] Verify timeout path: replace orchestrate.sh body with `sleep 10`; run `git commit -m "test: timeout"`; confirm commit completes within 7s total and `[hook warning]` appears; revert `scripts/orchestrate.sh`
- [x] T014 [US2] Verify CI/non-interactive mode: run `GIT_TERMINAL_PROMPT=0 git -c core.pager=cat commit -m "test: ci mode"` and confirm hook fires without hanging or prompting

**Checkpoint**: User Stories 1 and 2 verified — delegation works and failures never block git.

---

## Phase 5: User Story 3 — Hooks Contain No Business Logic (Priority: P3)

**Goal**: Each hook script is verifiably thin — context capture + single delegation call + error warning only. No business logic anywhere in hook files.

**Independent Test**: Run `wc -l scripts/pre-commit.sh scripts/post-merge.sh scripts/pre-push.sh` — each must be ≤ 30 lines. Grep confirms no doc-related keywords in hook files.

- [x] T015 [US3] Verify line count constraint (SC-004): run `wc -l scripts/pre-commit.sh scripts/post-merge.sh scripts/pre-push.sh` — each must report ≤ 30 lines; fail if any exceed
- [x] T016 [US3] Verify no business logic: run `grep -n "document\|generate\|update\|write\|sed\|awk\|python\|node" scripts/pre-commit.sh scripts/post-merge.sh scripts/pre-push.sh` — expect no matches

**Checkpoint**: All three user stories verified and functional.

---

## Phase 6: Polish & Cross-Cutting Concerns

**Purpose**: Final hardening and end-to-end validation.

- [x] T017 Add `logs/.gitkeep` (empty file) so the `logs/` directory is tracked in git even though `logs/` entries are gitignored — ensures fresh clones have the directory available without running the installer
- [x] T018 Run `quickstart.md` end-to-end: verify pre-commit, post-merge, and pre-push scenarios produce expected `logs/hooks.log` entries; verify non-blocking behaviour scenario from quickstart

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies — start immediately; T002, T003 can run in parallel after T001
- **Foundational (Phase 2)**: Depends on T004 (lib.sh must exist before verification)
- **US1 (Phase 3)**: Depends on Phase 2 — T007, T008, T009 can all run in parallel
- **US2 (Phase 4)**: Depends on Phase 3 (hooks must be implemented before failure testing)
- **US3 (Phase 5)**: Depends on Phase 3 (scripts must exist to measure)
- **Polish (Phase 6)**: Depends on all story phases

### User Story Dependencies

- **US1 (P1)**: Start after Phase 2 — no dependency on US2/US3
- **US2 (P2)**: Depends on US1 (hook scripts must exist) — verification only, no new code
- **US3 (P3)**: Depends on US1 (scripts must exist to measure) — verification only

### Parallel Opportunities

- T002, T003: both Phase 1 setup, different files — run simultaneously after T001
- T007, T008, T009: three different scripts in Phase 3 — run simultaneously

---

## Parallel Example: User Story 1 Hook Scripts

```bash
# All three hook scripts can be written simultaneously:
Task: "Implement scripts/pre-commit.sh"   # T007
Task: "Implement scripts/post-merge.sh"   # T008
Task: "Implement scripts/pre-push.sh"     # T009
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Complete Phase 1: Setup (T001–T004)
2. Complete Phase 2: Foundational (T005–T006)
3. Complete Phase 3: User Story 1 (T007–T011)
4. **STOP and VALIDATE**: Make a commit → check `logs/hooks.log`
5. Ship MVP if ready

### Incremental Delivery

1. Phase 1 + 2 → infrastructure in place
2. Phase 3 (US1) → hooks fire end-to-end → **MVP**
3. Phase 4 (US2) → failure handling verified → production-ready
4. Phase 5 (US3) → thin constraint confirmed → maintainability guaranteed
5. Phase 6 → polish + end-to-end sign-off

---

## Notes

- T001 is destructive (removes 001 stubs) — do it first before any other setup
- T007–T009 all source `scripts/lib.sh` — must complete T004 before these
- US2 and US3 tasks are verification-only — no new code files
- All hook scripts use `#!/bin/sh` (POSIX) — no bash features per research.md
- `HOOK_FILES` is newline-delimited per `contracts/orchestration-interface.md`
