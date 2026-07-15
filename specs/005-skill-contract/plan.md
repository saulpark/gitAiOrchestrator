# Implementation Plan: Skill Contract

**Branch**: `005-skill-contract` | **Date**: 2026-07-16 | **Spec**: [spec.md](./spec.md)
**Input**: Feature specification from `/specs/005-skill-contract/spec.md`

## Summary

Defines skill contract v1.0 (human-readable artifact in
[contracts/skill-contract.md](./contracts/skill-contract.md)) and implements
`src/skill_registry.py`: a CLI that validates a skill's `skill.json` manifest against the
contract, maintains the versioned catalog `skills/registry.json`, and supports
`register` / `deregister` / `resolve` / `list` / `validate`. Rejections report **every**
violation by name in one pass (SC-003). The 004 router's provisional path-based invoker is
replaced by registry-based resolution (FR-004): an identifier is resolvable iff registered.

## Technical Context

**Language/Version**: Python 3.10+ stdlib (`json`, `os`, `re`, `sys`, `argparse`)
**Primary Dependencies**: none at runtime; pytest + ruff dev-only
**Storage**: `skills/registry.json` (versioned catalog, committed); `skills/<dir>/skill.json` manifests
**Testing**: pytest (`tests/test_skill_registry.py` + updated router tests)
**Constraints**: registration CLI is developer-facing — non-zero exit on rejection is correct
(it is never in the git hook path); router/hook path still never aborts git
**Consumers**: 004 router resolves through the registry; 006 executor will own runtime behavior

## Constitution Check

| Principle | Assessment | Notes |
|-----------|------------|-------|
| 4 · Spec Before Automation | ✅ PASS | contract doc (FR-005) precedes any skill authoring |
| 5 · Deterministic & Reviewable | ✅ PASS | registry is a committed JSON file; validation is pure |
| 6 · Safe By Default | ✅ PASS | invalid skills never enter the registry (SC-002); hook path unaffected |
| 11 · Small Composable Scripts | ✅ PASS | registry tool separate from router; validation separate from I/O |
| 12 · Structured Inputs/Outputs | ✅ PASS | manifest, registry, and skill-result schemas all versioned |
| 14 · Observable Execution | ✅ PASS | every violation named; deregistration warns on dangling route refs |

**Gate result: PASS.**

## Project Structure

### Documentation (this feature)

```text
specs/005-skill-contract/
├── plan.md
├── research.md
├── data-model.md
├── quickstart.md
├── contracts/
│   └── skill-contract.md    # THE standalone human-readable contract (FR-005)
└── tasks.md
```

### Source Code Changes

```text
# New files
src/skill_registry.py            # validation + registry CLI
tests/test_skill_registry.py
skills/registry.json             # initial empty catalog (contract_version 1.0)

# Modified
src/route_workflows.py           # make_skills_invoker → registry-based resolution
tests/test_route_workflows.py    # invoker tests updated to registered skills
scripts/orchestrate.sh           # unchanged interface (--skills-dir still passed)
```

## Phase 0: Research

*Findings in [research.md](./research.md)* — manifest format (`skill.json`), contract rules
v1.0, registry layout, duplicate/deregistration semantics, router resolution change.

## Phase 1: Design

*See [data-model.md](./data-model.md), [contracts/skill-contract.md](./contracts/skill-contract.md), [quickstart.md](./quickstart.md)*

### Post-Design Constitution Re-check

| Principle | Re-assessment |
|-----------|--------------|
| 6 · Safe By Default | ✅ SC-002: validation gate is the only write path into the registry |
| 12 · Structured I/O | ✅ manifest v1.0, registry v1.0, skill-result v1.0 all documented |
| 14 · Observable | ✅ SC-003 single-pass complete violation lists; FR-007 dangling-ref warnings |

**Post-design gate: PASS.**

## Complexity Tracking

> No constitution violations — this section is empty by design.
