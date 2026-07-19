# Research: Claude Code Bridge

**Branch**: `007-claude-code-bridge` | **Date**: 2026-07-19

---

## Decision: Headless Invocation — `claude -p --output-format json`

**Decision**: The bridge invokes the `claude` CLI in non-interactive print mode:
`claude -p <prompt> --output-format json --max-turns <n>`, cwd = repo root.
**Rationale**: Print mode is Claude Code's supported automation surface; JSON output gives
the skill a structured payload (`result`, `is_error`, cost/usage metadata). `--max-turns`
bounds agentic loops inside a hook-triggered run.
**Alternatives considered**:
- Anthropic API directly — rejected: bypasses Claude Code settings/CLAUDE.md (violates
  FR-004) and adds a dependency + key management
- Interactive session driving — rejected: not automatable, fragile

---

## Decision: Settings Inheritance via Working Directory (FR-004/SC-002)

**Decision**: The bridge runs `claude` with cwd = repository root and passes **no**
settings overrides by default. Claude Code then reads the project's own
`.claude/settings.json`, `CLAUDE.md`, etc. from their standard locations.
**Rationale**: Zero duplication — the same configuration governs interactive and automated
use, and configuration changes take effect on the next invocation with no sync step.
**Alternatives considered**:
- Copying settings into a bridge-owned file — rejected: the duplication FR-004 forbids

---

## Decision: Claude Code Hook Toggle (FR-006/007)

**Decision**: `config/bridge.json` has `hooks_enabled` (default `false`). When false, the
bridge adds `--settings '{"disableAllHooks": true}'` to the claude argv — Claude Code's
supported switch for suppressing its own hooks for that invocation. When true, no override
is passed and the project's configured Claude Code hooks fire normally.
**Rationale**: A single config key toggles the behavior per invocation (SC-004); the
project's hook definitions stay in Claude Code settings where they belong — the bridge
never duplicates them.

---

## Decision: Bounded Prompt Construction (FR-002/SC-005)

**Decision**: The prompt contains: event, branch, changed file list, commit list, the
skill's `task` text, and an explicit constraint: *"Only examine the files listed above.
Do not scan or enumerate the rest of the repository."* Partial contexts are flagged in the
prompt (`context is partial: missing <fields>`), and an empty change set is stated
explicitly so Claude Code does not go looking for work.
**Rationale**: The hook context is the single source (003); the constraint sentence is the
cheapest effective guard against full-repo scans while keeping read access for the listed
files. Tool-level allowlists vary by Claude Code version and belong in project settings if
the project wants them (which the bridge inherits automatically).

---

## Decision: Availability & Failure Containment (FR-005/SC-003)

**Decision**: `shutil.which(config["claude_command"])` before invocation → structured
`unavailable` result. Non-zero exit → `error` with stderr excerpt. `subprocess` timeout
(config `timeout_seconds`, default 120) → `timeout`. All paths return a BridgeResult and
exit 0; the calling skill decides what its own status becomes.
**Note**: The 006 executor's per-skill budget still applies to the whole skill; a skill
calling the bridge should declare a `time_budget_seconds` ≥ the bridge timeout.

---

## Decision: Testability (FR-008)

**Decision**: Core function `invoke(request, config, runner=None)`; `runner(argv, prompt,
timeout)` is injectable — tests pass fakes. CLI tests additionally use fake `claude`
executables placed first on PATH to exercise argv construction end-to-end.
**Decision**: No caching, no module-level mutable state — each invocation builds its own
argv and result (spec assumption on concurrency safety).
