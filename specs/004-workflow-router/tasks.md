# Tasks: Workflow Router

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Config-driven dispatch: context JSON in, mapped workflows invoked in order, DispatchResult out, never aborts git.

**Architecture:** `route(context, config, invoker)` pure core with injectable invoker; `load_config(path)` tolerant loader; CLI wires stdin/stdout/stderr + provisional `skills/<id>/run` invoker; `orchestrate.sh` becomes `parse_context.py | route_workflows.py`.

**Tech Stack:** Python 3.10+ stdlib, pytest, ruff.

## Global Constraints

- stdlib only at runtime; exit 0 always (SC-004); config re-read per invocation (FR-007)
- Config load + selection < 100 ms (SC-005)
- Every dispatch failure produces a visible warning (SC-003); unconfigured events skip with log only (FR-006)
- orchestrate.sh stays POSIX sh, thin (constitution §11)

---

## Task 1: Core routing with injectable invoker (US1)

**Files:** Create `src/route_workflows.py`, `tests/test_route_workflows.py`

**Interfaces produced:** `route(context: dict, config: dict, invoker) -> dict` (DispatchResult); `OUTCOMES = ("invoked", "unresolvable", "failed")`; `RESULT_SCHEMA_VERSION = "1.0"`

- [ ] **Step 1: Failing tests** — mapped workflows invoked in configured order with context passed; multiple workflows → independent results; event not in routes → empty results; other events' workflows not invoked
- [ ] **Step 2: Verify fail** — `pytest tests/test_route_workflows.py -q` → ModuleNotFoundError
- [ ] **Step 3: Implement `route()`** — look up `config["routes"].get(event)`, call invoker per identifier in order, collect results
- [ ] **Step 4: Verify pass**
- [ ] **Step 5: Commit** — `feat(004): config-driven dispatch core with injectable invoker`

## Task 2: Failure isolation + unroutable contexts (US3)

**Files:** Modify `src/route_workflows.py`; extend tests

- [ ] **Step 1: Failing tests** — invoker exception → `failed` outcome + warning, subsequent workflows still run; `failed`/`unresolvable` outcomes append warnings naming the workflow; `event: null` → empty results + warning; invalid invoker outcome value → coerced to `failed`
- [ ] **Step 2: Verify fail**
- [ ] **Step 3: Implement** — try/except around invoker, warning accumulation, event validation
- [ ] **Step 4: Verify pass**
- [ ] **Step 5: Commit** — `feat(004): per-workflow failure isolation and warnings`

## Task 3: Tolerant config loader (US2, FR-007/008)

**Files:** Modify `src/route_workflows.py`; extend tests

**Interfaces produced:** `load_config(path: str, warnings: list[str]) -> dict`

- [ ] **Step 1: Failing tests** — valid file loads; missing file → empty routes + warning; malformed JSON → empty + warning; `routes` not a dict → empty + warning; route value not list-of-str → that event `[]` + warning; unknown event key → ignored + warning
- [ ] **Step 2: Verify fail**
- [ ] **Step 3: Implement `load_config`**
- [ ] **Step 4: Verify pass**
- [ ] **Step 5: Commit** — `feat(004): tolerant routing-config loader`

## Task 4: CLI + provisional skills invoker + logging

**Files:** Modify `src/route_workflows.py`; extend tests; create `config/routes.json`

**Interfaces produced:** CLI per contracts/routing-config.md; `make_skills_invoker(skills_dir: str) -> callable`

- [ ] **Step 1: Failing tests** — CLI: context on stdin → DispatchResult on stdout, exit 0; garbage stdin → exit 0 + warning; missing config → exit 0 + stderr warning; skills invoker: executable `run` invoked with context on stdin (tmp_path), non-zero exit → `failed`, missing dir → `unresolvable`; `--log` appends summary line; selection perf < 100 ms
- [ ] **Step 2: Verify fail**
- [ ] **Step 3: Implement** `main()`, `make_skills_invoker`, `_log_summary`; add initial `config/routes.json` (all three events → `[]`)
- [ ] **Step 4: Verify pass + ruff clean**
- [ ] **Step 5: Commit** — `feat(004): router CLI, provisional skills invoker, log summary`

## Task 5: Wire orchestrate.sh to the real pipeline

**Files:** Rewrite `scripts/orchestrate.sh`

- [ ] **Step 1: Rewrite** — `parse_context.py | route_workflows.py --config … --log …`, POSIX sh, thin
- [ ] **Step 2: Verify constraints** — `sh -n`, business-logic grep on hook scripts still clean (orchestrate.sh is not a hook script; hooks unchanged)
- [ ] **Step 3: End-to-end test** — quickstart US1 demo: temp skill + config edit + commit → skill ran; revert; unconfigured event skips with log line (FR-006); missing-config warning path (US3)
- [ ] **Step 4: Commit** — `feat(004): orchestrate.sh runs parse→route pipeline`

## Task 6: Docs sync + finish

**Files:** Modify `CLAUDE.md`; check off tasks.md

- [ ] **Step 1: Full suite** — `pytest tests/ -q` (both features' tests) + `ruff check src/ tests/`
- [ ] **Step 2: Sync CLAUDE.md** (004 line in Active Technologies + Recent Changes)
- [ ] **Step 3: Commit, push, PR**
