# Tasks: Claude Code Bridge

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** One shared, testable component through which any skill calls Claude Code with a bounded context, project settings applied, structured results, opt-in hooks.

**Architecture:** `invoke(request, config, runner=None)` pure-ish core with injectable runner; `build_prompt(context, task)`; tolerant `load_bridge_config`; CLI stdin→stdout; `config/bridge.json`.

**Tech Stack:** Python 3.10+ stdlib, pytest (fake claude executables), ruff.

## Global Constraints

- Exit 0 always; every failure mode is a structured status (SC-003)
- Prompt bounded to hook-context data + task + constraint sentence (FR-002/SC-005)
- No settings duplication — cwd inheritance only (FR-004); `hooks_enabled` is the only toggle (FR-006/007)
- No caching, no shared mutable state

---

## Task 1: Prompt + config + core invoke with injectable runner

**Files:** Create `src/claude_bridge.py`, `tests/test_claude_bridge.py`, `config/bridge.json`

**Interfaces produced:** `REQUEST_SCHEMA_VERSION/RESULT_SCHEMA_VERSION = "1.0"`; `DEFAULT_CONFIG` dict; `load_bridge_config(path, warnings) -> dict`; `build_prompt(context, task) -> str`; `invoke(request, config, runner=None) -> dict`

- [ ] **Step 1: Failing tests** — prompt contains event/branch/files/commits/task + constraint sentence; partial context noted; empty change set stated; bad request (missing task/context) → `bad-request`; runner fake: argv has `-p`, `--output-format json`, `--max-turns`; hooks_enabled false → `--settings {"disableAllHooks": true}` present, true → absent; options overrides (max_turns, timeout); ok path parses claude JSON into `output` + `output_text`; non-zero exit → `error` with stderr; runner raising TimeoutExpired → `timeout`; config tolerant load (missing/malformed → defaults + warning)
- [ ] **Step 2: Verify fail**
- [ ] **Step 3: Implement**
- [ ] **Step 4: Verify pass**
- [ ] **Step 5: Commit** — `feat(007): bridge core — bounded prompt, config, structured results`

## Task 2: Availability detection + real subprocess runner + CLI

**Files:** Modify `src/claude_bridge.py`; extend tests

- [ ] **Step 1: Failing tests** — `claude_command` not on PATH → `unavailable` without running anything; CLI with fake `claude` first on PATH: request stdin → result stdout exit 0, fake receives prompt via `-p` argv and its JSON lands in `output`; fake exits 7 → `error`, exit 0; fake sleeps past `options.timeout_seconds: 1` → `timeout`, exit 0; garbage stdin → `bad-request`, exit 0
- [ ] **Step 2: Verify fail**
- [ ] **Step 3: Implement** default runner (`subprocess.run`, cwd stays caller's), `which` gate, `main()`
- [ ] **Step 4: Verify pass + ruff**
- [ ] **Step 5: Commit** — `feat(007): bridge CLI with availability detection and timeouts`

## Task 3: E2E + docs sync + finish

- [ ] **Step 1: E2E (fake claude)** — author a `summarize` skill that pipes context→bridge→skill-result, register it, route on pre-commit with fake claude on PATH, real commit → `invoked=1`, bridge output in skill result; toggle `hooks_enabled` and verify argv change (SC-004); clean up
- [ ] **Step 2: E2E (real claude, if installed)** — one direct bridge call with task "Reply with the single word OK." and `max_turns: 1`; record status
- [ ] **Step 3: Sync CLAUDE.md; check off tasks.md; full suite + ruff; commit, push, PR**
