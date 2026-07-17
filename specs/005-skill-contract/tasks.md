# Tasks: Skill Contract

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Skill contract v1.0 + validating registry CLI + registry-based router resolution.

**Architecture:** `validate_manifest(skill_dir) -> list[violations]` pure core; registry file ops in `SkillRegistry`-free plain functions; argparse CLI with `register/deregister/resolve/list/validate`; `route_workflows.make_skills_invoker` swapped to registry lookup.

**Tech Stack:** Python 3.10+ stdlib, pytest, ruff.

## Global Constraints

- stdlib only at runtime; registration CLI may exit non-zero (dev-facing, never in hook path)
- Rejection lists ALL violations by rule name in one pass (SC-003)
- No non-compliant skill enters the registry (SC-002); router resolves only registered skills (SC-004)

---

## Task 1: Manifest validation (US2 core)

**Files:** Create `src/skill_registry.py`, `tests/test_skill_registry.py`

**Interfaces produced:** `CONTRACT_VERSION = "1.0"`; `validate_manifest(skill_dir: str) -> list[str]` returning `"<rule>: <detail>"` strings; `RESERVED_NAMES`

- [x] **Step 1: Failing tests** — compliant manifest → `[]`; each rule violated one at a time → that rule named; all-fields-missing manifest → complete list in one call; missing/unparseable skill.json → `missing-manifest`; non-executable `run` → `entry-point`
- [x] **Step 2: Verify fail**
- [x] **Step 3: Implement `validate_manifest`** (rules 1–9 from research.md)
- [x] **Step 4: Verify pass**
- [x] **Step 5: Commit** — `feat(005): skill manifest validation, contract v1.0`

## Task 2: Registry operations (US1 + FR-006/007/008)

**Files:** Modify `src/skill_registry.py`; extend tests

**Interfaces produced:** `load_registry(skills_dir, warnings) -> dict`; `register_skill(skills_dir, skill_dir, update=False) -> tuple[bool, list[str]]`; `deregister_skill(skills_dir, name, routes_path) -> tuple[bool, list[str]]`; `validate_registry(skills_dir) -> dict[str, list[str]]`

- [x] **Step 1: Failing tests** — register compliant skill → appears in registry.json with contract stamp; duplicate name rejected (`duplicate-name`) unless `update=True`; rejected skill NOT written (SC-002); deregister removes + warns when routes reference the name; resolve/list read paths; `validate_registry` flags a skill whose manifest was broken after registration and reports contract-version drift
- [x] **Step 2: Verify fail**
- [x] **Step 3: Implement registry ops**
- [x] **Step 4: Verify pass**
- [x] **Step 5: Commit** — `feat(005): validating skill registry with dedup and dangling-ref warnings`

## Task 3: CLI

**Files:** Modify `src/skill_registry.py`; extend tests; create `skills/registry.json` (empty catalog)

- [x] **Step 1: Failing tests** — subprocess: `register` ok → exit 0; `register` bad → exit 1 with every violation line; `register` dup → exit 1; `--update` → exit 0; `deregister` unknown → exit 1; `resolve` known/unknown → 0/1; `validate` clean → 0, non-compliant → 1
- [x] **Step 2: Verify fail**
- [x] **Step 3: Implement argparse `main()`**
- [x] **Step 4: Verify pass + ruff**
- [x] **Step 5: Commit** — `feat(005): skill_registry CLI`

## Task 4: Router resolves via registry (FR-004/SC-004)

**Files:** Modify `src/route_workflows.py`; update `tests/test_route_workflows.py` invoker tests

- [x] **Step 1: Failing tests** — registered skill with executable run → `invoked`; unregistered dir present on disk → `unresolvable` ("not registered"); registered but run deleted → `unresolvable`; existing CLI tests keep passing
- [x] **Step 2: Verify fail**
- [x] **Step 3: Rewire `make_skills_invoker`** to registry lookup
- [x] **Step 4: Verify pass (both test files) + ruff**
- [x] **Step 5: Commit** — `feat(005): router resolves skills through the registry`

## Task 5: E2E + docs sync + finish

- [x] **Step 1: Quickstart E2E** — author `hello` skill, register, route on pre-commit, real commit → `invoked=1`; deregister → next commit warns `unresolvable`; clean up
- [x] **Step 2: Sync CLAUDE.md**; check off tasks.md
- [x] **Step 3: Full suite + ruff; commit, push, PR**
