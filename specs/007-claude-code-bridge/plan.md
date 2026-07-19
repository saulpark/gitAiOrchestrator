# Implementation Plan: Claude Code Bridge

**Branch**: `007-claude-code-bridge` | **Date**: 2026-07-19 | **Spec**: [spec.md](./spec.md)
**Input**: Feature specification from `/specs/007-claude-code-bridge/spec.md`

## Summary

`src/claude_bridge.py`: the shared component skills use to call Claude Code. A skill sends
a BridgeRequest (hook context + task) on stdin; the bridge builds a **bounded prompt**
(event, branch, changed files, commits — never the full repo), invokes the `claude` CLI
headless (`claude -p --output-format json`) in the repo cwd so the project's own Claude
Code settings/CLAUDE.md govern the call (FR-004), and returns a BridgeResult
(`ok` / `error` / `timeout` / `unavailable`). Claude Code hook integration is opt-in via
`config/bridge.json` (`hooks_enabled`); when off, the bridge passes
`--settings '{"disableAllHooks": true}'`. The runner is injectable for isolation tests
(FR-008).

## Technical Context

**Language/Version**: Python 3.10+ stdlib (`json`, `os`, `shutil`, `subprocess`, `sys`, `time`, `argparse`)
**Primary Dependencies**: `claude` CLI at runtime (absence handled: structured `unavailable`)
**Storage**: `config/bridge.json` (bridge configuration, committed; re-read per invocation)
**Testing**: pytest with injectable runner + fake `claude` executables on PATH
**Constraints**: exit 0 always (skills decide); no caching; no shared mutable state;
bounded context only (SC-005)

## Constitution Check

| Principle | Assessment | Notes |
|-----------|------------|-------|
| 1 · Incremental First | ✅ PASS | prompt bounded to the change set, never repo scans |
| 3 · Claude Code Is Engine | ✅ PASS | this is the single integration point skills share |
| 5 · Deterministic & Reviewable | ✅ PASS | same request+config → same claude argv; prompt is inspectable |
| 6 · Safe By Default | ✅ PASS | unavailable/timeout/error all structured; exit 0 |
| 11 · Small Composable | ✅ PASS | one module; request/response seam; injectable runner |
| 12 · Structured I/O | ✅ PASS | bridge-request@1.0 / bridge-result@1.0 versioned |
| 14 · Observable | ✅ PASS | duration, error type, stderr excerpts in every result |

**Gate result: PASS.**

## Project Structure

```text
specs/007-claude-code-bridge/
├── plan.md  research.md  data-model.md  quickstart.md  tasks.md
└── contracts/bridge-interface.md

# New
src/claude_bridge.py             # bridge module + CLI
tests/test_claude_bridge.py
config/bridge.json               # bridge configuration (hooks_enabled: false default)
```

## Phase 0: Research

*Findings in [research.md](./research.md)* — headless CLI shape, settings inheritance via
cwd, hooks toggle mechanism, bounded-prompt construction, availability detection.

## Phase 1: Design

*See [data-model.md](./data-model.md), [contracts/bridge-interface.md](./contracts/bridge-interface.md), [quickstart.md](./quickstart.md)*

### Post-Design Constitution Re-check

| Principle | Re-assessment |
|-----------|--------------|
| 3 · Engine | ✅ SC-001: skills need zero Claude-specific logic — request in, result out |
| 6 · Safe By Default | ✅ SC-003: `shutil.which` gate + try/except → structured `unavailable`/`error` |
| 12 · Structured I/O | ✅ result parses claude's JSON output when possible, raw text fallback preserved |

**Post-design gate: PASS.**

## Complexity Tracking

> No constitution violations — this section is empty by design.
