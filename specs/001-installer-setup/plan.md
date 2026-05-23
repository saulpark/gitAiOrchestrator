# Implementation Plan: Automated Install Flow

**Branch**: `001-installer-setup` | **Date**: 2026-04-10 | **Spec**: [spec.md](./spec.md)
**Input**: Feature specification from `/specs/001-installer-setup/spec.md`

## Summary

A standalone Python 3.10+ install script (`install.py`) invoked via `python install.py` that validates prerequisites (Git ≥ 2.28, Claude Code CLI, uv), configures `git config core.hooksPath .githooks`, creates required directories, and makes hook scripts executable. Validates all prerequisites before making any changes. Detects already-configured environments and exits cleanly.

## Technical Context

**Language/Version**: Python 3.10+
**Primary Dependencies**: stdlib only (`subprocess`, `shutil`, `pathlib`, `sys`) — no third-party packages required
**Storage**: N/A — filesystem operations only (git config, mkdir, chmod)
**Testing**: pytest
**Target Platform**: macOS and Linux developer machines
**Project Type**: CLI installer script (standalone, not a pip package)
**Performance Goals**: < 30 seconds end-to-end (SC-003); prerequisite checks are near-instant
**Constraints**: No sudo/root required; all changes scoped to repository and local git config

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Assessment | Notes |
|-----------|------------|-------|
| 4 · Spec Before Automation | ✅ PASS | spec.md defined before any implementation |
| 5 · Deterministic & Reviewable | ✅ PASS | Idempotent; all changes are normal file/config ops |
| 6 · Safe By Default | ✅ PASS | All prerequisites validated before any modification; warns before overwriting existing `core.hooksPath` |
| 9 · Validation Required | ✅ PASS | Prerequisite validation is the primary feature |
| 10 · Human Oversight | ✅ PASS | Interactive confirmation required before overwriting existing hooks path config |
| 11 · Small Composable Scripts | ✅ PASS | `install.py` is a thin coordinator; hook scripts delegate to `scripts/` |
| 13 · Idempotent Workflows | ✅ PASS | Re-running on a configured system is a no-op (FR-008) |
| 14 · Observable Execution | ✅ PASS | Each action logged as taken or skipped; clear exit status |

**Gate result: PASS — no violations. Proceed to Phase 0.**

*Post-design re-check: See bottom of Phase 1 section.*

## Project Structure

### Documentation (this feature)

```text
specs/001-installer-setup/
├── plan.md              # This file
├── research.md          # Phase 0 output
├── data-model.md        # Phase 1 output
├── quickstart.md        # Phase 1 output
├── contracts/           # Phase 1 output
│   └── cli.md
└── tasks.md             # Phase 2 output (/speckit.tasks — not created here)
```

### Source Code (repository root)

```text
install.py               # Single-command installer entry point
.githooks/               # Versioned git hooks (core.hooksPath target)
│   post-commit          # Thin launcher → scripts/post-commit.sh
│   pre-push             # Thin launcher → scripts/pre-push.sh (optional)
│   post-merge           # Thin launcher → scripts/post-merge.sh (optional)
scripts/                 # Hook implementation logic (versioned)
│   post-commit.sh
│   pre-push.sh
│   post-merge.sh
logs/                    # Local runtime logs (gitignored)
.gitignore               # Excludes logs/, local state
```

**Structure Decision**: Single-project, flat layout. No `src/` wrapper needed for a standalone installer script. Hook logic lives in `scripts/` and is referenced by thin launchers in `.githooks/` — keeping hooks stable while logic evolves independently (Constitution §11).

## Phase 0: Research

*Findings consolidated in [research.md](./research.md)*

Resolved decisions:
- **Script type**: Standalone `install.py` (not pip-installable package)
- **Entry point**: `python install.py` (stdlib only — no uv needed to run the installer itself; uv is a checked prerequisite, not the runner)
- **Python floor**: 3.10 (3.8 EOL Oct 2024, 3.9 EOL Oct 2025)
- **Hooks directory**: `.githooks/` (conventional, signals VC intent, analogous to `.github/`)
- **Hook types**: `post-commit` (primary), `pre-push`, `post-merge` (placeholder stubs)
- **Error strategy**: Collect ALL prerequisite errors then exit once — no partial state
- **git config idempotency**: Read current value → skip if match, prompt if mismatch, set if unset

## Phase 1: Design

*See [data-model.md](./data-model.md), [contracts/cli.md](./contracts/cli.md), [quickstart.md](./quickstart.md)*

### Post-Design Constitution Re-check

| Principle | Re-assessment |
|-----------|--------------|
| 6 · Safe By Default | ✅ `exist_ok=True` on mkdir; chmod only if not already executable |
| 13 · Idempotent | ✅ Each step checks current state before acting |
| 14 · Observable | ✅ `[OK]`, `[SKIP]`, `[WARN]`, `[ERROR]` prefixes on each output line |

**Post-design gate: PASS.**

## Complexity Tracking

> No constitution violations — this section is empty by design.
