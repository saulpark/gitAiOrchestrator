# gitAiOrchestrator Development Guidelines

Auto-generated from all feature plans. Last updated: 2026-05-23

## Active Technologies
- POSIX sh (`#!/bin/sh`) — no bash-isms; CI and interactive terminal compatible + git (already required by 001); no external packages (002-git-hook-scripts)
- N/A — logs written to `logs/hooks.log` (002-git-hook-scripts)
- Python 3.10+ stdlib (`json`, `os`, `re`, `sys`) at runtime; pytest + ruff dev-only via `.venv` (003-hook-context-parser)
- Routing config `config/routes.json` (JSON, schema v1.0); router `src/route_workflows.py` (004-workflow-router)
- Skill contract v1.0 (`specs/005-skill-contract/contracts/skill-contract.md`); registry `skills/registry.json` via `src/skill_registry.py` register/deregister/resolve/list/validate (005-skill-contract)

- Python 3.10+ + stdlib only (`subprocess`, `shutil`, `pathlib`, `sys`) — no third-party packages required (001-installer-setup)

## Project Structure

```text
src/
tests/
```

## Commands

cd src && pytest && ruff check .

## Code Style

Python 3.10+: Follow standard conventions

## Recent Changes
- 005-skill-contract: Added skill contract v1.0 + `src/skill_registry.py`; router resolves skills through `skills/registry.json`
- 004-workflow-router: Added `src/route_workflows.py` + `config/routes.json`; orchestrate.sh now runs parse→route pipeline
- 003-hook-context-parser: Added `src/parse_context.py` (env → JSON context, schema v1.0); `HOOK_COMMITS` added to hook contract (pre-push)
- 002-git-hook-scripts: Added POSIX sh (`#!/bin/sh`) — no bash-isms; CI and interactive terminal compatible + git (already required by 001); no external packages

- 001-installer-setup: Added Python 3.10+ + stdlib only (`subprocess`, `shutil`, `pathlib`, `sys`) — no third-party packages required

<!-- MANUAL ADDITIONS START -->
<!-- MANUAL ADDITIONS END -->
