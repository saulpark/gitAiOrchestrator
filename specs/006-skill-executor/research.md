# Research: Skill Executor

**Branch**: `006-skill-executor` | **Date**: 2026-07-18

---

## Decision: Time Budget Source — optional manifest field (contract v1.1)

**Decision**: Default 30 s per skill (spec assumption). A skill may declare
`time_budget_seconds` in `skill.json` (number, 0 < n ≤ 600). Skill contract bumps to
**v1.1** (additive, optional field — existing skills remain compliant); validation gains
rule `time-budget` (only when the field is present and invalid).
**Rationale**: Spec: budget "defined per skill in the skill contract or overridden in the
routing configuration". The manifest is the per-skill home; a routing-config override would
break 004's `routes` schema (lists of strings) for marginal value — deferred.
**Alternatives considered**:
- Route-level override — rejected: breaks routes schema v1.0; nothing needs it yet
- Executor CLI flag only — rejected: not per-skill, contradicts spec wording

---

## Decision: Strict Output Validation (edge case resolved: yes, failure)

**Decision**: A skill that exits 0 must emit one parseable JSON object on stdout with
`schema_version`, `skill`, `status` (`skill-result@1.0`). Non-conforming stdout →
executor records `failure` with detail `malformed output…`. Non-zero exit → `failure`
regardless of stdout. TimeoutExpired → `timeout`. Unresolvable at execution time →
`skipped` (complements the 004 router warning).
**Rationale**: The 005 contract promises downstream consumers a uniform result shape;
trusting it without checking would push malformed data into the orchestration layer. The
executor is the enforcement point the 005 spec explicitly deferred to runtime.

---

## Decision: Status & Overall Semantics

- Per-skill: `success` | `failure` | `timeout` | `skipped` (FR-005)
- Overall (FR-006/008): all success → `success`; ≥1 non-success and ≥1 success →
  `partial-failure`; all non-success → `failure`; empty plan → `empty`
- `skipped`/`timeout` count as non-success for the overall computation
- Duplicate identifiers in a plan run once per occurrence (004 decision carries over)
- Partial contexts (003) are passed through unmodified — skills decide (contract rule)

---

## Decision: Router Integration — router selects, executor runs

**Decision**: `route_workflows.select_plan(context, config, warnings) -> list[str]`
extracts the plan; `main()` calls `execute_skills.execute_plan(plan, context, skills_dir)`
and emits **DispatchResult v1.1**: adds top-level `overall`, per-result `status` +
`duration_ms` (mapping: success→`invoked`, skipped→`unresolvable`, failure/timeout→`failed`
keeps 004's outcome vocabulary), and embeds the full summary under `execution`.
`make_skills_invoker` is removed — resolution + execution live in the executor now.
`route(context, config, invoker)` stays as the documented seam for selection-logic tests.
**Rationale**: Matches the spec's layering assumption ("executor receives an
already-resolved execution plan from the workflow router") without a third process in the
orchestrate pipeline.
**Consequence**: DispatchResult stdout consumers must accept v1.1 (only known consumer is
orchestrate.sh, which discards stdout; tests updated).

---

## Decision: Executor Failure Containment

**Decision**: Each invocation wrapped in try/except; `subprocess.run(timeout=budget)`
handles termination (kills the child on timeout). An executor-level exception during one
skill records `failure` for that skill and continues. `main()` wraps everything; exit 0
always; summary emitted immediately after the loop (SC-005).
