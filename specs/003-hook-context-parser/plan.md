# Implementation Plan: Hook Context Parser

**Branch**: `003-hook-context-parser` | **Date**: 2026-07-14 | **Spec**: [spec.md](./spec.md)
**Input**: Feature specification from `/specs/003-hook-context-parser/spec.md`

## Summary

A standalone Python parser (`src/parse_context.py`) that reads the raw hook environment
(`HOOK_EVENT`, `HOOK_BRANCH`, `HOOK_FILES`, `HOOK_COMMITS`) and emits a single-line JSON
context object on stdout with an identical schema for all three hook types. Missing or
malformed input produces a *partial* context with explicit `unavailable` markers and
human-readable `errors` — the parser always exits 0. Tested with pytest (SC-004 requires
automated schema comparison).

> **Contract extension (002 → 003)**: The spec requires pre-push contexts to include the
> commits being pushed (US1-3, US2-3), but the 002 hook contract only captures files.
> This feature adds an optional `HOOK_COMMITS` env var to the hook contract and updates
> `scripts/pre-push.sh` to capture it (stays within the 30-line thin-hook budget; other
> hooks unchanged — they simply don't set it).

## Technical Context

**Language/Version**: Python 3.10+ — stdlib only (`json`, `os`, `re`, `sys`); matches 001
**Primary Dependencies**: none at runtime; `pytest` + `ruff` for development (already project commands)
**Storage**: N/A — context is emitted to stdout, never persisted (spec assumption)
**Testing**: pytest (`tests/test_parse_context.py`); manual CLI check via quickstart
**Target Platform**: macOS and Linux developer machines + CI
**Project Type**: Python module with CLI entry point
**Performance Goals**: < 1 s for 1,000 changed files (SC-003)
**Constraints**: Always exit 0 (SC-005); parser runs no git commands — hooks are the capture point
**Consumer**: `scripts/orchestrate.sh` will invoke it in 004 (workflow-router); standalone until then (FR-007)

## Constitution Check

| Principle | Assessment | Notes |
|-----------|------------|-------|
| 2 · Git Is Change Authority | ✅ PASS | Raw data captured by 002 hooks from git; parser only normalizes |
| 4 · Spec Before Automation | ✅ PASS | spec.md + this plan precede implementation |
| 5 · Deterministic & Reviewable | ✅ PASS | Pure function of env input; sorted, deduped output |
| 6 · Safe By Default | ✅ PASS | Always exit 0; catastrophic failure emits fallback partial context |
| 11 · Small Composable Scripts | ✅ PASS | One module, one responsibility; CLI-invocable |
| 12 · Structured Inputs/Outputs | ✅ PASS | Versioned JSON schema (`schema_version`), documented contract |
| 14 · Observable Execution | ✅ PASS | `errors` array carries every parse anomaly; nothing silent |

**Gate result: PASS.**

## Project Structure

### Documentation (this feature)

```text
specs/003-hook-context-parser/
├── plan.md              # This file
├── research.md          # Phase 0 output
├── data-model.md        # Phase 1 output
├── quickstart.md        # Phase 1 output
├── contracts/
│   └── context-schema.md
└── tasks.md             # Phase 2 output
```

### Source Code Changes

```text
# New files
src/parse_context.py         # Parser module + CLI (python3 src/parse_context.py)
tests/test_parse_context.py  # pytest suite: schema uniformity, normalization, partial contexts

# Modified (hook contract v1.1)
scripts/pre-push.sh          # Also captures HOOK_COMMITS (rev-list of pushed range)
```

## Phase 0: Research

*Findings consolidated in [research.md](./research.md)*

Resolved decisions:
- **Language**: Python 3.10+ stdlib (project convention; JSON needs no external deps)
- **Input**: environment variables only — parser never runs git (hooks are the capture point)
- **Output**: single-line JSON on stdout; `schema_version: "1.0"`
- **Commits for pre-push**: new `HOOK_COMMITS` env var captured by pre-push.sh via `git rev-list`
- **Path normalization**: repo-relative, `normpath`, deduped, sorted; absolute paths made relative to cwd (hooks run at repo root); paths outside the repo dropped with an error note
- **Partial contexts**: unset env var → field in `unavailable[]`; empty string `HOOK_FILES` → valid empty list (spec: empty change set is not an error)
- **Exit code**: always 0, including on internal exceptions (fallback context emitted)

## Phase 1: Design

*See [data-model.md](./data-model.md), [contracts/context-schema.md](./contracts/context-schema.md), [quickstart.md](./quickstart.md)*

### Post-Design Constitution Re-check

| Principle | Re-assessment |
|-----------|--------------|
| 6 · Safe By Default | ✅ `main()` wraps `parse_context()` in try/except emitting fallback partial context, exit 0 |
| 12 · Structured I/O | ✅ all 8 fields present in every output; schema versioned for breaking changes |
| 14 · Observable | ✅ every dropped path/commit and missing field appends to `errors[]` |

**Post-design gate: PASS.**

## Complexity Tracking

> No constitution violations — this section is empty by design.
