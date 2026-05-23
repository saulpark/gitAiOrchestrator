# Quickstart: Automated Install Flow

**Branch**: `001-installer-setup` | **Date**: 2026-04-10

## Prerequisites

Before running the installer, ensure the following are installed:

| Tool | Minimum Version | Install |
|------|----------------|---------|
| git | 2.28 | https://git-scm.com/downloads |
| uv | any | `curl -LsSf https://astral.sh/uv/install.sh \| sh` |
| claude CLI | any | https://claude.ai/code |

Python 3.10+ must be installed separately and available as `python` or `python3` in your PATH. uv does not need to be installed to *run* the installer — it is checked as a prerequisite once the installer starts.

---

## Install

From inside the repository (root or any subdirectory):

```sh
python install.py
```

The installer will:
1. Validate all prerequisites
2. Configure `git config core.hooksPath = .githooks`
3. Create `.githooks/`, `scripts/`, and `logs/` directories
4. Install hook launcher scripts and make them executable
5. Add `logs/` to `.gitignore`
6. Report success

**Expected output on a clean machine:**
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

---

## Verify

Make a test commit to confirm the hooks are active:

```sh
echo "# test" >> README.md
git add README.md
git commit -m "test: verify hooks fire"
```

The `post-commit` hook should execute without errors.

---

## Re-running

Safe to run again at any time. The installer detects the existing configuration and skips all steps that are already correct:

```sh
python install.py
# [SKIP] ... Already configured. Nothing to do.
```

---

## Troubleshooting

**`uv: not found`** — Install uv first: `curl -LsSf https://astral.sh/uv/install.sh | sh`

**`claude: not found`** — Install Claude Code CLI: https://claude.ai/code

**`git` version too old** — Update git: https://git-scm.com/downloads

**`core.hooksPath` already set to a different value** — The installer will prompt before overwriting. Answer `y` to switch to `.githooks`, or `N` to abort and manually resolve the conflict.

**Not in a git repository** — Run the command from the repository root (where `.git/` is located).
