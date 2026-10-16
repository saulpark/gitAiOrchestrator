#!/usr/bin/env python3
"""Workflow router (feature 004; execution delegated to 006).

Reads a hook context (003 schema) on stdin, loads config/routes.json fresh on
every invocation, selects the execution plan for the event, and hands it to
the skill executor (execute_skills) with each skill's mode. Emits a
DispatchResult v2.0 JSON on stdout (embedding the ExecutionSummary). Since 009
the terminal stays silent: warnings go to logs/hooks.log and the run record,
and the only stderr output is a `[hook blocked]` line when a sync skill's
block rule matched (exit 10). Every other path exits 0. Contracts:
specs/004-workflow-router/contracts/routing-config.md,
specs/006-skill-executor/contracts/execution-summary.md,
specs/009-aioutput-skills/contracts/execution-and-output.md
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone

from ai_output import DEFAULT_OUTPUT_RETENTION
from claude_bridge import invoke as bridge_invoke
from claude_bridge import load_bridge_config
from execute_skills import (
    DEFAULT_MODE,
    DEFAULT_SYNC_CEILING,
    MAX_BUDGET_SECONDS,
    MODES,
    dispatch_async,
    execute_plan,
)
from run_records import (
    BLOCK_EXIT_CODE,
    DEFAULT_RETENTION,
    build_run_record,
    evaluate_outcomes,
    new_run_id,
    write_run_record,
)

# DispatchResult: 1.0 → 1.1 (006) → 1.2 (008) → 2.0 (009: modes, verdicts,
# result files; warnings no longer printed)
RESULT_SCHEMA_VERSION = "2.0"
OUTCOMES = ("invoked", "unresolvable", "failed")  # router-level vocabulary
VALID_EVENTS = ("pre-commit", "post-merge", "pre-push")
DEFAULT_CONFIG = "config/routes.json"
DEFAULT_SKILLS_DIR = "skills"
# Executor statuses (006) collapse into the router's coarser vocabulary (004),
# which the DispatchResult has exposed since before the executor existed.
_STATUS_TO_OUTCOME = {"success": "invoked", "dispatched": "invoked",
                      "skipped": "unresolvable", "failure": "failed",
                      "error": "failed", "timeout": "failed",
                      "dispatch-failed": "failed"}


def _positive_int(raw: dict, key: str, default: int, warnings: list[str]) -> int:
    value = raw.get(key, default)
    # isinstance(True, int) is True in Python — exclude bools explicitly.
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        warnings.append(f"routing config: '{key}' must be a positive integer — using default")
        return default
    return value


def _skill_rules(raw: dict, warnings: list[str]) -> dict:
    """routes v2.0 `skills` (+ the v1.x `outcomes` fallback) → {name: rule}.

    Rule values are validated here only as far as shape and mode go; an
    invalid on_failure is kept so evaluate_outcomes can note it per run.
    """
    skills = raw.get("skills", {})
    if not isinstance(skills, dict) or not all(isinstance(v, dict) for v in skills.values()):
        warnings.append("routing config: 'skills' must be an object of rule objects — ignoring")
        skills = {}
    rules = {name: dict(rule) for name, rule in skills.items()}

    legacy = raw.get("outcomes", {})
    if not isinstance(legacy, dict) or not all(isinstance(v, dict) for v in legacy.values()):
        warnings.append("routing config: 'outcomes' must be an object of rule objects — ignoring")
        legacy = {}
    if legacy:
        warnings.append("routing config: 'outcomes' is deprecated — move on_failure "
                        "into skills.<name> (routes v2.0)")
    for name, rule in legacy.items():
        if "on_failure" in rule:
            rules.setdefault(name, {}).setdefault("on_failure", rule["on_failure"])

    for name, rule in rules.items():
        if "mode" in rule and rule["mode"] not in MODES:
            warnings.append(f"routing config: skill '{name}' has invalid mode "
                            f"{rule['mode']!r} — using {DEFAULT_MODE}")
            del rule["mode"]
        rule.setdefault("mode", DEFAULT_MODE)
        if rule.get("on_failure") == "block" and rule["mode"] != "sync":
            warnings.append(f"routing config: skill '{name}' is async — "
                            "on_failure=block is ignored (only sync skills block)")
    return rules


def load_config(path: str, warnings: list[str]) -> dict:
    """Read and sanitize config/routes.json; never raise.

    Read fresh on every invocation (SC-005) so editing routes or skill rules
    takes effect on the next git event with no reinstall. Every validation
    problem degrades to "route nothing" plus a warning rather than an error:
    a typo in the config must not be able to break someone's commit.
    """
    empty = {"version": "2.0", "routes": {}, "skills": {},
             "sync_ceiling_seconds": DEFAULT_SYNC_CEILING,
             "run_retention": DEFAULT_RETENTION,
             "output_retention": DEFAULT_OUTPUT_RETENTION}
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

    ceiling = raw.get("sync_ceiling_seconds", DEFAULT_SYNC_CEILING)
    if (not isinstance(ceiling, (int, float)) or isinstance(ceiling, bool)
            or not 1 <= ceiling <= MAX_BUDGET_SECONDS):
        warnings.append(f"routing config: 'sync_ceiling_seconds' must be 1–"
                        f"{MAX_BUDGET_SECONDS} — using {DEFAULT_SYNC_CEILING:g}")
        ceiling = DEFAULT_SYNC_CEILING

    return {"version": raw.get("version", "1.0"), "routes": clean,
            "skills": _skill_rules(raw, warnings),
            "sync_ceiling_seconds": float(ceiling),
            "run_retention": _positive_int(raw, "run_retention", DEFAULT_RETENTION, warnings),
            "output_retention": _positive_int(raw, "output_retention",
                                              DEFAULT_OUTPUT_RETENTION, warnings)}


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

    A coarse "did anything run?" trail, followed by one line per warning. The
    full detail lives in the run record written by feature 008.
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
            # The terminal stays silent since 009, so this is where warnings
            # are read.
            fh.writelines(f"[{stamp}] warning {w}\n" for w in result["warnings"])
    except OSError:
        pass  # logging must never break routing


def main(argv: list[str] | None = None, bridge=bridge_invoke,
         dispatch=dispatch_async) -> int:
    """CLI: context JSON on stdin -> DispatchResult on stdout.

    The full runtime pipeline lives here: load config → select plan → execute
    (006/009: async dispatched, sync run) → evaluate outcomes + write the run
    record (008). Exit code is 0, except BLOCK_EXIT_CODE (10) when a sync
    skill's block rule matched — the one signal scripts/lib.sh translates into
    aborting the git operation. bridge/dispatch are injectable for tests.
    """
    parser = argparse.ArgumentParser(description="Route a hook context to configured workflows")
    parser.add_argument("--config", default=DEFAULT_CONFIG)
    parser.add_argument("--log", default=None)
    parser.add_argument("--skills-dir", default=DEFAULT_SKILLS_DIR)
    parser.add_argument("--root", default=".", help="repository root (for _aioutput/, logs/)")
    parser.add_argument("--runs-dir", default=None, help="default: <root>/logs/runs")
    parser.add_argument("--bridge-config", default=None,
                        help="default: <root>/config/bridge.json")
    args = parser.parse_args(argv)
    root = os.path.abspath(args.root)
    runs_dir = args.runs_dir or os.path.join(root, "logs", "runs")

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
        # The id is needed before the run ends: it names the async job and is
        # written into every result file.
        run_id = new_run_id(context.get("event"))
        bridge_config = load_bridge_config(
            args.bridge_config or os.path.join(root, "config", "bridge.json"),
            warnings) if plan else None
        rules = config["skills"]
        summary = execute_plan(
            plan, context, skills_dir=args.skills_dir, root=root, run_id=run_id,
            modes={s: rules.get(s, {}).get("mode", DEFAULT_MODE) for s in plan},
            sync_ceiling=config["sync_ceiling_seconds"], bridge_config=bridge_config,
            output_retention=config["output_retention"],
            jobs_dir=os.path.join(root, "logs", "async"), runs_dir=runs_dir,
            log_path=os.path.abspath(args.log) if args.log else None,
            outcome_rules=rules, run_retention=config["run_retention"],
            bridge=bridge, dispatch=dispatch)
        evaluation = evaluate_outcomes(summary, rules, context.get("event"))
        record = build_run_record(context, plan, summary, evaluation, warnings,
                                  run_id=run_id)
        record_path = write_run_record(runs_dir, record, config["run_retention"])

        results = []
        for r in evaluation["results"]:
            outcome = _STATUS_TO_OUTCOME.get(r["status"], "failed")
            if r["outcome"] == "warn":
                warnings.append(f"workflow '{r['skill']}' {outcome}: {r['detail']}")
            results.append({"workflow": r["skill"], "mode": r["mode"],
                            "outcome": outcome, "status": r["status"],
                            "verdict": r["verdict"], "output_file": r["output_file"],
                            "detail": r["detail"], "duration_ms": r["duration_ms"]})

        # Every blocking skill is named — the developer should not have to
        # re-run to discover the second reason their commit was refused.
        blocking = [r for r in evaluation["results"] if r["outcome"] == "block"]
        for b in blocking:
            see = f" (see {b['output_file']})" if b["output_file"] else ""
            print(f"[hook blocked] skill '{b['skill']}': {b['detail']}{see}",
                  file=sys.stderr)
        if blocking:
            exit_code = BLOCK_EXIT_CODE

        result = {"schema_version": RESULT_SCHEMA_VERSION, "run_id": run_id,
                  "event": context.get("event"), "overall": summary["overall"],
                  "final_outcome": evaluation["final_outcome"],
                  "results": results, "outcomes": evaluation["results"],
                  "execution": summary, "run_record": record_path,
                  "warnings": evaluation.get("notes", [])}
    except Exception as exc:  # SC-004: only a matched block rule may abort git
        # A router crash is logged and exits 0 — never a block.
        result = {"schema_version": RESULT_SCHEMA_VERSION, "run_id": None,
                  "event": context.get("event"), "overall": "failure",
                  "final_outcome": "warn", "results": [], "outcomes": [],
                  "execution": None, "run_record": None,
                  "warnings": [f"router failure: {exc}"]}
        exit_code = 0
    result["warnings"] = warnings + result["warnings"]

    if args.log:
        _log_summary(args.log, result)
    json.dump(result, sys.stdout)
    sys.stdout.write("\n")
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
