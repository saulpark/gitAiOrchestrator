#!/usr/bin/env python3
"""Workflow router (feature 004).

Reads a hook context (003 schema) on stdin, loads config/routes.json fresh on
every invocation, and dispatches each mapped workflow identifier through an
invoker. Emits a DispatchResult JSON on stdout, warnings on stderr, and always
exits 0 so routing can never abort the triggering git operation. Contract:
specs/004-workflow-router/contracts/routing-config.md
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone

RESULT_SCHEMA_VERSION = "1.0"
OUTCOMES = ("invoked", "unresolvable", "failed")
VALID_EVENTS = ("pre-commit", "post-merge", "pre-push")
DEFAULT_CONFIG = "config/routes.json"
DEFAULT_SKILLS_DIR = "skills"
SKILL_GUARD_SECONDS = 60


def load_config(path: str, warnings: list[str]) -> dict:
    empty = {"version": "1.0", "routes": {}}
    try:
        with open(path, encoding="utf-8") as fh:
            raw = json.load(fh)
    except FileNotFoundError:
        warnings.append(f"routing config not found: {path} — treating as empty")
        return empty
    except (json.JSONDecodeError, OSError) as exc:
        warnings.append(f"routing config unreadable ({path}): {exc} — treating as empty")
        return empty

    routes = raw.get("routes") if isinstance(raw, dict) else None
    if not isinstance(routes, dict):
        warnings.append(f"routing config ({path}): 'routes' must be an object — treating as empty")
        return empty

    clean: dict[str, list[str]] = {}
    for event, workflows in routes.items():
        if event not in VALID_EVENTS:
            warnings.append(f"routing config: unknown event '{event}' ignored")
            continue
        if isinstance(workflows, list) and all(isinstance(w, str) for w in workflows):
            clean[event] = workflows
        else:
            warnings.append(f"routing config: route for '{event}' must be a list of strings — treating as empty")
            clean[event] = []
    return {"version": raw.get("version", "1.0"), "routes": clean}


def make_skills_invoker(skills_dir: str):
    """Provisional invoker (superseded by 005/006): skills/<id>/run executable."""
    def invoker(identifier: str, context: dict) -> tuple[str, str]:
        run_path = os.path.join(skills_dir, identifier, "run")
        if not (os.path.isfile(run_path) and os.access(run_path, os.X_OK)):
            return "unresolvable", f"no executable at {run_path}"
        proc = subprocess.run(
            [run_path], input=json.dumps(context), text=True,
            capture_output=True, timeout=SKILL_GUARD_SECONDS,
        )
        if proc.returncode != 0:
            return "failed", f"exit {proc.returncode}: {proc.stderr.strip()[:200]}"
        return "invoked", ""
    return invoker


def route(context: dict, config: dict, invoker) -> dict:
    warnings: list[str] = []
    results: list[dict] = []

    event = context.get("event")
    if event not in VALID_EVENTS:
        warnings.append(f"cannot route context: event is {event!r}")
        workflows: list[str] = []
    else:
        workflows = config.get("routes", {}).get(event, [])

    for identifier in workflows:
        try:
            outcome, detail = invoker(identifier, context)
        except Exception as exc:  # isolation: one failure never stops the rest
            outcome, detail = "failed", str(exc)
        if outcome not in OUTCOMES:
            outcome, detail = "failed", f"invoker returned invalid outcome {outcome!r}: {detail}"
        if outcome != "invoked":
            warnings.append(f"workflow '{identifier}' {outcome}: {detail}")
        results.append({"workflow": identifier, "outcome": outcome, "detail": detail})

    return {
        "schema_version": RESULT_SCHEMA_VERSION,
        "event": event if event in VALID_EVENTS else context.get("event"),
        "results": results,
        "warnings": warnings,
    }


def _log_summary(log_path: str, result: dict) -> None:
    try:
        os.makedirs(os.path.dirname(log_path) or ".", exist_ok=True)
        counts: dict[str, int] = {}
        for r in result["results"]:
            counts[r["outcome"]] = counts.get(r["outcome"], 0) + 1
        summary = " ".join(f"{k}={v}" for k, v in sorted(counts.items())) or "dispatched=0"
        stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        with open(log_path, "a", encoding="utf-8") as fh:
            fh.write(f"[{stamp}] route event={result['event']} {summary} "
                     f"warnings={len(result['warnings'])}\n")
    except OSError:
        pass  # logging must never break routing


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Route a hook context to configured workflows")
    parser.add_argument("--config", default=DEFAULT_CONFIG)
    parser.add_argument("--log", default=None)
    parser.add_argument("--skills-dir", default=DEFAULT_SKILLS_DIR)
    args = parser.parse_args(argv)

    warnings: list[str] = []
    try:
        context = json.load(sys.stdin)
        if not isinstance(context, dict):
            raise ValueError("context must be a JSON object")
    except Exception as exc:
        warnings.append(f"unreadable context on stdin: {exc}")
        context = {"event": None}

    config = load_config(args.config, warnings)
    try:
        result = route(context, config, make_skills_invoker(args.skills_dir))
    except Exception as exc:  # SC-004: routing can never abort the git operation
        result = {"schema_version": RESULT_SCHEMA_VERSION,
                  "event": context.get("event"), "results": [],
                  "warnings": [f"router failure: {exc}"]}
    result["warnings"] = warnings + result["warnings"]

    for w in result["warnings"]:
        print(f"[router warning] {w}", file=sys.stderr)
    if args.log:
        _log_summary(args.log, result)
    json.dump(result, sys.stdout)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
