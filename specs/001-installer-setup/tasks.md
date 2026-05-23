# Tasks: Automated Install Flow

**Input**: Design documents from `/specs/001-installer-setup/`
**Prerequisites**: plan.md ✓, spec.md ✓, research.md ✓, data-model.md ✓, contracts/cli.md ✓

**Organization**: Grouped by user story for independent implementation and testing.
**Tests**: Not requested in spec — no test tasks included.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: US1/US2/US3 maps to user stories from spec.md
- Exact file paths in all descriptions

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Skeleton files and output infrastructure needed by all stories.

- [x] T001 Create `install.py` with Python 3.10 version guard (`sys.version_info < (3, 10)`) and output helpers `_ok()`, `_skip()`, `_warn()`, `_error()` that print `[OK]`/`[SKIP]`/`[WARN]`/`[ERROR]` prefixed lines per `contracts/cli.md`
- [x] T002 Create `.gitignore` at repo root with `logs/` entry (create file if absent, append entry if present but missing it)

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Core data model and prerequisite-checking engine. Must complete before any user story.

**⚠️ CRITICAL**: No user story work can begin until this phase is complete.

- [x] T003 Define `Prerequisite` dataclass in `install.py` with fields: `name: str`, `command: str`, `min_version: tuple[int, ...] | None`, `version_flag: str`, `install_url: str` per `data-model.md`
- [x] T004 [P] Define `CheckResult` dataclass in `install.py` with fields: `prerequisite: Prerequisite`, `status: Literal["ok", "missing", "outdated"]`, `found_version: tuple[int, ...] | None`, `message: str` per `data-model.md`
- [x] T005 [P] Define `StepResult` and `InstallResult` dataclasses in `install.py` with fields per `data-model.md` (`action`, `status: Literal["done","skipped","warned","failed"]`, `detail`, `outcome`, `steps`, `errors`)
- [x] T006 Implement `check_tool(prereq: Prerequisite) -> CheckResult` in `install.py` using `shutil.which()` for PATH check and `subprocess.run([cmd, flag], capture_output=True, text=True)` for version; return `CheckResult` with appropriate status
- [x] T007 Implement `run_checks(prerequisites: list[Prerequisite]) -> list[CheckResult]` in `install.py` that calls `check_tool()` for ALL prerequisites before returning — never short-circuit on first failure

**Checkpoint**: Core engine ready — user story implementation can begin.

---

## Phase 3: User Story 1 — First-Time Setup (Priority: P1) 🎯 MVP

**Goal**: Developer with all prerequisites runs `python install.py` from a fresh clone and the system is fully configured with no additional steps.

**Independent Test**: Run `python install.py` in a clean repo clone with git ≥ 2.28, uv, and claude in PATH. Verify exit 0, all steps show `[OK]`, `.githooks/` exists with executable hooks, `git config core.hooksPath` = `.githooks`, `scripts/` exists, `logs/` exists, `.gitignore` contains `logs/`.

- [x] T008 [P] [US1] Write `.githooks/post-commit` thin launcher script (content: `#!/bin/sh\nexec "$(git rev-parse --show-toplevel)/scripts/post-commit.sh"`) per `research.md` hook architecture decision
- [x] T009 [P] [US1] Write `.githooks/pre-push` thin launcher script delegating to `scripts/pre-push.sh`
- [x] T010 [P] [US1] Write `.githooks/post-merge` thin launcher script delegating to `scripts/post-merge.sh`
- [x] T011 [P] [US1] Write stub `scripts/post-commit.sh` (executable, prints placeholder message, exits 0)
- [x] T012 [P] [US1] Write stub `scripts/pre-push.sh` (executable, exits 0)
- [x] T013 [P] [US1] Write stub `scripts/post-merge.sh` (executable, exits 0)
- [x] T014 [US1] Implement `create_directories(config: InstallConfig) -> list[StepResult]` in `install.py` using `Path(d).mkdir(parents=True, exist_ok=True)` for each dir in `config.dirs_to_create`; log `[OK]` for each
- [x] T015 [US1] Implement `install_hooks(config: InstallConfig) -> list[StepResult]` in `install.py` that writes hook launcher files if absent and runs `os.chmod(path, 0o755)` on each; log `[OK]` per hook
- [x] T016 [US1] Implement `configure_hooks_path(target: str) -> StepResult` in `install.py` using `subprocess.run(["git", "config", "--local", "core.hooksPath"])` to read current value; set unconditionally if unset; log `[OK]`
- [x] T017 [US1] Implement `update_gitignore(entry: str) -> StepResult` in `install.py` that reads `.gitignore`, appends `entry` if absent; log `[OK]`
- [x] T018 [US1] Wire `main()` in `install.py`: call `run_checks()` → exit 1 with errors if any fail → call `create_directories()`, `install_hooks()`, `configure_hooks_path()`, `update_gitignore()` → print "Installation complete." and exit 0

**Checkpoint**: User Story 1 fully functional — `python install.py` works end-to-end on a clean machine.

---

## Phase 4: User Story 2 — Prerequisite Failure Feedback (Priority: P2)

**Goal**: When prerequisites are missing or outdated, the installer reports ALL problems with actionable messages and exits before making any changes.

**Independent Test**: Remove `uv` from PATH (e.g., `PATH=/usr/bin:/bin python install.py`). Verify exit 1, `[ERROR]` line naming `uv` with install URL, no directories created, no git config changed.

- [x] T019 [P] [US2] Define prerequisites list in `install.py`: git with min_version `(2, 28)` and `install_url = "https://git-scm.com/downloads"`, uv with no version floor and install URL, claude with no version floor and install URL per `research.md` resolved prerequisites table
- [x] T020 [US2] Implement version-parsing callables in `install.py` for git (parse `"git version X.Y.Z"` → `(X, Y, Z)` tuple) and generic `--version` output; attach to Prerequisite instances
- [x] T021 [US2] Implement actionable `[ERROR]` output in `run_checks()`: for each failed `CheckResult`, print `[ERROR] {name}: {reason}\n        Install: {install_url}` per `contracts/cli.md` failure example
- [x] T022 [US2] Add not-in-git-repo guard at start of `main()` in `install.py`: run `git rev-parse --show-toplevel`; if non-zero exit, print `[ERROR] Not inside a git repository. Run from repo root.` and exit 1

**Checkpoint**: User Stories 1 and 2 both work — success path and failure path independently verified.

---

## Phase 5: User Story 3 — Idempotent Re-Run (Priority: P3)

**Goal**: Running `python install.py` on an already-configured environment makes no changes and exits 0.

**Independent Test**: Run `python install.py` twice in sequence. Second run must show only `[SKIP]` lines and "Already configured. Nothing to do." with exit 0 and no file modifications.

- [x] T023 [US3] Add skip detection to `create_directories()` in `install.py`: if `Path(d).exists()`, log `[SKIP]` and return `StepResult(status="skipped")` instead of creating
- [x] T024 [US3] Add skip detection to `install_hooks()` in `install.py`: if hook file exists and is already executable, log `[SKIP]`; if file exists but not executable, chmod and log `[OK]`
- [x] T025 [US3] Add full idempotency to `configure_hooks_path()` in `install.py`: if current value equals target, log `[SKIP]`; if current value is different non-empty string, log `[WARN]` + prompt stdin `[y/N]`; on `N`/empty, log abort and exit 1 per `contracts/cli.md` conflict example
- [x] T026 [US3] Add skip detection to `update_gitignore()` in `install.py`: read `.gitignore`, if `logs/` entry already present log `[SKIP]` and return skipped StepResult
- [x] T027 [US3] Add "already configured" summary path in `main()` in `install.py`: if all StepResults have `status="skipped"`, print "Already configured. Nothing to do." instead of "Installation complete."

**Checkpoint**: All three user stories independently verified and functional.

---

## Phase 6: Polish & Cross-Cutting Concerns

**Purpose**: Edge cases, end-to-end validation.

- [x] T028 [P] Validate edge case in `install.py`: run from a directory without a `.git` repo (T022 guard fires, exits 1, no changes)
- [x] T029 [P] Validate edge case in `install.py`: existing `core.hooksPath` set to `custom-hooks` → `[WARN]` prompt fires → answer `N` → exit 1, no change to git config
- [x] T030 Run quickstart.md end-to-end validation: follow every step, confirm all `[OK]` lines appear, make test commit and verify `post-commit` hook fires

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies — start immediately
- **Foundational (Phase 2)**: Depends on Phase 1 (needs output helpers from T001)
- **User Story 1 (Phase 3)**: Depends on Phase 2 — needs data model and `run_checks()`
- **User Story 2 (Phase 4)**: Depends on Phase 2 + Phase 3 (`main()` wired in T018)
- **User Story 3 (Phase 5)**: Depends on Phase 3 (`main()` wired) + Phase 4 (all checks present)
- **Polish (Phase 6)**: Depends on all story phases complete

### User Story Dependencies

- **US1 (P1)**: Start after Phase 2 — no dependency on US2/US3
- **US2 (P2)**: Depends on US1 `main()` wire-up (T018) — extends error handling path
- **US3 (P3)**: Depends on US1 steps (T014–T017) — adds skip detection to each

### Parallel Opportunities

- T008–T013 (hook stubs): all six can run simultaneously
- T003, T004, T005: T004 and T005 can run in parallel after T003
- T019, T022: can run in parallel within Phase 4
- T028, T029: can run in parallel within Phase 6

---

## Parallel Example: User Story 1 Hook Stubs

```bash
# All six hook stub files can be written simultaneously:
Task: "Write .githooks/post-commit launcher"       # T008
Task: "Write .githooks/pre-push launcher"          # T009
Task: "Write .githooks/post-merge launcher"        # T010
Task: "Write scripts/post-commit.sh stub"          # T011
Task: "Write scripts/pre-push.sh stub"             # T012
Task: "Write scripts/post-merge.sh stub"           # T013
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Complete Phase 1: Setup (T001–T002)
2. Complete Phase 2: Foundational (T003–T007)
3. Complete Phase 3: User Story 1 (T008–T018)
4. **STOP and VALIDATE**: Run `python install.py` on clean machine — all `[OK]`, hooks fire on commit
5. Ship MVP if ready

### Incremental Delivery

1. Phase 1 + 2 → installer skeleton with working check engine
2. Phase 3 (US1) → full happy path works end-to-end → **MVP**
3. Phase 4 (US2) → failure messages polished → better DX
4. Phase 5 (US3) → idempotency complete → production-ready
5. Phase 6 → edge cases hardened

---

## Notes

- All tasks target `install.py` (single file) except T002 (`.gitignore`) and T008–T013 (hook/script stubs)
- No external packages — stdlib only throughout
- [P] tasks operate on different files or non-overlapping functions
- Commit after each phase checkpoint at minimum
