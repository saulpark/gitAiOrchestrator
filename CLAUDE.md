# gitAiOrchestrator Development Guidelines

Auto-generated from all feature plans. Last updated: 2026-10-02

## Active Technologies
- POSIX sh (`#!/bin/sh`) — no bash-isms; CI and interactive terminal compatible + git (already required by 001); no external packages (002-git-hook-scripts)
- N/A — logs written to `logs/hooks.log` (002-git-hook-scripts)
- Python 3.10+ stdlib (`json`, `os`, `re`, `sys`) at runtime; pytest + ruff dev-only via `.venv` (003-hook-context-parser)
- Routing config `config/routes.json` (JSON, schema v1.0); router `src/route_workflows.py` (004-workflow-router)
- Skill contract v1.1 (`specs/005-skill-contract/contracts/skill-contract.md`, superseded by 009 v2.0); registry `skills/registry.json` via `src/skill_registry.py` register/deregister/resolve/list/validate (005-skill-contract)
- Executor `src/execute_skills.py` (execution-summary@1.0; default 30 s budget, manifest `time_budget_seconds` override) (006-skill-executor)
- Claude bridge `src/claude_bridge.py` (bridge-request/result@1.0; `config/bridge.json`; headless `claude -p --output-format json`, cwd settings inheritance, `hooks_enabled` toggle) (007-claude-code-bridge)
- Observability `src/run_records.py` (run-record@1.0 in `logs/runs/`, `list`/`show --last` CLI); outcome rules in routes v1.1 (`outcomes.<skill>.on_failure: block|warn|skip`, default warn); block = router exit 10 → hook exit 1 (008-run-observability)
- Declarative skills + `_aioutput/` (009): skill = `skill.json` + `prompt.md` (contract v2.0, `specs/009-aioutput-skills/contracts/skill-contract.md`, no executable files); Claude runs read-only (`--restricted --tools Read,Grep,Glob ...`, CLI >= 2.1.287) and returns `{verdict, reason, report}`; framework writes `_aioutput/<skill>/<stamp>-<event>.md` via `src/ai_output.py`; per-skill `mode: sync|async` in routes v2.0 (`skills.<name>`), async via detached `src/async_worker.py`; only sync `failure` + `on_failure: block` blocks; terminal silent except `[hook blocked]`; `HOOK_CEILING_SECONDS=610` (009-aioutput-skills)
- Repo-wide read context (010): Claude may read the whole repository (change set = focus); bridge request optional `root` → Claude's cwd; `max_turns` default 20; constitution principles 1/3/8 amended (`specs/010-repo-wide-context/plan.md`)
- Installer Claude check (011): `install.py` requires claude CLI >= 2.1.287 and verifies hook-style auth (static settings-env name check + live confined call, `--skip-claude-check`); aborts with the missing variable names (`specs/011-installer-claude-check/plan.md`)

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
- 012-hidden-claude-window: `claude_bridge.hidden_window_kwargs` — the claude child gets `CREATE_NO_WINDOW` on Windows, so async runs open no console window that can be closed by accident
- fix-windows-timeout: `scripts/lib.sh` `_gnu_timeout` — hooks ignore a non-GNU `timeout` (Windows `System32\timeout.exe`) and use the POSIX watchdog
- 011-installer-claude-check: install.py aborts unless Claude runs under the hooks' `--restricted` confinement; TUTORIAL §1 lists the necessary env vars per provider
- 010-repo-wide-context: Skills read the whole repository (read-only unchanged); bridge pins cwd to repo root; `max_turns` 6 → 20; constitution amended
- 009-aioutput-skills: Skills are prompts; Claude read-only; results in `_aioutput/` (`src/ai_output.py`); sync/async modes + `src/async_worker.py`; routes v2.0, bridge 2.0, run-record 1.1, DispatchResult 2.0; warnings to `logs/hooks.log`
- 008-run-observability: Added `src/run_records.py` — run records, history CLI, block/warn/skip outcome enforcement; hooks propagate exit-10 blocks
- 007-claude-code-bridge: Added `src/claude_bridge.py` + `config/bridge.json` — shared bounded-context Claude Code invocation for skills
- 006-skill-executor: Added `src/execute_skills.py` (ordered execution, time budgets, ExecutionSummary); router delegates execution; contract v1.1 optional `time_budget_seconds`
- 005-skill-contract: Added skill contract v1.0 + `src/skill_registry.py`; router resolves skills through `skills/registry.json`
- 004-workflow-router: Added `src/route_workflows.py` + `config/routes.json`; orchestrate.sh now runs parse→route pipeline
- 003-hook-context-parser: Added `src/parse_context.py` (env → JSON context, schema v1.0); `HOOK_COMMITS` added to hook contract (pre-push)
- 002-git-hook-scripts: Added POSIX sh (`#!/bin/sh`) — no bash-isms; CI and interactive terminal compatible + git (already required by 001); no external packages

- 001-installer-setup: Added Python 3.10+ + stdlib only (`subprocess`, `shutil`, `pathlib`, `sys`) — no third-party packages required

<!-- MANUAL ADDITIONS START -->
<!-- MANUAL ADDITIONS END -->
