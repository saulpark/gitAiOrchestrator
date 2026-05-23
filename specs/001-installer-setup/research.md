# Research: Automated Install Flow

**Branch**: `001-installer-setup` | **Date**: 2026-04-10

---

## Decision: Script Type

**Decision**: Standalone `install.py` script invoked via `python install.py` (not a pip package, not `uv run`, not `setup.py`)
**Rationale**: Installers run before the environment is configured. A single file means a single command — no pip, no virtualenv activation, no bootstrapping paradox. `setup.py` is deprecated (PEP 517). Using `uv run install.py` would create a bootstrap paradox: uv must already be installed to run the installer, but the installer is responsible for *detecting* whether uv is installed. Since the script is pure stdlib, any Python 3.10+ on the machine runs it directly — uv is a checked prerequisite, not the runner.
**Alternatives considered**:
- `pip install -e .` — rejected: requires pip and a configured environment; overkill for a setup script
- Shell script (`install.sh`) — rejected: Python gives cleaner cross-platform version parsing and structured error handling; aligns with user intent from spec

---

## Decision: Python Minimum Version

**Decision**: Python 3.10+
**Rationale**: Python 3.8 reached EOL October 2024; 3.9 EOL October 2025. In 2026, 3.10 is the minimum still receiving security patches. `match` statements (3.10+) are not needed here, but the version floor is justified by EOL policy alone.
**Alternatives considered**:
- 3.8 — rejected: EOL'd
- 3.11+ — considered but 3.10 is sufficient and broadens compatibility on older LTS distros
- No floor check — rejected: silent failures on outdated Python are worse than an explicit message

---

## Decision: Git Minimum Version

**Decision**: Git 2.28+
**Rationale**: `core.hooksPath` was added in Git 2.9 (2016), but 2.28 introduced `init.defaultBranch` and is the modern baseline. More importantly, it is the oldest release still in active use on supported OS versions as of 2026. Checking for 2.28 catches meaningfully outdated installs.
**Alternatives considered**:
- Git 2.9 (first version with core.hooksPath) — rejected: too permissive; ancient versions have other issues
- No git version check — rejected: spec requires version validation (FR-002 implicit, FR-005 explicit)

---

## Decision: Hooks Directory Name

**Decision**: `.githooks/`
**Rationale**: Signals version-control intent (analogous to `.github/`), stays hidden from casual `ls`, and is widely recognized as the conventional name for versioned hook directories. Git itself uses `.githooks/` as an example in documentation.
**Alternatives considered**:
- `hooks/` — rejected: too generic; conflicts with other tooling conventions
- `githooks/` — viable second choice but lacks the dot-prefix convention
- `git-hooks/` — rejected: verbose with no advantage

---

## Decision: Hook Script Architecture

**Decision**: Thin launchers in `.githooks/` → logic in `scripts/`
**Rationale**: Keeps hook files stable (rarely need changing) while allowing hook logic to evolve in versioned scripts. Satisfies Constitution §11 (Small Composable Scripts). Pattern:
```sh
#!/bin/sh
exec "$(git rev-parse --show-toplevel)/scripts/post-commit.sh"
```
**Alternatives considered**:
- Logic in hook files directly — rejected: tight coupling; violates Constitution §11
- No hook stubs at install time — rejected: installer must leave the system ready to use (SC-001)

---

## Decision: Hook Types to Install

**Decision**: `post-commit` (primary), `pre-push` and `post-merge` (placeholder stubs)
**Rationale**: `post-commit` is the primary trigger for documentation updates after local commits. `pre-push` enables optional gating before remote pushes. `post-merge` catches documentation drift from incoming changes after `git pull`. `post-receive` and `post-push` are server-side hooks — not applicable client-side.
**Alternatives considered**:
- Only `post-commit` — too narrow; misses pull-based changes
- Server-side hooks — rejected: requires server access; out of scope for local installer

---

## Decision: Prerequisite Error Strategy

**Decision**: Collect all errors, exit once with full list
**Rationale**: Better UX — developer sees all missing tools in one run, not one per run. No partial state is created during the check phase. Aligns with FR-005 (actionable messages) and FR-006 (no changes on failure).
**Alternatives considered**:
- Fail on first error — rejected: forces multiple re-runs to discover all problems

---

## Decision: git config Idempotency Handling

**Decision**: Read → skip if already correct → prompt if mismatch → set if unset
**Rationale**: Satisfies FR-008 (detect already-configured) and FR-009 (warn before overwrite). Non-zero exit from `git config --get` means key is unset (not an error condition).

```python
result = subprocess.run(
    ["git", "config", "--local", "core.hooksPath"],
    capture_output=True, text=True
)
current = result.stdout.strip()
target = ".githooks"

if current == target:
    # Skip — already correct
elif current:
    # Warn and prompt before overwriting
else:
    # Set unconditionally
```
**Alternatives considered**:
- Always overwrite — rejected: violates FR-009 and Constitution §6
- Only skip if set, never prompt — rejected: silently breaks existing hook setups

---

## Decision: Directory Creation

**Decision**: `Path(dir).mkdir(parents=True, exist_ok=True)` — no destructive operations
**Rationale**: `exist_ok=True` makes the operation a no-op if directory exists. No content is modified. Unexpected content in existing directories is left untouched (edge case from spec).
**Alternatives considered**:
- Delete and recreate — rejected: destructive, violates Constitution §6

---

## Resolved: Prerequisites List

| Tool | Min Version | Check Command | Install Guidance |
|------|-------------|---------------|-----------------|
| git | 2.28 | `git --version` | https://git-scm.com/downloads |
| uv | any | `uv --version` | https://docs.astral.sh/uv/ |
| claude (Claude Code CLI) | any | `claude --version` | https://claude.ai/code |

Python itself is checked via `sys.version_info` at script start (before other imports).

---

## Resolved: Directories to Create

| Directory | Purpose | Versioned? |
|-----------|---------|------------|
| `.githooks/` | Versioned git hooks target | Yes |
| `scripts/` | Hook implementation logic | Yes |
| `logs/` | Local runtime output | No (gitignored) |
