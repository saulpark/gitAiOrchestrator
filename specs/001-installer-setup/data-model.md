# Data Model: Automated Install Flow

**Branch**: `001-installer-setup` | **Date**: 2026-04-10

This installer operates on in-memory data structures and produces filesystem/git-config side effects. There is no persistent database or serialized state format.

---

## Entity: Prerequisite

A required external tool that must be present and meet a minimum version.

| Field | Type | Description |
|-------|------|-------------|
| `name` | `str` | Display name (e.g., `"git"`, `"uv"`, `"claude"`) |
| `command` | `str` | Shell command to locate the tool (e.g., `"git"`) |
| `min_version` | `tuple[int, ...] \| None` | Minimum acceptable version tuple; `None` means any version |
| `version_flag` | `str` | Flag passed to get version string (e.g., `"--version"`) |
| `version_parse` | `Callable[[str], tuple[int, ...]]` | Parses raw version output to a comparable tuple |
| `install_url` | `str` | URL or command to guide installation |

**Validation rules**:
- `command` must be non-empty
- If `min_version` is set, `version_parse` must be provided
- Version comparison: actual tuple must be `>= min_version` (lexicographic)

**State transitions**: Prerequisite has no lifecycle state — it is checked once per run.

---

## Entity: CheckResult

The outcome of evaluating a single Prerequisite.

| Field | Type | Description |
|-------|------|-------------|
| `prerequisite` | `Prerequisite` | The prerequisite that was evaluated |
| `status` | `Literal["ok", "missing", "outdated"]` | Outcome |
| `found_version` | `tuple[int, ...] \| None` | Actual version found; `None` if missing |
| `message` | `str` | Human-readable message for this result |

---

## Entity: InstallConfig

The set of repository changes the installer manages.

| Field | Type | Description |
|-------|------|-------------|
| `hooks_path` | `str` | Target value for `git config core.hooksPath` (e.g., `".githooks"`) |
| `dirs_to_create` | `list[str]` | Paths relative to repo root to create if absent |
| `hooks_to_install` | `list[str]` | Hook filenames to write to `hooks_path/` |
| `scripts_to_chmod` | `list[str]` | Paths to ensure are executable after creation |

**Validation rules**:
- `hooks_path` must be a relative path (not absolute, not `.git/hooks`)
- All `dirs_to_create` paths must be relative

---

## Entity: StepResult

The outcome of a single install action.

| Field | Type | Description |
|-------|------|-------------|
| `action` | `str` | Human-readable description (e.g., `"Set core.hooksPath"`) |
| `status` | `Literal["done", "skipped", "warned", "failed"]` | Outcome |
| `detail` | `str \| None` | Optional additional detail |

---

## Entity: InstallResult

The aggregate outcome of a complete installer run.

| Field | Type | Description |
|-------|------|-------------|
| `outcome` | `Literal["success", "already_configured", "failure", "aborted"]` | Top-level result |
| `steps` | `list[StepResult]` | Ordered log of each action taken or skipped |
| `errors` | `list[CheckResult]` | Failed prerequisite checks (empty on success) |

**State transitions**:

```
START
  └─> check prerequisites
        ├─> any failures? → outcome = "failure", print errors, exit 1
        └─> all pass
              └─> configure
                    ├─> all already correct? → outcome = "already_configured", exit 0
                    ├─> user aborts overwrite prompt? → outcome = "aborted", exit 1
                    └─> changes applied? → outcome = "success", exit 0
```

---

## Filesystem Side Effects (not persisted entities)

| Path | Operation | Condition |
|------|-----------|-----------|
| `.githooks/` | `mkdir` | Always (idempotent) |
| `.githooks/post-commit` | Write thin launcher script | If not present |
| `.githooks/pre-push` | Write thin launcher script | If not present |
| `.githooks/post-merge` | Write thin launcher script | If not present |
| `.githooks/*` | `chmod +x` | If not already executable |
| `scripts/` | `mkdir` | Always (idempotent) |
| `logs/` | `mkdir` | Always (idempotent) |
| `.gitignore` | Append `logs/` entry | If not already present |
| `git config core.hooksPath` | Write `.githooks` | If unset or after confirmation |
