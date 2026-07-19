# Data Model: Skill Executor

**Branch**: `006-skill-executor` | **Date**: 2026-07-18

## Entity: ExecutionPlan

Ordered list of skill identifier strings, produced by `route_workflows.select_plan()` from
the routing config for the context's event. Duplicates allowed (run per occurrence).
Empty plan is valid → summary `overall: "empty"`.

## Entity: SkillInvocation

One subprocess run: `skills/<dir>/run` ← context JSON stdin, bounded by the skill's time
budget (manifest `time_budget_seconds` or default 30 s). Produces an ExecutionResult.

## Entity: ExecutionResult

| Field | Type | Notes |
|-------|------|-------|
| `skill` | string | identifier from the plan |
| `status` | enum | `success` / `failure` / `timeout` / `skipped` |
| `duration_ms` | int | wall clock; 0 for `skipped` |
| `detail` | string | skill summary on success; error text otherwise |
| `result` | object \| null | parsed `skill-result@1.0` or null |

## Entity: ExecutionSummary

See [contracts/execution-summary.md](./contracts/execution-summary.md). Contains `event`,
`overall`, total `duration_ms`, ordered `results` (same order as plan — SC-001).

## Entity: TimeBudget

Resolution order: `skill.json:time_budget_seconds` → executor `--default-budget` → 30 s.
Validated at registration when present (`time-budget` rule, contract v1.1).

## Flow

```text
hook → orchestrate.sh → parse_context.py ─ context ─→ route_workflows.py
                                                        │ select_plan(config)
                                                        ▼
                                          execute_skills.execute_plan(plan, context)
                                                        │ per skill: resolve → run → status
                                                        ▼
                                    DispatchResult v1.1 (embeds ExecutionSummary)
                                    stdout (discarded by hook) + hooks.log summary line
```
