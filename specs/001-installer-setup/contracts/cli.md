# CLI Contract: Automated Install Flow

**Branch**: `001-installer-setup` | **Date**: 2026-04-10

## Command

```
python install.py
```

Must be run from within the **git repository** (any subdirectory works; the script resolves the root via `git rev-parse --show-toplevel`).

---

## Arguments

No required arguments. No flags in v1.

---

## Environment

| Variable | Required | Description |
|----------|----------|-------------|
| `PATH` | Yes | Must include `git`, `uv`, `claude` |
| `GIT_DIR` | No | Must not be set to a non-standard value |

The script must be run inside a git repository (i.e., `git rev-parse --show-toplevel` must succeed).

---

## Exit Codes

| Code | Meaning |
|------|---------|
| `0` | Success — system is ready (either freshly configured or already configured) |
| `1` | Failure — prerequisites missing, aborted by user, or unexpected error |

---

## Standard Output

All output goes to **stdout**. Each line is prefixed with a status token:

| Prefix | Meaning |
|--------|---------|
| `[OK]` | Action completed successfully |
| `[SKIP]` | Action skipped — already in correct state |
| `[WARN]` | Non-fatal warning, user attention may be needed |
| `[ERROR]` | Fatal error — run will exit after all errors are listed |

**Example: successful fresh install**
```
[OK]   git 2.48.1 found (required: 2.28+)
[OK]   uv 0.6.12 found
[OK]   claude CLI found
[OK]   Created .githooks/
[OK]   Installed .githooks/post-commit
[OK]   Installed .githooks/pre-push
[OK]   Installed .githooks/post-merge
[OK]   Set git config core.hooksPath = .githooks
[OK]   Created scripts/
[OK]   Created logs/
[OK]   Updated .gitignore (added logs/)
[OK]   Installation complete. Run `git commit` to verify hooks fire.
```

**Example: already configured**
```
[SKIP] git 2.48.1 found (required: 2.28+)
[SKIP] uv 0.6.12 found
[SKIP] claude CLI found
[SKIP] .githooks/ already exists
[SKIP] .githooks/post-commit already installed
[SKIP] .githooks/pre-push already installed
[SKIP] .githooks/post-merge already installed
[SKIP] core.hooksPath already set to .githooks
[SKIP] scripts/ already exists
[SKIP] logs/ already exists
[SKIP] .gitignore already excludes logs/
[OK]   Already configured. Nothing to do.
```

**Example: prerequisite failure**
```
[OK]   git 2.48.1 found (required: 2.28+)
[ERROR] uv: not found in PATH
        Install: curl -LsSf https://astral.sh/uv/install.sh | sh
[ERROR] claude: not found in PATH
        Install: https://claude.ai/code
```
*(exits 1, no changes made)*

**Example: hooks path conflict**
```
[OK]   git 2.48.1 found
...
[WARN] core.hooksPath is currently set to 'custom-hooks'
       Overwrite with '.githooks'? [y/N]:
```
*(waits for stdin; 'N' or empty → exits 1 without changes)*

---

## Standard Error

Used only for unexpected runtime exceptions (stack traces). Normal flow output goes to stdout.

---

## Stdin

Read only when prompting for confirmation of an existing `core.hooksPath` overwrite. Expects `y` or `Y` to confirm; any other input (including empty) declines.

---

## Idempotency Contract

Running the command multiple times on the same repository state produces identical output (modulo `[OK]` → `[SKIP]` transitions) and makes no additional changes after the first successful run.
