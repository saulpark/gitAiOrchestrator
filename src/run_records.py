#!/usr/bin/env python3
"""Run observability and outcome enforcement (feature 008).

Evaluates block/warn/skip outcomes for every skill result (default: warn —
safe by default, FR-009), writes a run record for every automation run to
logs/runs/, and provides the run-history CLI. Contract:
specs/008-run-observability/contracts/run-record.md
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone

RECORD_SCHEMA_VERSION = "1.0"
BLOCK_EXIT_CODE = 10
OUTCOMES = ("block", "warn", "skip")
DEFAULT_RETENTION = 50
DEFAULT_RUNS_DIR = "logs/runs"
BLOCKABLE_EVENTS = ("pre-commit", "pre-push")


def evaluate_outcomes(summary: dict, outcome_rules: dict, event: str) -> dict:
    """Map each execution result to an outcome per the configured rules."""
    results: list[dict] = []
    notes: list[str] = []
    block_downgraded = False

    for r in summary.get("results", []):
        skill, status = r["skill"], r["status"]
        rule = outcome_rules.get(skill) if isinstance(outcome_rules, dict) else None
        if not isinstance(rule, dict):
            rule = None

        if status == "success":
            outcome = "none"
            reason = "skill succeeded"
        else:
            requested = rule.get("on_failure") if rule else None
            if requested in OUTCOMES:
                outcome = requested
                reason = (f"rule outcomes.{skill}.on_failure={requested} "
                          f"matched status '{status}'")
            else:
                if rule is not None:
                    notes.append(f"invalid outcome rule for '{skill}' "
                                 f"({requested!r}) — defaulting to warn")
                outcome = "warn"
                reason = f"no valid rule for '{skill}' — default warn on status '{status}'"
            if outcome == "block" and event not in BLOCKABLE_EVENTS:
                outcome = "warn"
                block_downgraded = True
                reason += f" (block downgraded to warn: '{event}' already completed)"

        results.append({"skill": skill, "status": status,
                        "duration_ms": r.get("duration_ms", 0),
                        "detail": r.get("detail", ""),
                        "rule": rule, "outcome": outcome, "reason": reason})

    if any(r["outcome"] == "block" for r in results):
        final = "block"
    elif any(r["outcome"] == "warn" for r in results):
        final = "warn"
    else:
        final = "none"

    return {"results": results, "final_outcome": final,
            "block_downgraded": block_downgraded, "notes": notes}


def build_run_record(context: dict, plan: list[str], summary: dict,
                     evaluation: dict, warnings: list[str]) -> dict:
    now = datetime.now(timezone.utc)
    event = context.get("event")
    return {
        "schema_version": RECORD_SCHEMA_VERSION,
        "id": f"{now.strftime('%Y%m%dT%H%M%S.%f')}Z-{event}",
        "event": event,
        "timestamp": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "branch": context.get("branch"),
        "context_summary": {"files": len(context.get("files") or []),
                            "commits": len(context.get("commits") or []),
                            "partial": bool(context.get("partial"))},
        "plan": plan,
        "results": evaluation["results"],
        "final_outcome": evaluation["final_outcome"],
        "block_downgraded": evaluation["block_downgraded"],
        "duration_ms": summary.get("duration_ms", 0),
        "warnings": list(warnings) + list(evaluation.get("notes", [])),
    }


def write_run_record(runs_dir: str, record: dict,
                     retention: int = DEFAULT_RETENTION) -> str | None:
    """Persist a record and prune history. Best-effort: never raises (SC-002)."""
    try:
        os.makedirs(runs_dir, exist_ok=True)
        path = os.path.join(runs_dir, f"{record['id']}.json")
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(record, fh, indent=2)
            fh.write("\n")
        names = sorted(n for n in os.listdir(runs_dir) if n.endswith(".json"))
        for stale in names[:-retention] if retention > 0 else []:
            os.unlink(os.path.join(runs_dir, stale))
        return path
    except OSError:
        return None


def list_runs(runs_dir: str) -> list[dict]:
    """Newest-first lightweight summaries of retained runs."""
    try:
        names = sorted((n for n in os.listdir(runs_dir) if n.endswith(".json")),
                       reverse=True)
    except OSError:
        return []
    out = []
    for name in names:
        try:
            with open(os.path.join(runs_dir, name), encoding="utf-8") as fh:
                rec = json.load(fh)
        except (OSError, ValueError):
            continue
        statuses = [r["status"] for r in rec.get("results", [])]
        out.append({"id": rec.get("id", name[:-5]), "event": rec.get("event"),
                    "timestamp": rec.get("timestamp"),
                    "final_outcome": rec.get("final_outcome"),
                    "ok": statuses.count("success"),
                    "not_ok": len(statuses) - statuses.count("success")})
    return out


def load_run(runs_dir: str, run_id: str) -> dict | None:
    path = os.path.join(runs_dir, f"{run_id}.json")
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def _render(record: dict) -> str:
    lines = [
        f"run      {record['id']}",
        f"event    {record['event']}  branch {record['branch']}  at {record['timestamp']}",
        f"context  files={record['context_summary']['files']} "
        f"commits={record['context_summary']['commits']} "
        f"partial={record['context_summary']['partial']}",
        f"outcome  {record['final_outcome'].upper()}"
        + ("  (block downgraded)" if record.get("block_downgraded") else ""),
        "",
    ]
    if not record["results"]:
        lines.append("no skills ran (empty plan)")
    for r in record["results"]:
        rule = json.dumps(r["rule"]) if r["rule"] else "default"
        lines.append(f"- {r['skill']}: {r['status']} ({r['duration_ms']}ms) "
                     f"-> {r['outcome']}  [rule: {rule}]")
        lines.append(f"    {r['reason']}")
        if r["detail"]:
            lines.append(f"    detail: {r['detail']}")
    if record.get("warnings"):
        lines.append("")
        lines.extend(f"warning: {w}" for w in record["warnings"])
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--runs-dir", default=DEFAULT_RUNS_DIR)
    parser = argparse.ArgumentParser(description="Automation run history")
    sub = parser.add_subparsers(dest="command", required=True)
    p_list = sub.add_parser("list", parents=[common])
    p_list.add_argument("--limit", type=int, default=20)
    p_show = sub.add_parser("show", parents=[common])
    p_show.add_argument("run_id", nargs="?")
    p_show.add_argument("--last", action="store_true")
    args = parser.parse_args(argv)

    if args.command == "list":
        for run in list_runs(args.runs_dir)[:args.limit]:
            print(f"{run['id']}  {run['event']}  {run['final_outcome']}  "
                  f"ok={run['ok']} fail={run['not_ok']}")
        return 0

    # show
    if args.last:
        runs = list_runs(args.runs_dir)
        if not runs:
            print("no runs recorded", file=sys.stderr)
            return 1
        record = load_run(args.runs_dir, runs[0]["id"])
    elif args.run_id:
        record = load_run(args.runs_dir, args.run_id)
    else:
        print("show requires a run id or --last", file=sys.stderr)
        return 1
    if record is None:
        print("run not found", file=sys.stderr)
        return 1
    print(_render(record))
    return 0


if __name__ == "__main__":
    sys.exit(main())
