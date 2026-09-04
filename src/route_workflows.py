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
from run_records import (
    BLOCK_EXIT_CODE,
    DEFAULT_RETENTION,
    DEFAULT_RUNS_DIR,
    build_run_record,
    evaluate_outcomes,
    write_run_record,
)

RESULT_SCHEMA_VERSION = "1.2"   # DispatchResult: 1.0 → 1.1 (006) → 1.2 (008)
OUTCOMES = ("invoked", "unresolvable", "failed")  # router-level vocabulary
VALID_EVENTS = ("pre-commit", "post-merge", "pre-push")
DEFAULT_CONFIG = "config/routes.json"
DEFAULT_SKILLS_DIR = "skills"
# Executor statuses (006) collapse into the router's coarser vocabulary (004),
# which the DispatchResult has exposed since before the executor existed.
_STATUS_TO_OUTCOME = {"success": "invoked", "skipped": "unresolvable",
                      "failure": "failed", "timeout": "failed"}


def load_config(path: str, warnings: list[str]) -> dict:
    """Read and sanitize config/routes.json; never raise.

    Read fresh on every invocation (SC-005) so editing routes or outcome rules
    takes effect on the next git event with no reinstall. Every validation
    problem degrades to "route nothing" plus a warning rather than an error:
    a typo in the config must not be able to break someone's commit.
    """
    empty = {"version": "1.0", "routes": {}, "outcomes": {},
             "run_retention": DEFAULT_RETENTION}
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

    # Validate per event, so one bad entry doesn't discard the whole table.
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

    # routes v1.1: {"<skill>": {"on_failure": "block"|"warn"|"skip"}} (008).
    # Individual rule values are validated later, at evaluation time.
    outcomes = raw.get("outcomes", {})
    if not isinstance(outcomes, dict) or not all(
            isinstance(v, dict) for v in outcomes.values()):
        if outcomes != {}:
            warnings.append("routing config: 'outcomes' must be an object of "
                            "rule objects — ignoring")
        outcomes = {}

    retention = raw.get("run_retention", DEFAULT_RETENTION)
    # isinstance(True, int) is True in Python — exclude bools explicitly.
    if not isinstance(retention, int) or isinstance(retention, bool) or retention < 1:
        if retention != DEFAULT_RETENTION:
            warnings.append("routing config: 'run_retention' must be a positive "
                            "integer — using default")
        retention = DEFAULT_RETENTION

    return {"version": raw.get("version", "1.0"), "routes": clean,
            "outcomes": outcomes, "run_retention": retention}


def select_plan(context: dict, config: dict, warnings: list[str]) -> list[str]:
    """Extract the ordered execution plan for the context's event (FR-006)."""
    event = context.get("event")
    if event not in VALID_EVENTS:
        warnings.append(f"cannot route context: event is {event!r}")
        return []
    return config.get("routes", {}).get(event, [])


def route(context: dict, config: dict, invoker) -> dict:
    """Dispatch a plan through a caller-supplied invoker (feature 004).

    Kept as the pluggable-invoker seam the 004 contract defines and its tests
    pin. main() no longer uses it — since 006 the real path calls the skill
    executor directly (see execute_plan below).
    """
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
    """Append one human-scannable line per event to logs/hooks.log.

    A coarse "did anything run?" trail. The full detail lives in the run record
    written by feature 008; this is what `tail -1 logs/hooks.log` shows.
    """
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
                     f"outcome={result.get('final_outcome', 'n/a')} "
                     f"warnings={len(result['warnings'])}\n")
    except OSError:
        pass  # logging must never break routing


def main(argv: list[str] | None = None) -> int:
    """CLI: context JSON on stdin -> DispatchResult on stdout.

    The full runtime pipeline lives here: load config → select plan → execute
    (006) → evaluate outcomes + write the run record (008). Exit code is 0,
    except BLOCK_EXIT_CODE (10) when a configured block rule matched — the one
    signal scripts/lib.sh translates into aborting the git operation.
    """
    parser = argparse.ArgumentParser(description="Route a hook context to configured workflows")
    parser.add_argument("--config", default=DEFAULT_CONFIG)
    parser.add_argument("--log", default=None)
    parser.add_argument("--skills-dir", default=DEFAULT_SKILLS_DIR)
    parser.add_argument("--runs-dir", default=DEFAULT_RUNS_DIR)
    args = parser.parse_args(argv)

    warnings: list[str] = []
    try:
        context = json.load(sys.stdin)
        if not isinstance(context, dict):
            raise ValueError("context must be a JSON object")
    except Exception as exc:
        # Unreadable context is not fatal: carry on with an eventless context,
        # which routes to nothing and still produces a record and a warning.
        warnings.append(f"unreadable context on stdin: {exc}")
        context = {"event": None}

    config = load_config(args.config, warnings)
    exit_code = 0
    try:
        plan = select_plan(context, config, warnings)
        summary = execute_plan(plan, context, args.skills_dir)
        evaluation = evaluate_outcomes(summary, config["outcomes"],
                                       context.get("event"))
        record = build_run_record(context, plan, summary, evaluation, warnings)
        record_path = write_run_record(args.runs_dir, record,
                                       config["run_retention"])

        # Re-shape the evaluated results into the DispatchResult vocabulary,
        # surfacing anything ruled "warn" on stderr where the developer sees it.
        results = []
        for r in evaluation["results"]:
            outcome = _STATUS_TO_OUTCOME.get(r["status"], "failed")
            if r["outcome"] == "warn":
                warnings.append(f"workflow '{r['skill']}' {outcome}: {r['detail']}")
            results.append({"workflow": r["skill"], "outcome": outcome,
                            "status": r["status"], "detail": r["detail"],
                            "duration_ms": r["duration_ms"]})

        # Every blocking skill is named — the developer should not have to
        # re-run to discover the second reason their commit was refused.
        blocking = [r for r in evaluation["results"] if r["outcome"] == "block"]
        for b in blocking:
            print(f"[hook blocked] skill '{b['skill']}': {b['detail']}",
                  file=sys.stderr)
        if blocking:
            exit_code = BLOCK_EXIT_CODE

        result = {"schema_version": RESULT_SCHEMA_VERSION,
                  "event": context.get("event"), "overall": summary["overall"],
                  "final_outcome": evaluation["final_outcome"],
                  "results": results, "outcomes": evaluation["results"],
                  "execution": summary, "run_record": record_path,
                  "warnings": evaluation.get("notes", [])}
    except Exception as exc:  # SC-004: only a matched block rule may abort git
        # A router crash is reported as a warning and exit 0 — never a block.
        result = {"schema_version": RESULT_SCHEMA_VERSION,
                  "event": context.get("event"), "overall": "failure",
                  "final_outcome": "warn", "results": [], "outcomes": [],
                  "execution": None, "run_record": None,
                  "warnings": [f"router failure: {exc}"]}
        exit_code = 0
    result["warnings"] = warnings + result["warnings"]

    for w in result["warnings"]:
        print(f"[router warning] {w}", file=sys.stderr)
    if args.log:
        _log_summary(args.log, result)
    json.dump(result, sys.stdout)
    sys.stdout.write("\n")
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
