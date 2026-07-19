# Tasks: Run Observability and Outcome Enforcement

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Every run leaves a queryable record; skill results drive configurable block/warn/skip outcomes; block propagates through the hooks; everything else stays non-blocking.

**Architecture:** `run_records.py` (evaluation + store + history CLI) consumed by the router; routes config v1.1; `_finish_hook` in lib.sh; exit-code 10 protocol.

**Tech Stack:** Python 3.10+ stdlib, POSIX sh, pytest, ruff.

## Global Constraints

- Default outcome warn (FR-009); block only via explicit rule; only pre-commit/pre-push can block (post-merge downgrades)
- 100% of runs produce a record (SC-002); record write is best-effort and never affects the git op
- Exit 10 is the only blocking signal; 143/timeouts/crashes always warn + proceed
- Rules and retention re-read every run (SC-005)

---

## Task 1: Outcome evaluation (US3 core)

**Files:** Create `src/run_records.py`, `tests/test_run_records.py`

**Interfaces produced:** `BLOCK_EXIT_CODE = 10`; `OUTCOMES = ("block", "warn", "skip")`; `evaluate_outcomes(summary, outcome_rules, event) -> dict`

- [x] **Step 1: Failing tests** — success → `none`; failure w/o rule → warn (default, FR-009); block/warn/skip rules honored for failure, timeout, skipped statuses; invalid rule value → warn + note; final = strongest (block > warn > none); two blocks → both named in reasons; post-merge block → warn + `block_downgraded`; empty results → final `none`; reason strings name rule + status (SC-003)
- [x] **Step 2: Verify fail**
- [x] **Step 3: Implement**
- [x] **Step 4: Verify pass**
- [x] **Step 5: Commit** — `feat(008): outcome evaluation with safe-by-default warn`

## Task 2: Run record store + history CLI (US1/US2)

**Files:** Modify `src/run_records.py`; extend tests

**Interfaces produced:** `build_run_record`, `write_run_record(runs_dir, record, retention)`, `list_runs`, `load_run`; CLI `list [--limit N]` / `show <id>|--last`

- [x] **Step 1: Failing tests** — record carries FR-002 fields (event, timestamp, per-skill status+duration+rule+outcome+reason, final); empty-plan record written (SC-002); retention prunes oldest beyond N; ids lexically sortable; `list_runs` newest first; CLI `list` one-line summaries, `show --last` renders skills+outcomes+reasons, unknown id → exit 1; write failure (unwritable dir) → returns None, no raise
- [x] **Step 2: Verify fail**
- [x] **Step 3: Implement**
- [x] **Step 4: Verify pass + ruff**
- [x] **Step 5: Commit** — `feat(008): run record store and history CLI`

## Task 3: Router integration (routes v1.1, DispatchResult v1.2, exit 10)

**Files:** Modify `src/route_workflows.py`, `config/routes.json`; extend `tests/test_route_workflows.py`

- [x] **Step 1: Failing tests** — `load_config` accepts optional `outcomes` (tolerant: bad shapes → warning + ignored) and `run_retention`; CLI with failing block-ruled skill → exit **10** + `[hook blocked] skill '<name>'` on stderr + run record written; warn default → exit 0 + `[router warning]`; skip rule → exit 0, **no** message, still recorded; post-merge block-ruled failure → exit 0 warn + downgraded note; DispatchResult v1.2 fields (`final_outcome`, `outcomes`, `run_record`)
- [x] **Step 2: Verify fail**
- [x] **Step 3: Implement** (`--runs-dir` arg defaulting to `logs/runs`; version bump to 1.2)
- [x] **Step 4: Verify pass + ruff**
- [x] **Step 5: Commit** — `feat(008): router enforces outcomes, writes run records, exits 10 on block`

## Task 4: Hook propagation (`_finish_hook`)

**Files:** Modify `scripts/lib.sh`, `scripts/pre-commit.sh`, `scripts/pre-push.sh`, `scripts/post-merge.sh`

- [x] **Step 1: Implement** `_finish_hook` in lib.sh; replace the three-line tail of each hook with `_finish_hook $?`
- [x] **Step 2: Verify** — `sh -n` all; line counts ≤ 30; business-logic grep clean; shell checks: `_finish_hook 10` → exit 1 with `[hook blocked]`, `_finish_hook 1` → exit 0 with warning, `_finish_hook 0` → exit 0 silent
- [x] **Step 3: Commit** — `feat(008): hooks propagate block exit code, warn on everything else`

## Task 5: E2E + docs sync + finish

- [x] **Step 1: Live E2E** — block-ruled failing skill on pre-commit → real `git commit` **aborts** with `[hook blocked]`; flip rule to warn (config-only, SC-005) → commit proceeds with warning; skip → silent; `run_records.py show --last` renders the diagnosis; clean up
- [x] **Step 2: Contract addenda** — 002 exit-code table, 004 routes v1.1 pointer; sync CLAUDE.md; check off tasks.md
- [x] **Step 3: Full suite + ruff; commit, push, PR**
