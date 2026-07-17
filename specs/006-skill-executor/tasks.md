# Tasks: Skill Executor

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ordered, isolated, time-bounded skill execution with a structured summary; router delegates its run loop to the executor.

**Architecture:** `execute_plan(plan, context, skills_dir, default_budget)` engine in `src/execute_skills.py` with CLI; `route_workflows.select_plan()` + DispatchResult v1.1; contract v1.1 optional `time_budget_seconds`.

**Tech Stack:** Python 3.10+ stdlib, pytest, ruff.

## Global Constraints

- Executor exits 0 always (FR-007); summary for every plan incl. empty (SC-003, FR-008)
- Plan order preserved in results (SC-001); failures/timeouts isolated (SC-002/FR-003)
- Context passed unmodified to every skill (FR-002); sequential only

---

## Task 1: Executor engine (US1+US2)

**Files:** Create `src/execute_skills.py`, `tests/test_execute_skills.py`

**Interfaces produced:** `execute_plan(plan: list[str], context: dict, skills_dir: str, default_budget: float = 30.0) -> dict`; `SUMMARY_SCHEMA_VERSION = "1.0"`; `STATUSES = ("success", "failure", "timeout", "skipped")`

- [x] **Step 1: Failing tests** — order preserved; context JSON delivered unmodified to each skill's stdin; exit-1 skill → `failure` and later skills still run; sleep-past-budget skill (manifest `time_budget_seconds: 1`) → `timeout`, later skills run; unregistered id → `skipped`; malformed stdout with exit 0 → `failure`; compliant skill → `success` with parsed `result` and `detail` = skill summary; duplicate id runs twice; overall: success / partial-failure / failure / empty; durations ≥ 0
- [x] **Step 2: Verify fail**
- [x] **Step 3: Implement engine** (registry resolution, budget from manifest, subprocess with timeout, stdout validation)
- [x] **Step 4: Verify pass**
- [x] **Step 5: Commit** — `feat(006): skill executor engine with isolation and time budgets`

## Task 2: Executor CLI (FR-009) + contract v1.1 in registry tool

**Files:** Modify `src/execute_skills.py`, `src/skill_registry.py`; extend both test files; update `specs/005-skill-contract/contracts/skill-contract.md`; restamp `skills/registry.json`

- [x] **Step 1: Failing tests** — CLI: plan argv + context stdin → summary stdout, exit 0; garbage stdin → exit 0 + `empty`-plan-style summary with failure note; registry: `time_budget_seconds: -5` → `time-budget` violation; valid budget accepted; `CONTRACT_VERSION == "1.1"`
- [x] **Step 2: Verify fail**
- [x] **Step 3: Implement** CLI `main()`; `time-budget` rule; bump `CONTRACT_VERSION`; v1.1 addendum in contract doc; registry stamp
- [x] **Step 4: Verify pass + ruff**
- [x] **Step 5: Commit** — `feat(006): executor CLI; skill contract v1.1 optional time budget`

## Task 3: Router delegates to executor (DispatchResult v1.1)

**Files:** Modify `src/route_workflows.py`; update `tests/test_route_workflows.py`

**Interfaces produced:** `select_plan(context: dict, config: dict, warnings: list[str]) -> list[str]`; DispatchResult v1.1 (`overall`, `execution`, per-result `status`/`duration_ms`; outcomes derived success→invoked, skipped→unresolvable, failure|timeout→failed); `make_skills_invoker` removed

- [x] **Step 1: Failing tests** — select_plan extraction incl. unroutable-context warning; CLI end-to-end with registered tmp skill → v1.1 shape, outcome mapping, embedded execution summary; invoker tests removed (superseded by executor tests)
- [x] **Step 2: Verify fail**
- [x] **Step 3: Implement** — rewire `main()`, keep `route()` seam for selection tests
- [x] **Step 4: Verify pass (all test files) + ruff**
- [x] **Step 5: Commit** — `feat(006): router delegates execution to skill executor`

## Task 4: E2E + docs sync + finish

- [x] **Step 1: Quickstart E2E** — register fails/slow/works skills, route on pre-commit, real commit → partial-failure summary logged, `works` ran (SC-002); clean up
- [x] **Step 2: Sync CLAUDE.md**; 004 contract addendum pointer (DispatchResult v1.1); check off tasks.md
- [x] **Step 3: Full suite + ruff; commit, push, PR**
