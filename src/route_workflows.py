#!/usr/bin/env python3
"""Workflow router (feature 004; execution delegated to 006).

Reads a hook context (003 schema) on stdin, loads config/routes.json fresh on
every invocation, selects the execution plan for the event, and hands it to
the skill executor (execute_skills). Emits a DispatchResult v1.1 JSON on
stdout (embedding the ExecutionSummary), warnings on stderr, and always exits
0 so routing can never abort the triggering git operation. Contracts:
specs/004-workflow-router/contracts/routing-config.md,
specs/006-skill-executor/contracts/execution-summary.md
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone

from execute_skills import execute_plan

RESULT_SCHEMA_VERSION = "1.1"
OUTCOMES = ("invoked", "unresolvable", "failed")
VALID_EVENTS = ("pre-commit", "post-merge", "pre-push")
DEFAULT_CONFIG = "config/routes.json"
DEFAULT_SKILLS_DIR = "skills"
_STATUS_TO_OUTCOME = {"success": "invoked", "skipped": "unresolvable",
                      "failure": "failed", "timeout": "failed"}


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


def select_plan(context: dict, config: dict, warnings: list[str]) -> list[str]:
    """Extract the ordered execution plan for the context's event (FR-006)."""
    event = context.get("event")
    if event not in VALID_EVENTS:
        warnings.append(f"cannot route context: event is {event!r}")
        return []
    return config.get("routes", {}).get(event, [])


def route(context: dict, config: dict, invoker) -> dict:
    warnings: list[str] = []
    results: list[dict] = []
    event = context.get("event")
    workflows = select_plan(context, config, warnings)

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
                     f"overall={result.get('overall', 'n/a')} "
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
        plan = select_plan(context, config, warnings)
        summary = execute_plan(plan, context, args.skills_dir)
        results = []
        for r in summary["results"]:
            outcome = _STATUS_TO_OUTCOME.get(r["status"], "failed")
            if outcome != "invoked":
                warnings.append(f"workflow '{r['skill']}' {outcome}: {r['detail']}")
            results.append({"workflow": r["skill"], "outcome": outcome,
                            "status": r["status"], "detail": r["detail"],
                            "duration_ms": r["duration_ms"]})
        result = {"schema_version": RESULT_SCHEMA_VERSION,
                  "event": context.get("event"), "overall": summary["overall"],
                  "results": results, "execution": summary, "warnings": []}
    except Exception as exc:  # SC-004: routing can never abort the git operation
        result = {"schema_version": RESULT_SCHEMA_VERSION,
                  "event": context.get("event"), "overall": "failure",
                  "results": [], "execution": None,
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
