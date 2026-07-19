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
DEFAULT_CONFIG = {
    "version": "1.0",
    "claude_command": "claude",
    "max_turns": 4,
    "timeout_seconds": 120,
    "hooks_enabled": False,
    "extra_args": [],
}
CONSTRAINT = ("Only examine the files listed above. "
              "Do not scan or enumerate the rest of the repository.")


def load_bridge_config(path: str, warnings: list[str]) -> dict:
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
        if isinstance(default, bool):
            valid = isinstance(value, bool)
        elif isinstance(default, (int, float)):
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


def _default_runner(argv: list[str], prompt_stdin: str | None,
                    timeout: float) -> tuple[int, str, str]:
    proc = subprocess.run(argv, input=prompt_stdin, text=True,
                          capture_output=True, timeout=timeout)
    return proc.returncode, proc.stdout, proc.stderr


def invoke(request: dict, config: dict, runner=None) -> dict:
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
        if shutil.which(config["claude_command"]) is None:
            return done("unavailable",
                        error=f"'{config['claude_command']}' not found on PATH")
        runner = _default_runner

    argv = [config["claude_command"], "-p", build_prompt(context, task),
            "--output-format", "json", "--max-turns", str(max_turns)]
    if not config["hooks_enabled"]:
        argv += ["--settings", json.dumps({"disableAllHooks": True})]
    argv += list(config["extra_args"])

    try:
        returncode, stdout, stderr = runner(argv, None, timeout)
    except subprocess.TimeoutExpired:
        return done("timeout", error=f"claude invocation exceeded {timeout}s")
    except Exception as exc:  # SC-003: nothing propagates to the caller
        return done("error", error=f"bridge failure: {exc}")

    if returncode != 0:
        return done("error",
                    error=f"claude exited {returncode}: {stderr.strip()[:300]}")

    try:
        output = json.loads(stdout)
        text = output.get("result", "") if isinstance(output, dict) else ""
        if not isinstance(output, dict):
            output, text = None, stdout.strip()
    except ValueError:
        output, text = None, stdout.strip()
    return done("ok", output=output, output_text=text)


def main(argv: list[str] | None = None) -> int:
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
