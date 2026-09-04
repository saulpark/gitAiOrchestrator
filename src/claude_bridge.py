#!/usr/bin/env python3
"""Claude Code bridge (feature 007).

The single component skills use to invoke Claude Code. Reads a BridgeRequest
on stdin, builds a bounded prompt from the hook context (never the full
repository), runs the claude CLI headless in the current directory so the
project's own Claude Code settings apply, and emits a BridgeResult. Always
exits 0 — the calling skill decides its own outcome. Contract:
specs/007-claude-code-bridge/contracts/bridge-interface.md
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import time

REQUEST_SCHEMA_VERSION = "1.0"
RESULT_SCHEMA_VERSION = "1.0"
DEFAULT_CONFIG_PATH = "config/bridge.json"
# Defaults also define the expected type of every config key: load_bridge_config
# validates config/bridge.json against these, so a bad value degrades instead of
# reaching the CLI invocation.
DEFAULT_CONFIG = {
    "version": "1.0",
    "claude_command": "claude",
    "max_turns": 4,           # bounded agentic turns — hooks must stay quick
    "timeout_seconds": 120,
    # Off by default: hooks enabled inside the bridge would let a hook-triggered
    # Claude run trigger hooks of its own. No recursion.
    "hooks_enabled": False,
    "extra_args": [],
}
# Constitution principle 1/3: Claude sees the change set, never the whole repo.
CONSTRAINT = ("Only examine the files listed above. "
              "Do not scan or enumerate the rest of the repository.")


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

    config = dict(DEFAULT_CONFIG)
    for key, default in DEFAULT_CONFIG.items():
        if key not in raw:
            continue
        value = raw[key]
        # Type-check each override against its default; unknown keys are
        # ignored entirely, so the config can carry comments-by-convention.
        if isinstance(default, bool):
            valid = isinstance(value, bool)
        elif isinstance(default, (int, float)):
            # bool is a subclass of int — check bool first, exclude it here.
            valid = isinstance(value, (int, float)) and not isinstance(value, bool)
        elif isinstance(default, list):
            valid = isinstance(value, list) and all(isinstance(v, str) for v in value)
        else:
            valid = isinstance(value, str)
        if valid:
            config[key] = value
        else:
            warnings.append(f"bridge config: invalid '{key}' — using default")
    return config


def build_prompt(context: dict, task: str) -> str:
    """Render the hook context + task into one bounded prompt.

    Structure matters: state the situation, enumerate the exact change set,
    then the task, and close with the do-not-scan constraint. A partial context
    is declared rather than hidden, so Claude knows what it is missing.
    """
    files = context.get("files") or []
    commits = context.get("commits") or []
    lines = [
        "You are invoked by an automated git-hook documentation pipeline.",
        f"Git event: {context.get('event')}",
        f"Branch: {context.get('branch')}",
    ]
    if context.get("partial"):
        missing = ", ".join(context.get("unavailable") or [])
        lines.append(f"Note: the context is partial — missing fields: {missing}.")
    if files:
        lines.append(f"Changed files ({len(files)}):")
        lines.extend(f"  - {f}" for f in files)
    else:
        lines.append("There are no changed files in this event.")
    if commits:
        lines.append(f"Commits ({len(commits)}):")
        lines.extend(f"  - {c}" for c in commits)
    lines.append("")
    lines.append(f"Task: {task}")
    lines.append("")
    lines.append(CONSTRAINT)
    return "\n".join(lines)


def _payload_error(stdout: str) -> tuple[bool, str]:
    """Read an error out of the CLI's --output-format json payload.

    Returns (payload signals an error, human-readable description). The CLI
    reports failures in the payload rather than on stderr — often with a null
    `result` and the reason only in `subtype` (e.g. error_max_turns), and with
    stderr entirely empty — so the payload is the authoritative source for the
    description the 007 contract promises. An `is_error: true` payload counts
    as a failure even when the process exited 0.
    """
    try:
        payload = json.loads(stdout)
    except ValueError:
        return False, ""
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


def _default_runner(argv: list[str], prompt_stdin: str | None,
                    timeout: float) -> tuple[int, str, str]:
    """Real subprocess invocation. Swappable via invoke(runner=...) so the
    bridge can be tested end to end without the claude CLI installed."""
    proc = subprocess.run(argv, input=prompt_stdin, text=True,
                          capture_output=True, timeout=timeout)
    return proc.returncode, proc.stdout, proc.stderr


def invoke(request: dict, config: dict, runner=None) -> dict:
    """Run one bridge request and always return a BridgeResult.

    Statuses: ok / bad-request / unavailable (no claude CLI) / timeout / error.
    Nothing raises — the calling skill inspects the status and decides its own
    outcome, so an absent or failing Claude degrades the run, never breaks it.
    """
    started = time.monotonic()

    def done(status: str, output=None, output_text: str = "",
             error: str = "") -> dict:
        return {"schema_version": RESULT_SCHEMA_VERSION, "status": status,
                "output": output, "output_text": output_text, "error": error,
                "duration_ms": int((time.monotonic() - started) * 1000)}

    context = request.get("context")
    task = request.get("task")
    if not isinstance(context, dict):
        return done("bad-request", error="request is missing a 'context' object")
    if not isinstance(task, str) or not task.strip():
        return done("bad-request", error="request is missing a non-empty 'task'")

    options = request.get("options") or {}
    max_turns = options.get("max_turns", config["max_turns"])
    timeout = options.get("timeout_seconds", config["timeout_seconds"])

    if runner is None:
        # Distinguish "Claude is not installed" (unavailable) from "Claude ran
        # and failed" (error) — very different things for a skill to react to.
        if shutil.which(config["claude_command"]) is None:
            return done("unavailable",
                        error=f"'{config['claude_command']}' not found on PATH")
        runner = _default_runner

    # Headless (-p) with JSON output; run in the current working directory so
    # the project's own .claude/settings.json and CLAUDE.md apply unchanged.
    argv = [config["claude_command"], "-p", build_prompt(context, task),
            "--output-format", "json", "--max-turns", str(max_turns)]
    if not config["hooks_enabled"]:
        # Prevents the git-hook-triggered Claude run from firing hooks itself.
        argv += ["--settings", json.dumps({"disableAllHooks": True})]
    argv += list(config["extra_args"])

    try:
        returncode, stdout, stderr = runner(argv, None, timeout)
    except subprocess.TimeoutExpired:
        return done("timeout", error=f"claude invocation exceeded {timeout}s")
    except Exception as exc:  # SC-003: nothing propagates to the caller
        return done("error", error=f"bridge failure: {exc}")

    payload_failed, payload_error = _payload_error(stdout)
    if returncode != 0:
        # Prefer the payload's reason; stderr is the fallback for a plain crash.
        detail = payload_error or stderr.strip()[:300]
        return done("error", error=f"claude exited {returncode}: {detail}")
    if payload_failed:
        # Exit 0 with an error payload (e.g. api_error_status 429) is a failure.
        return done("error", error=payload_error)

    # Prefer the CLI's structured JSON, but never fail on it: if the shape
    # changes, fall back to raw text so the skill still gets something usable.
    try:
        output = json.loads(stdout)
        text = output.get("result", "") if isinstance(output, dict) else ""
        if not isinstance(output, dict):
            output, text = None, stdout.strip()
    except ValueError:
        output, text = None, stdout.strip()
    return done("ok", output=output, output_text=text)


def main(argv: list[str] | None = None) -> int:
    """CLI: BridgeRequest JSON on stdin -> BridgeResult JSON on stdout.

    Always exits 0 — see the module docstring.
    """
    parser = argparse.ArgumentParser(description="Invoke Claude Code with a bounded context")
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
                  "output": None, "output_text": "",
                  "error": f"unreadable request on stdin: {exc}", "duration_ms": 0}
    else:
        result = invoke(request, config)

    json.dump(result, sys.stdout)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
