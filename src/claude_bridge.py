#!/usr/bin/env python3
"""Claude Code bridge (feature 007, confined read-only since 009).

The single component that invokes Claude Code. Builds a prompt from the hook
context (the change set as the run's focus; since 010 the whole repository is
readable) plus a skill's prompt, runs the claude CLI headless in a read-only
session rooted at the repository, and returns Claude's structured
verdict + report as a BridgeResult. Claude cannot modify the project: the
session only has Read/Grep/Glob, ignores every Claude settings file, and has
no hooks or MCP servers — the framework, not Claude, writes the result file.
Never raises. Contracts: specs/007-claude-code-bridge/contracts/bridge-interface.md,
specs/009-aioutput-skills/contracts/execution-and-output.md,
specs/010-repo-wide-context/plan.md
"""
from __future__ import annotations

import argparse
import functools
import json
import os
import re
import shutil
import subprocess
import sys
import time

REQUEST_SCHEMA_VERSION = "2.0"
RESULT_SCHEMA_VERSION = "2.0"
DEFAULT_CONFIG_PATH = "config/bridge.json"
# Defaults also define the expected type of every config key: load_bridge_config
# validates config/bridge.json against these, so a bad value degrades instead of
# reaching the CLI invocation. Deliberately no key can add CLI arguments.
DEFAULT_CONFIG = {
    "version": "2.0",
    "claude_command": "claude",
    "model": "",              # "" = the CLI's default model
    "max_turns": 20,          # bounded agentic turns; repo-wide reading needs room (010)
    "timeout_seconds": 120,
}
# 007 keys that could weaken the confinement; read and refused, never honored.
REMOVED_KEYS = ("hooks_enabled", "extra_args")

# The read-only session (feature 009, verified in the T0 spike). Not
# configurable: --restricted ignores user/project/local settings and drops
# code-running tools, --tools is the allowlist of tools that exist at all,
# --strict-mcp-config with no --mcp-config means no MCP servers, and nobody
# can answer a permission prompt inside a git hook.
READ_ONLY_TOOLS = "Read,Grep,Glob"
CONFINEMENT_ARGS = (
    "--restricted",
    "--tools", READ_ONLY_TOOLS,
    "--strict-mcp-config",
    "--permission-prompts", "none",
    "--settings", json.dumps({"disableAllHooks": True}),
)
# First CLI release whose --help documents every flag above. Older → refuse to
# run rather than run unconfined.
MIN_CLI_VERSION = (2, 1, 287)
VERDICTS = ("pass", "fail")
VERDICT_SCHEMA = {
    "type": "object",
    "properties": {
        "verdict": {"type": "string", "enum": list(VERDICTS)},
        "reason": {"type": "string"},
        "report": {"type": "string"},
    },
    "required": ["verdict", "reason", "report"],
}
# Constitution principles 1/3 as amended by 010: the change set is the focus,
# the whole repository is readable, nothing outside it. The boundary is an
# instruction — read-only confinement (above) is what is enforced.
SCOPE = ("The changed files above triggered this run and are its focus. "
         "You may read any file inside the repository ({root}) for context. "
         "Do not read files outside it.")
OUTPUT_INSTRUCTION = (
    "You have read-only tools; you cannot and must not try to modify files or "
    "run commands. Return your answer as the structured output: "
    "'verdict' is 'fail' if the task's failure condition is met, else 'pass'; "
    "'reason' is one line; 'report' is your full findings in markdown.")


def load_bridge_config(path: str, warnings: list[str]) -> dict:
    """Read config/bridge.json, falling back per-key to DEFAULT_CONFIG."""
    try:
        with open(path, encoding="utf-8") as fh:
            raw = json.load(fh)
        if not isinstance(raw, dict):
            raise ValueError("bridge config must be a JSON object")
    except FileNotFoundError:
        warnings.append(f"bridge config not found: {path} — using defaults")
        return dict(DEFAULT_CONFIG)
    except (OSError, ValueError) as exc:
        warnings.append(f"bridge config unreadable ({path}): {exc} — using defaults")
        return dict(DEFAULT_CONFIG)

    for key in REMOVED_KEYS:
        if key in raw:
            warnings.append(f"bridge config: '{key}' is no longer supported "
                            "(Claude always runs confined) — ignored")

    config = dict(DEFAULT_CONFIG)
    for key, default in DEFAULT_CONFIG.items():
        if key not in raw:
            continue
        value = raw[key]
        # Type-check each override against its default; unknown keys are
        # ignored entirely, so the config can carry comments-by-convention.
        if isinstance(default, (int, float)):
            # bool is a subclass of int — exclude it explicitly.
            valid = (isinstance(value, (int, float)) and not isinstance(value, bool)
                     and value > 0)
        else:
            valid = isinstance(value, str)
        if valid:
            config[key] = value
        else:
            warnings.append(f"bridge config: invalid '{key}' — using default")
    return config


def build_prompt(context: dict, task: str, root: str | None = None) -> str:
    """Render the hook context + task into one prompt.

    Structure matters: state the situation, enumerate the exact change set,
    then the task, the scope rule and the output instruction. A
    partial context is declared rather than hidden, so Claude knows what it is
    missing. Under --restricted CLAUDE.md is not loaded, so the prompt has to
    carry everything Claude needs.
    """
    files = context.get("files") or []
    commits = context.get("commits") or []
    lines = [
        "You are invoked by an automated git-hook pipeline.",
        f"Git event: {context.get('event')}",
        f"Branch: {context.get('branch')}",
    ]
    if context.get("partial"):
        missing = ", ".join(context.get("unavailable") or [])
        lines.append(f"Note: the context is partial — missing fields: {missing}.")
    if files:
        lines.append(f"Changed files — the focus of this run ({len(files)}):")
        lines.extend(f"  - {f}" for f in files)
    else:
        lines.append("There are no changed files in this event.")
    if commits:
        lines.append(f"Commits ({len(commits)}):")
        lines.extend(f"  - {c}" for c in commits)
    scope = SCOPE.format(root=root or "the current working directory")
    lines += ["", f"Task: {task}", "", scope, OUTPUT_INSTRUCTION]
    return "\n".join(lines)


def build_argv(config: dict, max_turns) -> list[str]:
    """The claude CLI argv. The prompt travels on stdin (no argv length limit).

    Pure. The confinement flags are appended unconditionally — there is no
    config value that removes or reorders them.
    """
    argv = [config["claude_command"], "-p", "--output-format", "json",
            "--max-turns", str(max_turns), *CONFINEMENT_ARGS,
            "--json-schema", json.dumps(VERDICT_SCHEMA)]
    if config.get("model"):
        argv += ["--model", config["model"]]
    return argv


def cli_supports_confinement(version_output: str) -> bool:
    """True if `claude --version` output names a version ≥ MIN_CLI_VERSION."""
    match = re.search(r"(\d+)\.(\d+)\.(\d+)", version_output or "")
    if not match:
        return False
    return tuple(int(g) for g in match.groups()) >= MIN_CLI_VERSION


def _payload_error(payload) -> tuple[bool, str]:
    """Read an error out of the CLI's --output-format json payload.

    Returns (payload signals an error, human-readable description). The CLI
    reports failures in the payload rather than on stderr — often with a null
    `result` and the reason only in `subtype` (e.g. error_max_turns) — so the
    payload is the authoritative source. `is_error: true` is a failure even
    when the process exited 0.
    """
    if not isinstance(payload, dict):
        return False, ""
    subtype = payload.get("subtype")
    failed = (payload.get("is_error") is True
              or (isinstance(subtype, str) and subtype.startswith("error")))
    if not failed:
        return False, ""

    parts: list[str] = []
    result = payload.get("result")
    if isinstance(result, str) and result.strip():
        parts.append(result.strip()[:300])
    if isinstance(subtype, str) and subtype != "success":
        parts.append(f"subtype={subtype}")
    api_status = payload.get("api_error_status")
    if api_status:
        parts.append(f"api_error_status={api_status}")
    return True, " | ".join(parts) or "claude reported an error payload"


def parse_verdict(payload) -> tuple[dict | None, str]:
    """Extract {verdict, reason, report} from a CLI payload. Pure.

    Returns (fields, error). `structured_output` is where --json-schema puts
    the object (T0 spike); `result` carrying the same JSON as a string is the
    fallback. fields is None only when no report at all can be recovered;
    a report without a valid verdict comes back with verdict None + an error.
    """
    if not isinstance(payload, dict):
        return None, "claude output is not a JSON object"
    data = payload.get("structured_output")
    if not isinstance(data, dict):
        try:
            data = json.loads(payload.get("result") or "")
        except (TypeError, ValueError):
            data = None
    if not isinstance(data, dict):
        text = payload.get("result")
        if isinstance(text, str) and text.strip():
            return ({"verdict": None, "reason": "", "report": text.strip()},
                    "no structured verdict in claude output")
        return None, "no structured output in claude output"

    report = data.get("report") if isinstance(data.get("report"), str) else ""
    reason = data.get("reason") if isinstance(data.get("reason"), str) else ""
    verdict = data.get("verdict")
    if verdict not in VERDICTS:
        return ({"verdict": None, "reason": reason, "report": report},
                f"invalid verdict {verdict!r}")
    return {"verdict": verdict, "reason": reason, "report": report}, ""


def _default_runner(argv: list[str], prompt_stdin: str | None,
                    timeout: float, cwd: str | None = None) -> tuple[int, str, str]:
    """Real subprocess invocation. Swappable via invoke(runner=...) so the
    bridge can be tested end to end without the claude CLI installed.

    UTF-8 explicitly: the CLI emits UTF-8, and the Windows locale default
    (cp1252) would turn every em dash in a report into mojibake.
    """
    proc = subprocess.run(argv, input=prompt_stdin, text=True,
                          encoding="utf-8", errors="replace",
                          capture_output=True, timeout=timeout, cwd=cwd)
    return proc.returncode, proc.stdout, proc.stderr


# Cached: one `claude --version` per process, not one per skill. Module-level
# state, justified — the answer cannot change while a run is in progress.
@functools.lru_cache(maxsize=8)
def _cli_version(command: str) -> str:
    try:
        proc = subprocess.run([command, "--version"], capture_output=True,
                              text=True, encoding="utf-8", errors="replace",
                              timeout=15)
        return proc.stdout
    except (OSError, subprocess.SubprocessError):
        return ""


def invoke(request: dict, config: dict, runner=None, version_probe=None) -> dict:
    """Run one bridge request and always return a BridgeResult (2.0).

    Statuses: ok / bad-request / unavailable (no CLI, or too old to confine) /
    timeout / error (incl. no valid verdict). Nothing raises — the executor
    classifies the status, so an absent or failing Claude degrades the run,
    never breaks it.
    """
    started = time.monotonic()

    def done(status: str, fields: dict | None = None, error: str = "") -> dict:
        fields = fields or {}
        return {"schema_version": RESULT_SCHEMA_VERSION, "status": status,
                "verdict": fields.get("verdict"),
                "reason": fields.get("reason", ""),
                "report": fields.get("report", ""), "error": error,
                "duration_ms": int((time.monotonic() - started) * 1000)}

    context = request.get("context")
    task = request.get("task")
    if not isinstance(context, dict):
        return done("bad-request", error="request is missing a 'context' object")
    if not isinstance(task, str) or not task.strip():
        return done("bad-request", error="request is missing a non-empty 'task'")
    # Optional (010): the repository root Claude runs in and may read. Absent =
    # inherit the caller's cwd, which inside a git hook is already the root.
    root = request.get("root")
    if root is not None and not (isinstance(root, str) and root and os.path.isdir(root)):
        return done("bad-request", error=f"request 'root' is not a directory: {root!r}")

    options = request.get("options") or {}
    max_turns = options.get("max_turns", config["max_turns"])
    timeout = options.get("timeout_seconds", config["timeout_seconds"])

    if runner is None:
        # Distinguish "Claude is not installed" (unavailable) from "Claude ran
        # and failed" (error) — very different things to diagnose.
        command = shutil.which(config["claude_command"])
        if command is None:
            return done("unavailable",
                        error=f"'{config['claude_command']}' not found on PATH")
        # Never fall back to an unconfined call on a CLI that lacks the flags.
        version = (version_probe or _cli_version)(command)
        if not cli_supports_confinement(version):
            needed = ".".join(map(str, MIN_CLI_VERSION))
            return done("unavailable",
                        error=f"claude CLI too old for confinement (need ≥ {needed}, "
                              f"got {version.strip() or 'unknown'})")
        runner = _default_runner

    argv = build_argv(config, max_turns)
    try:
        returncode, stdout, stderr = runner(argv, build_prompt(context, task, root),
                                            timeout, root)
    except subprocess.TimeoutExpired:
        return done("timeout", error=f"claude invocation exceeded {timeout}s")
    except Exception as exc:  # nothing propagates to the caller
        return done("error", error=f"bridge failure: {exc}")

    try:
        payload = json.loads(stdout)
    except ValueError:
        payload = None
    payload_failed, payload_error = _payload_error(payload)
    if returncode != 0:
        # Prefer the payload's reason; stderr is the fallback for a plain crash.
        detail = payload_error or stderr.strip()[:300]
        return done("error", error=f"claude exited {returncode}: {detail}")
    if payload_failed:
        # Exit 0 with an error payload (e.g. api_error_status 429) is a failure.
        return done("error", error=payload_error)

    fields, error = parse_verdict(payload)
    if error:
        return done("error", fields, error)
    return done("ok", fields)


def main(argv: list[str] | None = None) -> int:
    """CLI (debugging aid): BridgeRequest JSON on stdin -> BridgeResult on stdout.

    Always exits 0 — see the module docstring.
    """
    parser = argparse.ArgumentParser(description="Invoke Claude Code read-only with a bounded context")
    parser.add_argument("--config", default=DEFAULT_CONFIG_PATH)
    args = parser.parse_args(argv)

    warnings: list[str] = []
    config = load_bridge_config(args.config, warnings)
    for w in warnings:
        print(f"[bridge warning] {w}", file=sys.stderr)

    try:
        request = json.load(sys.stdin)
        if not isinstance(request, dict):
            raise ValueError("request must be a JSON object")
    except Exception as exc:
        result = {"schema_version": RESULT_SCHEMA_VERSION, "status": "bad-request",
                  "verdict": None, "reason": "", "report": "",
                  "error": f"unreadable request on stdin: {exc}", "duration_ms": 0}
    else:
        result = invoke(request, config)

    json.dump(result, sys.stdout)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
