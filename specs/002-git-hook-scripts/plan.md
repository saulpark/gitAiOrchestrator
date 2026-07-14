# Implementation Plan: Git Hook Scripts

**Branch**: `002-git-hook-scripts` | **Date**: 2026-05-23 | **Spec**: [spec.md](./spec.md)
**Input**: Feature specification from `/specs/002-git-hook-scripts/spec.md`

## Summary

Three thin POSIX sh hook scripts (`scripts/pre-commit.sh`, `scripts/post-merge.sh`, `scripts/pre-push.sh`) that capture the minimum event context (event type, branch, changed files) and delegate to `scripts/orchestrate.sh` via environment variables. Always exit 0 — never block a git operation. 5-second timeout with cross-platform detection (`timeout`/`gtimeout`/background-kill fallback).

> **Note on 001 → 002 transition**: Feature 001 created a `post-commit` hook stub. Feature 002 spec requires `pre-commit` (fires before commit, captures staged files). This plan adds `.githooks/pre-commit` + `scripts/pre-commit.sh` and removes the 001 `post-commit` stubs.

## Technical Context

**Language/Version**: POSIX sh (`#!/bin/sh`) — no bash-isms; CI and interactive terminal compatible
**Primary Dependencies**: git (already required by 001); no external packages
**Storage**: N/A — logs written to `logs/hooks.log`
**Testing**: Manual verification via git operations
**Target Platform**: macOS and Linux developer machines + CI environments
**Project Type**: Shell scripts (hook executors)
**Performance Goals**: Hook overhead < 2 seconds perceived (SC-002); async mode has no constraint
**Constraints**: Always `exit 0`; orchestration failures must never abort git operations

## Orchestration Entry Point Interface

Hook scripts communicate with `scripts/orchestrate.sh` via environment variables:

```sh
HOOK_EVENT="<event>"   \
HOOK_BRANCH="<branch>" \
HOOK_FILES="<newline-delimited file list>" \
scripts/orchestrate.sh
```

| Variable | Description | Example |
|----------|-------------|---------|
| `HOOK_EVENT` | Git event type | `pre-commit`, `post-merge`, `pre-push` |
| `HOOK_BRANCH` | Current branch name | `main`, `002-git-hook-scripts` |
| `HOOK_FILES` | Newline-delimited changed paths | `src/foo.py\nsrc/bar.py` |

`scripts/orchestrate.sh` is a stub in this feature — fully implemented in 003/004.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Assessment | Notes |
|-----------|------------|-------|
| 1 · Incremental First | ✅ PASS | Hooks use git plumbing for minimal bounded diff per event |
| 2 · Git Is Change Authority | ✅ PASS | Hooks fire on git events; `git diff-tree`, `rev-parse` for context |
| 4 · Spec Before Automation | ✅ PASS | spec.md defined before implementation |
| 5 · Deterministic & Reviewable | ✅ PASS | Same staged state → same delegation call |
| 6 · Safe By Default | ✅ PASS | Always `exit 0`; orchestration failures emit warnings, never abort |
| 11 · Small Composable Scripts | ✅ PASS | Each hook < 30 lines (SC-004); delegates all logic to orchestrate.sh |
| 12 · Structured Inputs/Outputs | ✅ PASS | Env var protocol is machine-readable and documented |
| 14 · Observable Execution | ✅ PASS | Timeout and failure warnings printed to stderr |

**Gate result: PASS — no violations. Proceed to Phase 0.**

## Project Structure

### Documentation (this feature)

```text
specs/002-git-hook-scripts/
├── plan.md              # This file
├── research.md          # Phase 0 output
├── data-model.md        # Phase 1 output
├── quickstart.md        # Phase 1 output
├── contracts/           # Phase 1 output
│   └── orchestration-interface.md
└── tasks.md             # Phase 2 output (/speckit.tasks)
```

### Source Code Changes

```text
# New files
scripts/pre-commit.sh        # Captures staged files, delegates to orchestrate.sh
scripts/orchestrate.sh       # Stub entry point — fully implemented in 003/004
.githooks/pre-commit         # New launcher → scripts/pre-commit.sh

# Replaced (001 stubs → real implementations)
scripts/post-merge.sh        # Captures ORIG_HEAD..HEAD diff, delegates
scripts/pre-push.sh          # Parses stdin refs, delegates

# Removed (post-commit replaced by pre-commit)
.githooks/post-commit        # Remove — superseded by .githooks/pre-commit
scripts/post-commit.sh       # Remove — superseded by scripts/pre-commit.sh

# Modified (001 installer kept in sync)
install.py                   # hooks_to_install: post-commit → pre-commit (FR-008)
```

## Phase 0: Research

*Findings consolidated in [research.md](./research.md)*

Resolved decisions:
- **Shell**: `#!/bin/sh` POSIX — no bash features needed
- **pre-commit files**: `git diff --cached --name-only --diff-filter=ACM`
- **post-merge files**: `git diff-tree -r --name-only --no-commit-id ORIG_HEAD HEAD`
- **pre-push files**: stdin loop parsing `local_ref local_sha remote_ref remote_sha`
- **Branch**: `git rev-parse --abbrev-ref HEAD` (compatible pre-2.22)
- **Timeout**: detect `timeout` → `gtimeout` → background+kill fallback
- **Fire-and-forget**: `cmd </dev/null >>logs/hooks.log 2>&1 & disown $!`
- **Error handling**: capture exit code, warn to stderr, always `exit 0`
- **Context protocol**: env vars (`HOOK_EVENT`, `HOOK_BRANCH`, `HOOK_FILES`)

## Phase 1: Design

*See [data-model.md](./data-model.md), [contracts/orchestration-interface.md](./contracts/orchestration-interface.md), [quickstart.md](./quickstart.md)*

### Post-Design Constitution Re-check

| Principle | Re-assessment |
|-----------|--------------|
| 6 · Safe By Default | ✅ `exit 0` enforced in all error paths including timeout |
| 11 · Small Composable | ✅ hook scripts 20–28 lines each; orchestrate.sh is separate |
| 14 · Observable | ✅ stderr warnings with `[hook warning]` prefix; log file for async |

**Post-design gate: PASS.**

## Complexity Tracking

> No constitution violations — this section is empty by design.
