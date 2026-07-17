# Implementation Plan: Skill Executor

**Branch**: `006-skill-executor` | **Date**: 2026-07-18 | **Spec**: [spec.md](./spec.md)
**Input**: Feature specification from `/specs/006-skill-executor/spec.md`

## Summary

`src/execute_skills.py` runs an ordered execution plan: for each skill identifier it
resolves through the 005 registry, runs `skills/<dir>/run` with the unmodified context on
stdin under a per-skill time budget (default 30 s; optional `time_budget_seconds` in the
manifest — skill contract v1.1), validates stdout against `skill-result@1.0`, and records
status (`success` / `failure` / `timeout` / `skipped`), duration, and detail. The full run
becomes an ExecutionSummary with an overall status. The 004 router CLI now delegates the
run loop to the executor and emits DispatchResult v1.1 embedding the summary; the
provisional `make_skills_invoker` is retired.

## Technical Context

**Language/Version**: Python 3.10+ stdlib (`json`, `os`, `subprocess`, `sys`, `time`, `argparse`)
**Testing**: pytest (`tests/test_execute_skills.py` + updated router/registry tests)
**Constraints**: executor exits 0 always (FR-007/SC-004); summary emitted immediately after
last skill (SC-005); sequential execution only; context passed unmodified (FR-002)
**Contract changes**: skill contract 1.0 → **1.1** (optional `time_budget_seconds`);
DispatchResult 1.0 → **1.1** (adds `overall`, per-result `status` + `duration_ms`,
embedded `execution` summary)

## Constitution Check

| Principle | Assessment | Notes |
|-----------|------------|-------|
| 5 · Deterministic & Reviewable | ✅ PASS | plan order preserved; same plan+context → same statuses |
| 6 · Safe By Default | ✅ PASS | per-skill isolation; timeouts enforced; exit 0 always |
| 11 · Small Composable Scripts | ✅ PASS | selection (004) / resolution (005) / execution (006) separated |
| 12 · Structured I/O | ✅ PASS | execution-summary@1.0 documented; contract bumps versioned |
| 14 · Observable | ✅ PASS | per-skill status+duration+detail; overall status; log line |

**Gate result: PASS.**

## Project Structure

```text
specs/006-skill-executor/
├── plan.md  research.md  data-model.md  quickstart.md  tasks.md
└── contracts/execution-summary.md

# New
src/execute_skills.py            # engine + CLI (FR-009)
tests/test_execute_skills.py

# Modified
src/route_workflows.py           # select_plan(); main() delegates to executor; DispatchResult v1.1
src/skill_registry.py            # CONTRACT_VERSION 1.1; optional time-budget rule
tests/test_route_workflows.py    # invoker tests migrate to executor; CLI tests → v1.1
tests/test_skill_registry.py     # time-budget validation cases
specs/005-skill-contract/contracts/skill-contract.md   # v1.1 addendum
skills/registry.json             # contract stamp 1.1
scripts/orchestrate.sh           # unchanged (same CLI surface)
```

## Phase 0: Research

*Findings in [research.md](./research.md)* — budget source, strict output validation,
status/overall semantics, router integration shape.

## Phase 1: Design

*See [data-model.md](./data-model.md), [contracts/execution-summary.md](./contracts/execution-summary.md), [quickstart.md](./quickstart.md)*

### Post-Design Constitution Re-check

| Principle | Re-assessment |
|-----------|--------------|
| 6 · Safe By Default | ✅ TimeoutExpired handled; executor-level exception → summary with failure, exit 0 |
| 12 · Structured I/O | ✅ execution-summary@1.0; DispatchResult v1.1 additive except stdout consumer note |
| 14 · Observable | ✅ SC-003: every plan (empty/all-fail/all-timeout) yields a summary |

**Post-design gate: PASS.**

## Complexity Tracking

> No constitution violations — this section is empty by design.
