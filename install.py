#!/usr/bin/env python3
"""
install.py — gitAiOrchestrator installer

Sets up git hooks, creates required directories, and validates prerequisites.

Feature 001. Install is nothing but git configuration: point core.hooksPath at
the versioned .githooks/ directory and make sure the scripts are executable.
No daemon, no service, nothing to keep running.

Two properties the whole file is built around:
  * idempotent — every step reports done/skipped and re-running changes nothing
  * all-or-nothing on prerequisites — every check runs and is reported before
    any change is made, so the user fixes their environment in one pass

Usage:
    python install.py [--skip-claude-check]

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

import argparse
import json
import os
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Literal

# The Claude checks reuse the bridge's confinement so "passes here" means
# "passes in the hooks" — one definition, not a copy (feature 011).
sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))
from claude_bridge import CONFINEMENT_ARGS, MIN_CLI_VERSION, _payload_error

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

# --- Data model -------------------------------------------------------------
# Checks and steps return values instead of printing-and-exiting, which is what
# lets main() collect a full report and keeps the pieces unit-testable.

@dataclass
class Prerequisite:
    """A tool that must be present, and how to check its version."""
    name: str
    command: str
    min_version: tuple[int, ...] | None
    version_flag: str
    install_url: str
    version_parse: Callable[[str], tuple[int, ...]] | None = None


@dataclass
class CheckResult:
    """Outcome of one prerequisite check: ok / missing / outdated."""
    prerequisite: Prerequisite
    status: Literal["ok", "missing", "outdated"]
    found_version: tuple[int, ...] | None
    message: str


@dataclass
class StepResult:
    """Outcome of one install step. "skipped" = already in the desired state."""
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
    """What to install, kept in one place rather than scattered as literals."""
    hooks_path: str
    dirs_to_create: list[str]
    hooks_to_install: list[str]
    scripts_to_chmod: list[str]


# ---------------------------------------------------------------------------
# Version parsers
# ---------------------------------------------------------------------------

def _parse_git_version(output: str) -> tuple[int, ...]:
    """First dotted numeric token from `git --version`.

    Version tuples compare directly (2, 39, 5) < (2, 48, 1), which is why the
    minimum is expressed as a tuple too. Distributions append suffixes like
    "(Apple Git-154)", so non-numeric segments are dropped rather than parsed.
    """
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

# min_version=None means presence-only: the tool is required, but any version
# will do. Every entry here is enforced — a missing one aborts the install.
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
        # 009: older CLIs lack the confinement flags, so every skill would end
        # as `unavailable`. Better to say so now than on every commit.
        min_version=MIN_CLI_VERSION,
        version_flag="--version",
        install_url="https://claude.ai/code",
        version_parse=_parse_semver,
    ),
]


def check_tool(prereq: Prerequisite) -> CheckResult:
    """Presence on PATH, then version when the prerequisite declares one."""
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


# The hooks do not run under the interpreter running this installer: they
# resolve their own (scripts/orchestrate.sh). On Windows `python3` is usually
# the Microsoft Store stub, so "this installer runs" proves nothing about the
# hooks. Same candidates, same order as the probe in orchestrate.sh.
HOOK_PYTHON_CANDIDATES: list[list[str]] = [["python3"], ["python"], ["py", "-3"]]
_HOOK_PYTHON_PROBE = "import sys; sys.exit(sys.version_info < (3, 10))"

HOOK_PYTHON = Prerequisite(
    name="python for hooks",
    command="python3 | python | py -3",
    min_version=(3, 10),
    version_flag="",
    install_url=(
        "https://www.python.org/downloads/ (on Windows, also disable the "
        "python/python3 App Execution Aliases in Settings)"
    ),
)


def _probe_python(argv: list[str]) -> bool:
    """True when argv runs a Python 3.10+. Missing or hung = not usable.

    The command is resolved through PATH explicitly, as the hook's shell does:
    on Windows, subprocess would otherwise find it in the running
    interpreter's own directory first and report a Python the hooks can't see.
    """
    resolved = shutil.which(argv[0])
    if resolved is None:
        return False
    try:
        result = subprocess.run(
            [resolved, *argv[1:], "-c", _HOOK_PYTHON_PROBE],
            capture_output=True, timeout=10, check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0


def check_hook_python(
    candidates: list[list[str]] = HOOK_PYTHON_CANDIDATES,
    probe: Callable[[list[str]], bool] = _probe_python,
) -> CheckResult:
    """The first candidate the hooks would pick, or "missing" if none works."""
    for argv in candidates:
        if probe(argv):
            return CheckResult(
                prerequisite=HOOK_PYTHON,
                status="ok",
                found_version=None,
                message=f"hooks will use '{' '.join(argv)}' (Python 3.10+)",
            )
    tried = ", ".join(" ".join(c) for c in candidates)
    return CheckResult(
        prerequisite=HOOK_PYTHON,
        status="missing",
        found_version=None,
        message=f"no working Python 3.10+ for the hooks (tried: {tried})",
    )


def run_checks(prerequisites: list[Prerequisite]) -> list[CheckResult]:
    """Check all prerequisites before making any changes. Never short-circuits."""
    return [check_tool(p) for p in prerequisites]


# ---------------------------------------------------------------------------
# Claude authentication for the hooks (feature 011)
# ---------------------------------------------------------------------------

# The hooks run Claude with --restricted, which ignores ~/.claude/settings.json
# — including its `env` block, where provider setups (Bedrock, Vertex, …) often
# live. `claude auth status` reads that file, so it says "logged in" while every
# skill fails with "Not logged in". These are the names worth reporting when
# they exist only in the settings file (Claude Code docs, 2026-10-02).
RELEVANT_ENV = frozenset({
    # providers
    "CLAUDE_CODE_USE_BEDROCK", "AWS_REGION", "AWS_DEFAULT_REGION", "AWS_PROFILE",
    "AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN",
    "AWS_BEARER_TOKEN_BEDROCK",
    "CLAUDE_CODE_USE_VERTEX", "CLOUD_ML_REGION", "ANTHROPIC_VERTEX_PROJECT_ID",
    "GOOGLE_APPLICATION_CREDENTIALS",
    "CLAUDE_CODE_USE_FOUNDRY", "ANTHROPIC_FOUNDRY_RESOURCE", "ANTHROPIC_FOUNDRY_BASE_URL",
    "ANTHROPIC_FOUNDRY_API_KEY", "ANTHROPIC_FOUNDRY_AUTH_TOKEN",
    # Anthropic API / gateways
    "ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_BASE_URL",
    "CLAUDE_CODE_OAUTH_TOKEN",
    # model pins (required on Foundry, optional elsewhere)
    "ANTHROPIC_MODEL", "ANTHROPIC_DEFAULT_OPUS_MODEL", "ANTHROPIC_DEFAULT_SONNET_MODEL",
    "ANTHROPIC_DEFAULT_HAIKU_MODEL",
    # network
    "HTTPS_PROXY", "HTTP_PROXY", "NO_PROXY", "https_proxy", "http_proxy", "no_proxy",
    "NODE_EXTRA_CA_CERTS", "CLAUDE_CODE_CERT_STORE", "CLAUDE_CODE_CLIENT_CERT",
    "CLAUDE_CODE_CLIENT_KEY", "CLAUDE_CODE_CLIENT_KEY_PASSPHRASE",
})
# Settings keys (not variables) that produce credentials. Under --restricted
# they are never run, and no environment variable can stand in for the key.
IGNORED_AUTH_SETTINGS = ("apiKeyHelper", "awsAuthRefresh", "awsCredentialExport")
CLAUDE_PROBE_PROMPT = "Reply with the single word OK."
CLAUDE_PROBE_TIMEOUT = 90


@dataclass
class ClaudeAuthResult:
    """Can the hooks' confined Claude answer? ok / failed / skipped."""
    status: Literal["ok", "failed", "skipped"]
    missing: list[str] = field(default_factory=list)   # names only, never values
    ignored: list[str] = field(default_factory=list)
    error: str = ""
    notes: list[str] = field(default_factory=list)


def user_settings_path(environ: dict) -> Path:
    base = environ.get("CLAUDE_CONFIG_DIR") or str(Path.home() / ".claude")
    return Path(base) / "settings.json"


def read_user_settings(path: Path) -> dict:
    """The user's Claude settings, or {} when missing/unreadable. Never raises."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def missing_env(settings: dict, environ: dict) -> list[str]:
    """Relevant names set in settings' `env` but absent from the environment.

    Pure. Only names are compared — values are never read out or printed.
    """
    env = settings.get("env")
    if not isinstance(env, dict):
        return []
    return sorted(n for n in env if n in RELEVANT_ENV and n not in environ)


def ignored_settings(settings: dict) -> list[str]:
    """Credential-producing settings keys the hooks will never run. Pure."""
    return [k for k in IGNORED_AUTH_SETTINGS if k in settings]


def _run_claude(argv: list[str], stdin: str, timeout: float) -> tuple[int, str, str]:
    proc = subprocess.run(argv, input=stdin, text=True, encoding="utf-8",
                          errors="replace", capture_output=True, timeout=timeout,
                          check=False)
    return proc.returncode, proc.stdout, proc.stderr


def probe_claude(command: str = "claude", run=_run_claude,
                 which=shutil.which) -> tuple[bool, str]:
    """One tiny Claude call under the hooks' exact confinement → (ok, error)."""
    resolved = which(command)
    if resolved is None:
        return False, f"'{command}' not found on PATH"
    argv = [resolved, "-p", "--output-format", "json", "--max-turns", "1",
            *CONFINEMENT_ARGS]
    try:
        rc, stdout, stderr = run(argv, CLAUDE_PROBE_PROMPT, CLAUDE_PROBE_TIMEOUT)
    except subprocess.TimeoutExpired:
        return False, f"no answer within {CLAUDE_PROBE_TIMEOUT}s"
    except OSError as exc:
        return False, f"could not start claude: {exc}"
    try:
        payload = json.loads(stdout)
    except ValueError:
        payload = None
    failed, error = _payload_error(payload)
    if rc != 0 or failed:
        return False, error or stderr.strip()[:300] or f"claude exited {rc}"
    return True, ""


def check_claude_auth(settings: dict, environ: dict, probe: Callable[[], tuple[bool, str]],
                      skip: bool = False) -> ClaudeAuthResult:
    """Combine the static settings check with the live probe.

    The live call decides: names missing from the environment are only the
    explanation. They can be harmless (a model pin, or a region the AWS
    profile already supplies), so a passing call with missing names is a note.
    """
    missing = missing_env(settings, environ)
    ignored = ignored_settings(settings)
    notes: list[str] = []
    if environ.get("CLAUDECODE"):
        notes.append("running inside a Claude Code session: the check may pass only "
                     "because of variables that session provides; re-run from a "
                     "normal terminal to be sure")
    if ignored:
        notes.append(f"settings key(s) {', '.join(ignored)} are not used by the hooks; "
                     "use environment-based credentials instead")
    if skip:
        if missing:
            notes.append("set only in ~/.claude/settings.json, so not seen by the hooks: "
                         + ", ".join(missing))
        return ClaudeAuthResult("skipped", missing, ignored, "", notes)

    ok, error = probe()
    if ok:
        if missing:
            notes.append("not applied to the hooks (Claude still works without them): "
                         + ", ".join(missing))
        return ClaudeAuthResult("ok", missing, ignored, "", notes)
    return ClaudeAuthResult("failed", missing, ignored, error, notes)


# ---------------------------------------------------------------------------
# Install steps
# ---------------------------------------------------------------------------

# The installed hook is a two-line shim that exec's the versioned script. That
# indirection is the point: scripts/ is committed and can change freely, while
# what git actually invokes never has to be reinstalled.
_HOOK_LAUNCHER = """\
#!/bin/sh
exec "$(git rev-parse --show-toplevel)/scripts/{name}.sh"
"""

# Only written when scripts/<name>.sh is absent (installing into a repo that
# does not carry them). A no-op stub keeps the hook chain valid until real
# logic is added; existing scripts are never overwritten.
_STUB_SCRIPT = """\
#!/bin/sh
# {name} hook — placeholder implementation
# Replace with actual logic
exit 0
"""


def create_directories(config: InstallConfig, repo_root: Path) -> list[StepResult]:
    """Create the directories the pipeline writes to. Existing ones = skipped."""
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
    """Write the .githooks/<event> shims and make them executable.

    An existing hook file is never rewritten — only chmod'ed if needed. A hook
    that exists but is not executable is silently ignored by git, which is the
    most common "why did nothing happen?" install problem.
    """
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
    """Ensure scripts/<event>.sh exists and is executable (stub if absent)."""
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
    """Point git at .githooks/ — the one setting that activates everything.

    --local only: never touch the user's global git config. If some other
    hooksPath is already configured, that is someone else's tooling, so ask
    before overwriting and treat a declined prompt (or no TTY) as an abort.
    """
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
    """Add an ignore entry if no equivalent form is already present.

    logs/ holds hook output and run records — local diagnostics that would
    otherwise show up as noise in every status and diff.
    """
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

def main(argv: list[str] | None = None) -> None:
    """Check everything, then change everything, then summarize."""
    parser = argparse.ArgumentParser(description="Install gitAiOrchestrator git hooks")
    parser.add_argument("--skip-claude-check", action="store_true",
                        help="skip the live Claude call (offline/CI installs)")
    args = parser.parse_args(argv)
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
    # All checks run before the first failure is reported, so the user sees
    # the complete list of what to install rather than one item at a time.
    checks = run_checks(PREREQUISITES) + [check_hook_python()]
    failures = [c for c in checks if c.status != "ok"]

    if failures:
        for c in failures:
            _error(f"{c.prerequisite.name}: {c.message}")
            print(f"        Install: {c.prerequisite.install_url}")
        sys.exit(1)

    for c in checks:
        _ok(c.message)

    # --- Claude must run the way the hooks run it (011) ---
    # Still before any change: a Claude the hooks cannot use aborts the install
    # just like a missing git.
    auth = check_claude_auth(read_user_settings(user_settings_path(os.environ)),
                             dict(os.environ), probe_claude,
                             skip=args.skip_claude_check)
    if auth.status == "failed":
        _error(f"Claude cannot run inside the git hooks: {auth.error}")
        if auth.missing:
            print("        These are set in ~/.claude/settings.json, which the hooks do not")
            print("        read. Set them as real environment variables (same values):")
            for name in auth.missing:
                print(f"          {name}")
        for note in auth.notes:
            print(f"        Note: {note}")
        print("        See TUTORIAL.md, section 1, 'Claude authentication for the hooks'.")
        print("        Offline/CI install: re-run with --skip-claude-check.")
        sys.exit(1)
    if auth.status == "ok":
        _ok("claude answers under the hooks' read-only confinement")
    else:
        _skip("live Claude check (--skip-claude-check)")
    for note in auth.notes:
        _warn(note)

    # --- Installation steps ---
    all_steps: list[StepResult] = []

    all_steps += create_directories(config, repo_root)
    all_steps += install_hooks(config, repo_root)
    all_steps += install_scripts(repo_root, config.hooks_to_install)

    hooks_path_result = configure_hooks_path(config.hooks_path, repo_root)
    all_steps.append(hooks_path_result)

    # Without hooksPath nothing is wired up, so a declined overwrite is fatal —
    # better a clear failure than an install that silently does nothing.
    if hooks_path_result.status == "failed":
        sys.exit(1)

    all_steps.append(update_gitignore("logs/", repo_root))

    # --- Summary ---
    # Everything skipped = a re-run on an already-configured repo (idempotency).
    if all(s.status == "skipped" for s in all_steps):
        _ok("Already configured. Nothing to do.")
    else:
        _ok("Installation complete. Run `git commit` to verify hooks fire.")


if __name__ == "__main__":
    main()
