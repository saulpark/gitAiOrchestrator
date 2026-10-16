# Quickstart: Declarative AI Skills (009)

This describes the target behavior. It works once tasks.md is implemented.

## 1. Write a skill: two files, no code

```text
skills/todo-check/skill.json
{"name": "todo-check", "version": "1.0.0",
 "description": "Fails when staged files contain TODO-BLOCK",
 "input": "hook-context@1.0", "time_budget_seconds": 45}

skills/todo-check/prompt.md
Check each changed file for the marker TODO-BLOCK.
verdict "fail" if any file contains it (list file and line in the report), else "pass".
```

```sh
python src/skill_registry.py register skills/todo-check
```

## 2. Route it and pick a mode (`config/routes.json`)

```json
{"version": "2.0",
 "routes": {"pre-commit": ["todo-check"]},
 "skills": {"todo-check": {"mode": "sync", "on_failure": "block"}},
 "sync_ceiling_seconds": 120}
```

Leave `skills.todo-check` out entirely to get the default: async, never blocks.

## 3. Use git normally

```sh
git commit -m "x"          # silent unless todo-check says fail
ls _aioutput/todo-check/   # 20261002T101530Z-pre-commit.md ...
python src/run_records.py show --last
tail logs/hooks.log
```

## What Claude can do in a skill

Only Read, Grep and Glob, inside the repository. It cannot write, edit, delete, run
commands, use the web or MCP, or be widened by any Claude settings file. The result file is
written by the framework from what Claude returns.
