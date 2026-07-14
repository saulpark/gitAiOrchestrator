# Implementation Plan: Workflow Router

**Branch**: `004-workflow-router` | **Date**: 2026-07-14 | **Spec**: [spec.md](./spec.md)
**Input**: Feature specification from `/specs/004-workflow-router/spec.md`

## Summary

A Python router (`src/route_workflows.py`) that reads the 003 hook context JSON on stdin,
loads `config/routes.json` fresh on every invocation (FR-007), and dispatches each mapped
workflow identifier through an injectable invoker. Outcomes (`invoked`, `unresolvable`,
`failed`) are reported per workflow in a DispatchResult JSON on stdout; warnings go to
stderr with a `[router warning]` prefix; the router always exits 0 (SC-004).
`scripts/orchestrate.sh` is upgraded from stub to the real two-stage pipeline:
`parse_context.py | route_workflows.py`.

> **Invocation-layer boundary (spec non-goal)**: The router selects and hands off. The
> default invoker used by the CLI is *provisional*: an identifier resolves to an
> executable at `skills/<identifier>/run`, which receives the context JSON on stdin.
> Features 005 (skill contract) and 006 (skill executor) formalize/replace this. Tests
> use fake invokers (FR-009), so the provisional resolution is not load-bearing.

## Technical Context

**Language/Version**: Python 3.10+ stdlib only (`json`, `os`, `subprocess`, `sys`, `argparse`, `datetime`)
**Primary Dependencies**: none at runtime; pytest + ruff via `.venv` (dev-only)
**Storage**: `config/routes.json` (versioned routing truth); log lines appended to `logs/hooks.log`
**Testing**: pytest (`tests/test_route_workflows.py`)
**Target Platform**: macOS and Linux + CI
**Performance Goals**: config load + selection < 100 ms (SC-005)
**Constraints**: always exit 0; missing/malformed config = empty config + warning (FR-008); config re-read per invocation (FR-007)
**Consumers**: invoked by `scripts/orchestrate.sh`; workflows invoked per 005/006 contracts later

## Constitution Check

| Principle | Assessment | Notes |
|-----------|------------|-------|
| 4 · Spec Before Automation | ✅ PASS | spec.md + this plan precede implementation |
| 5 · Deterministic & Reviewable | ✅ PASS | Same context + config → same dispatch plan, configured order preserved |
| 6 · Safe By Default | ✅ PASS | Exit 0 always; per-workflow failure isolation (spec assumption) |
| 11 · Small Composable Scripts | ✅ PASS | Selection (router) separated from execution (invoker) |
| 12 · Structured Inputs/Outputs | ✅ PASS | Context JSON in, DispatchResult JSON out, versioned config schema |
| 14 · Observable Execution | ✅ PASS | Every skip/failure logged or warned; `[router warning]` prefix on stderr |

**Gate result: PASS.**

## Project Structure

### Documentation (this feature)

```text
specs/004-workflow-router/
├── plan.md
├── research.md
├── data-model.md
├── quickstart.md
├── contracts/
│   └── routing-config.md
└── tasks.md
```

### Source Code Changes

```text
# New files
src/route_workflows.py           # Router module + CLI
tests/test_route_workflows.py    # pytest suite
config/routes.json               # Initial routing config (all events → [])

# Replaced (002 stub → real pipeline)
scripts/orchestrate.sh           # parse_context.py | route_workflows.py
```

## Phase 0: Research

*Findings consolidated in [research.md](./research.md)*

Resolved decisions:
- **Config format**: JSON (`config/routes.json`) — stdlib parseable; YAML/TOML need deps or 3.11+ quirks
- **Config schema**: `{"version": "1.0", "routes": {"<event>": ["id", ...]}}`
- **Router I/O**: context JSON on stdin → DispatchResult JSON on stdout; warnings on stderr; exit 0
- **Invoker abstraction**: `route(context, config, invoker)` takes a callable — tests inject fakes (FR-009)
- **Provisional default invoker**: `skills/<id>/run` executable, context JSON on stdin, 60 s guard
- **Failure isolation**: exceptions per workflow are caught; remaining workflows still run
- **Logging**: router appends its own timestamped summary line to `logs/hooks.log` (replaces stub's line)

## Phase 1: Design

*See [data-model.md](./data-model.md), [contracts/routing-config.md](./contracts/routing-config.md), [quickstart.md](./quickstart.md)*

### Post-Design Constitution Re-check

| Principle | Re-assessment |
|-----------|--------------|
| 6 · Safe By Default | ✅ malformed config, unroutable context, invoker crash — all paths exit 0 with warning |
| 12 · Structured I/O | ✅ DispatchResult carries per-workflow outcome enum; config versioned |
| 14 · Observable | ✅ skip-with-log on unconfigured events (FR-006), warning on every failure (SC-003) |

**Post-design gate: PASS.**

## Complexity Tracking

> No constitution violations — this section is empty by design.
