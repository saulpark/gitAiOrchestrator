#!/usr/bin/env python3
"""
install.py — gitAiOrchestrator installer

Sets up git hooks, creates required directories, and validates prerequisites.

Usage:
    python install.py

Must be run from inside the target git repository (any subdirectory works).
"""
import sys

# Python version guard — must be before any other imports
if sys.version_info < (3, 10):
    sys.exit(
        f"Error: Python 3.10+ required "
        f"(found {sys.version_info.major}.{sys.version_info.minor}). "
        "See https://www.python.org/downloads/"
    )

import os
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Literal


# ---------------------------------------------------------------------------
# Output helpers
# ---------------------------------------------------------------------------

def _ok(msg: str) -> None:
    print(f"[OK]   {msg}")


def _skip(msg: str) -> None:
    print(f"[SKIP] {msg}")


def _warn(msg: str) -> None:
    print(f"[WARN] {msg}")


def _error(msg: str) -> None:
    print(f"[ERROR] {msg}")


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class Prerequisite:
    name: str
    command: str
    min_version: tuple[int, ...] | None
    version_flag: str
    install_url: str
    version_parse: Callable[[str], tuple[int, ...]] | None = None


@dataclass
class CheckResult:
    prerequisite: Prerequisite
    status: Literal["ok", "missing", "outdated"]
    found_version: tuple[int, ...] | None
    message: str


@dataclass
class StepResult:
    action: str
    status: Literal["done", "skipped", "warned", "failed"]
    detail: str | None = None


@dataclass
class InstallResult:
    outcome: Literal["success", "already_configured", "failure", "aborted"]
    steps: list[StepResult] = field(default_factory=list)
    errors: list[CheckResult] = field(default_factory=list)


@dataclass
class InstallConfig:
    hooks_path: str
    dirs_to_create: list[str]
    hooks_to_install: list[str]
    scripts_to_chmod: list[str]


# ---------------------------------------------------------------------------
# Version parsers
# ---------------------------------------------------------------------------

def _parse_git_version(output: str) -> tuple[int, ...]:
    # "git version 2.48.1" → (2, 48, 1)
    for token in output.strip().split():
        if "." not in token:
            continue
        segments = token.split(".")
        try:
            parsed = tuple(int(s) for s in segments if s.isdigit())
            if parsed:
                return parsed
        except ValueError:
            continue
    return (0,)


def _parse_semver(output: str) -> tuple[int, ...]:
    match = re.search(r"(\d+)\.(\d+)(?:\.(\d+))?", output)
    if match:
        return tuple(int(g) for g in match.groups() if g is not None)
    return (0,)


# ---------------------------------------------------------------------------
# Prerequisites
# ---------------------------------------------------------------------------

PREREQUISITES: list[Prerequisite] = [
    Prerequisite(
        name="git",
        command="git",
        min_version=(2, 28),
        version_flag="--version",
        install_url="https://git-scm.com/downloads",
        version_parse=_parse_git_version,
    ),
    Prerequisite(
        name="uv",
        command="uv",
        min_version=None,
        version_flag="--version",
        install_url="https://docs.astral.sh/uv/",
    ),
    Prerequisite(
        name="claude CLI",
        command="claude",
        min_version=None,
        version_flag="--version",
        install_url="https://claude.ai/code",
    ),
]


def check_tool(prereq: Prerequisite) -> CheckResult:
    if not shutil.which(prereq.command):
        return CheckResult(
            prerequisite=prereq,
            status="missing",
            found_version=None,
            message=f"'{prereq.command}' not found in PATH",
        )

    if prereq.min_version is not None and prereq.version_parse is not None:
        result = subprocess.run(
            [prereq.command, prereq.version_flag],
            capture_output=True,
            text=True,
        )
        raw = result.stdout or result.stderr
        found = prereq.version_parse(raw)
        required_str = ".".join(str(x) for x in prereq.min_version)
        actual_str = ".".join(str(x) for x in found)

        if found < prereq.min_version:
            return CheckResult(
                prerequisite=prereq,
                status="outdated",
                found_version=found,
                message=(
                    f"{prereq.name} {actual_str} found, "
                    f"{required_str}+ required"
                ),
            )

        return CheckResult(
            prerequisite=prereq,
            status="ok",
            found_version=found,
            message=f"{prereq.name} {actual_str} found (required: {required_str}+)",
        )

    return CheckResult(
        prerequisite=prereq,
        status="ok",
        found_version=None,
        message=f"{prereq.name} found",
    )


def run_checks(prerequisites: list[Prerequisite]) -> list[CheckResult]:
    """Check all prerequisites before making any changes. Never short-circuits."""
    return [check_tool(p) for p in prerequisites]


# ---------------------------------------------------------------------------
# Install steps
# ---------------------------------------------------------------------------

_HOOK_LAUNCHER = """\
#!/bin/sh
exec "$(git rev-parse --show-toplevel)/scripts/{name}.sh"
"""

_STUB_SCRIPT = """\
#!/bin/sh
# {name} hook — placeholder implementation
# Replace with actual logic
exit 0
"""


def create_directories(config: InstallConfig, repo_root: Path) -> list[StepResult]:
    results = []
    for d in config.dirs_to_create:
        path = repo_root / d
        if path.exists():
            _skip(f"{d}/ already exists")
            results.append(StepResult(action=f"Create {d}/", status="skipped"))
        else:
            path.mkdir(parents=True, exist_ok=True)
            _ok(f"Created {d}/")
            results.append(StepResult(action=f"Create {d}/", status="done"))
    return results


def install_hooks(config: InstallConfig, repo_root: Path) -> list[StepResult]:
    results = []
    hooks_dir = repo_root / config.hooks_path

    for hook_name in config.hooks_to_install:
        hook_path = hooks_dir / hook_name
        rel = f"{config.hooks_path}/{hook_name}"

        if hook_path.exists():
            if os.access(hook_path, os.X_OK):
                _skip(f"{rel} already installed")
                results.append(StepResult(action=f"Install {hook_name}", status="skipped"))
            else:
                os.chmod(hook_path, 0o755)
                _ok(f"Made {rel} executable")
                results.append(StepResult(action=f"Install {hook_name}", status="done"))
        else:
            hook_path.write_text(_HOOK_LAUNCHER.format(name=hook_name))
            os.chmod(hook_path, 0o755)
            _ok(f"Installed {rel}")
            results.append(StepResult(action=f"Install {hook_name}", status="done"))

    return results


def install_scripts(repo_root: Path, hook_names: list[str]) -> list[StepResult]:
    results = []
    scripts_dir = repo_root / "scripts"

    for name in hook_names:
        script_path = scripts_dir / f"{name}.sh"
        rel = f"scripts/{name}.sh"

        if script_path.exists():
            if not os.access(script_path, os.X_OK):
                os.chmod(script_path, 0o755)
            _skip(f"{rel} already exists")
            results.append(StepResult(action=f"Install {rel}", status="skipped"))
        else:
            script_path.write_text(_STUB_SCRIPT.format(name=name))
            os.chmod(script_path, 0o755)
            _ok(f"Created {rel}")
            results.append(StepResult(action=f"Install {rel}", status="done"))

    return results


def configure_hooks_path(target: str, repo_root: Path) -> StepResult:
    result = subprocess.run(
        ["git", "config", "--local", "core.hooksPath"],
        capture_output=True,
        text=True,
        cwd=repo_root,
    )
    current = result.stdout.strip()

    if current == target:
        _skip(f"core.hooksPath already set to {target}")
        return StepResult(action="Set core.hooksPath", status="skipped")

    if current:
        _warn(f"core.hooksPath is currently set to '{current}'")
        try:
            answer = input(f"       Overwrite with '{target}'? [y/N]: ")
        except EOFError:
            answer = ""
        if answer.lower() != "y":
            _error("Aborted.")
            return StepResult(
                action="Set core.hooksPath",
                status="failed",
                detail="User declined overwrite",
            )

    subprocess.run(
        ["git", "config", "--local", "core.hooksPath", target],
        check=True,
        cwd=repo_root,
    )
    _ok(f"Set git config core.hooksPath = {target}")
    return StepResult(action="Set core.hooksPath", status="done")


def update_gitignore(entry: str, repo_root: Path) -> StepResult:
    gitignore = repo_root / ".gitignore"
    normalized = entry.rstrip("/")

    if gitignore.exists():
        content = gitignore.read_text()
        for line in content.splitlines():
            stripped = line.strip()
            if stripped in (entry, normalized, f"/{entry}", f"/{normalized}"):
                _skip(f".gitignore already excludes {entry}")
                return StepResult(
                    action=f"Update .gitignore ({entry})", status="skipped"
                )
        gitignore.write_text(content.rstrip("\n") + f"\n{entry}\n")
    else:
        gitignore.write_text(f"{entry}\n")

    _ok(f"Updated .gitignore (added {entry})")
    return StepResult(action=f"Update .gitignore ({entry})", status="done")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    # Not-in-git-repo guard
    result = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        _error("Not inside a git repository. Run from the repo root.")
        sys.exit(1)

    repo_root = Path(result.stdout.strip())

    config = InstallConfig(
        hooks_path=".githooks",
        dirs_to_create=[".githooks", "scripts", "logs"],
        hooks_to_install=["pre-commit", "pre-push", "post-merge"],
        scripts_to_chmod=[],
    )

    # --- Prerequisite checks (collect all before exiting) ---
    checks = run_checks(PREREQUISITES)
    failures = [c for c in checks if c.status != "ok"]

    if failures:
        for c in failures:
            _error(f"{c.prerequisite.name}: {c.message}")
            print(f"        Install: {c.prerequisite.install_url}")
        sys.exit(1)

    for c in checks:
        _ok(c.message)

    # --- Installation steps ---
    all_steps: list[StepResult] = []

    all_steps += create_directories(config, repo_root)
    all_steps += install_hooks(config, repo_root)
    all_steps += install_scripts(repo_root, config.hooks_to_install)

    hooks_path_result = configure_hooks_path(config.hooks_path, repo_root)
    all_steps.append(hooks_path_result)

    if hooks_path_result.status == "failed":
        sys.exit(1)

    all_steps.append(update_gitignore("logs/", repo_root))

    # --- Summary ---
    if all(s.status == "skipped" for s in all_steps):
        _ok("Already configured. Nothing to do.")
    else:
        _ok("Installation complete. Run `git commit` to verify hooks fire.")


if __name__ == "__main__":
    main()
