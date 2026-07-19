# Implementation Plan: Run Observability and Outcome Enforcement

**Branch**: `008-run-observability` | **Date**: 2026-07-19 | **Spec**: [spec.md](./spec.md)
**Input**: Feature specification from `/specs/008-run-observability/spec.md`

## Summary

`src/run_records.py`: evaluates an outcome (`block` / `warn` / `skip`; default **warn**,
FR-009) for every skill result against per-skill rules in `config/routes.json` v1.1
(`"outcomes": {"<skill>": {"on_failure": "block"}}`), writes a run record JSON to
`logs/runs/` for **every** run (SC-002, retention default 50), and provides a
`list` / `show` history CLI (FR-003). The router applies the evaluation: block → stderr
`[hook blocked]` message + **exit 10** (a reserved code); warn → visible warning, exit 0;
skip → silent, log only. The 002 hooks gain a shared `_finish_hook` helper in `lib.sh`
that translates exit 10 into a non-zero hook exit (aborting pre-commit/pre-push) while
every other failure still exits 0. Post-merge blocks are downgraded to warn (the merge
already happened).

> **Deliberate 002 contract change**: hooks no longer *unconditionally* exit 0. Exit 10
> from orchestration is the one signal that aborts the git operation — explicit, opt-in
> configuration only (FR-006). All other failures (crash, timeout, exit 1) keep the
> non-blocking guarantee. Documented as an 002 contract addendum.

## Technical Context

**Language/Version**: Python 3.10+ stdlib; POSIX sh for the hook helper
**Storage**: `logs/runs/<timestamp>-<event>.json` (gitignored, local); rules in `config/routes.json` (versioned)
**Testing**: pytest + shell checks for `_finish_hook`
**Constraints**: run record written best-effort after execution; block only for
pre-commit/pre-push; default outcome warn; rules re-read per run (SC-005)

## Constitution Check

| Principle | Assessment | Notes |
|-----------|------------|-------|
| 5 · Deterministic & Reviewable | ✅ PASS | same results + rules → same outcomes; records are plain JSON |
| 6 · Safe By Default | ✅ PASS | default warn (FR-009); block requires explicit per-skill config; timeouts/crashes never block |
| 12 · Structured I/O | ✅ PASS | run-record@1.0; routes v1.1 additive; DispatchResult v1.2 additive |
| 14 · Observable Execution | ✅ PASS | this feature — records for 100% of runs, history CLI, diagnostic detail |

**Gate result: PASS.**

## Project Structure

```text
specs/008-run-observability/
├── plan.md  research.md  data-model.md  quickstart.md  tasks.md
└── contracts/run-record.md

# New
src/run_records.py               # outcome evaluation + record store + history CLI
tests/test_run_records.py

# Modified
src/route_workflows.py           # evaluate outcomes, write record, exit 10 on block; DispatchResult v1.2
tests/test_route_workflows.py    # outcome/exit-code/record tests
config/routes.json               # v1.1: optional "outcomes" + "run_retention"
scripts/lib.sh                   # _finish_hook helper (exit-10 → abort; else warn + exit 0)
scripts/pre-commit.sh            # tail replaced with _finish_hook $?
scripts/pre-push.sh              # tail replaced with _finish_hook $?
scripts/post-merge.sh            # tail replaced with _finish_hook $? (block never reaches it)
specs/002-git-hook-scripts/contracts/orchestration-interface.md  # exit-code addendum
specs/004-workflow-router/contracts/routing-config.md            # v1.1 routes schema addendum
```

## Phase 0: Research

*Findings in [research.md](./research.md)* — exit-code protocol, rule shape, downgrade
semantics, record store layout, retention.

## Phase 1: Design

*See [data-model.md](./data-model.md), [contracts/run-record.md](./contracts/run-record.md), [quickstart.md](./quickstart.md)*

### Post-Design Constitution Re-check

| Principle | Re-assessment |
|-----------|--------------|
| 6 · Safe By Default | ✅ block is the only non-zero path and requires explicit config; hook timeout (143) warns, never blocks |
| 12 · Structured I/O | ✅ all three schema changes additive with version bumps |
| 14 · Observable | ✅ SC-001/003: `show --last` renders event, per-skill status+rule+outcome, final decision |

**Post-design gate: PASS.**

## Complexity Tracking

> No constitution violations — this section is empty by design.
