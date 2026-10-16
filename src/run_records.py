#!/usr/bin/env python3
"""Run observability and outcome enforcement (feature 008, modes since 009).

Evaluates block/warn/skip outcomes for every skill result (default: warn —
safe by default, FR-009), writes a run record for every automation run to
logs/runs/, and provides the run-history CLI. Contract:
specs/008-run-observability/contracts/run-record.md,
specs/009-aioutput-skills/contracts/execution-and-output.md
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone

RECORD_SCHEMA_VERSION = "1.1"
# Reserved exit code: the ONLY value that makes a git hook abort the operation.
# Router returns it; _finish_hook in scripts/lib.sh translates it (see 002).
BLOCK_EXIT_CODE = 10
OUTCOMES = ("block", "warn", "skip")  # routes.json → skills.<name>.on_failure
DEFAULT_RETENTION = 50                # run records kept before pruning oldest
DEFAULT_RUNS_DIR = "logs/runs"
# post-merge is excluded: the merge has already happened, so blocking it would
# be theatre — such rules are downgraded to warn instead.
BLOCKABLE_EVENTS = ("pre-commit", "pre-push")


def evaluate_outcomes(summary: dict, outcome_rules: dict, event: str) -> dict:
    """Map each execution result to an outcome per the configured rules.

    The safety rules of features 008 and 009, in one place:
      * success / dispatched → "none"
      * no/invalid rule      → "warn" (FR-009, safe by default)
      * failure              → block / warn / skip as configured — the only
                               status that can block (Claude judged the change)
      * error / timeout / skipped / dispatch-failed → warn, or skip if so
                               configured; a block rule is downgraded, because
                               a tooling problem must never stop git (009 R6)
      * block on an async skill → warn: the git operation is long gone
      * block on post-merge  → downgraded to warn, flagged block_downgraded
      * run's final outcome  → the strongest of them: block > warn > none

    Pure function: no I/O, no side effects — which is what makes the whole
    block/warn/skip matrix cheap to test exhaustively.
    """
    results: list[dict] = []
    notes: list[str] = []   # config problems, surfaced but never fatal
    block_downgraded = False

    for r in summary.get("results", []):
        skill, status = r["skill"], r["status"]
        mode = r.get("mode", "sync")
        rule = outcome_rules.get(skill) if isinstance(outcome_rules, dict) else None
        if not isinstance(rule, dict):
            rule = None

        if status in ("success", "dispatched"):
            outcome = "none"
            reason = "skill succeeded" if status == "success" else "handed to async worker"
        else:
            requested = rule.get("on_failure") if rule else None
            if requested in OUTCOMES:
                outcome = requested
                reason = (f"rule {skill}.on_failure={requested} "
                          f"matched status '{status}'")
            else:
                # A rule that sets on_failure to garbage is worth a note; no
                # rule (or a rule with only a mode) is the normal case.
                if rule is not None and "on_failure" in rule:
                    notes.append(f"invalid outcome rule for '{skill}' "
                                 f"({requested!r}) — defaulting to warn")
                outcome = "warn"
                reason = f"no valid rule for '{skill}' — default warn on status '{status}'"
            if outcome == "block":
                if status != "failure":
                    outcome, block_downgraded = "warn", True
                    reason += f" (block not applied: cannot block on '{status}')"
                elif mode != "sync":
                    outcome, block_downgraded = "warn", True
                    reason += " (block not applied: async skills never block)"
                elif event not in BLOCKABLE_EVENTS:
                    outcome, block_downgraded = "warn", True
                    reason += f" (block downgraded to warn: '{event}' already completed)"

        results.append({"skill": skill, "mode": mode, "status": status,
                        "verdict": r.get("verdict"),
                        "output_file": r.get("output_file"),
                        "duration_ms": r.get("duration_ms", 0),
                        "detail": r.get("detail", ""),
                        "rule": rule, "outcome": outcome, "reason": reason})

    # Strongest outcome wins; "skip" records the failure but stays silent.
    if any(r["outcome"] == "block" for r in results):
        final = "block"
    elif any(r["outcome"] == "warn" for r in results):
        final = "warn"
    else:
        final = "none"

    return {"results": results, "final_outcome": final,
            "block_downgraded": block_downgraded, "notes": notes}


def new_run_id(event, now: datetime | None = None) -> str:
    """A run id: UTC timestamp first, so ids sort lexically in chronological
    order — which is what makes listing and pruning a plain sorted()."""
    now = now or datetime.now(timezone.utc)
    return f"{now.strftime('%Y%m%dT%H%M%S.%f')}Z-{event}"


def build_run_record(context: dict, plan: list[str], summary: dict,
                     evaluation: dict, warnings: list[str],
                     run_id: str | None = None,
                     parent_run: str | None = None) -> dict:
    """Assemble the run-record@1.1 document for one automation run.

    run_id is passed in when the id was needed before the run finished (it
    names the async job and goes into every result file); parent_run marks
    an async worker's record and points back at the run that dispatched it.

    Also pure: building the record and writing it are separate so a full record
    can be asserted in tests without touching the filesystem.
    """
    now = datetime.now(timezone.utc)
    event = context.get("event")
    record = {
        "schema_version": RECORD_SCHEMA_VERSION,
        "id": run_id or new_run_id(event, now),
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
        "async_job": summary.get("async_job"),
    }
    if parent_run:
        record["parent_run"] = parent_run
    return record


def write_run_record(runs_dir: str, record: dict,
                     retention: int = DEFAULT_RETENTION) -> str | None:
    """Persist a record and prune history. Best-effort: never raises (SC-002).

    Returns the path written, or None if the write failed. Observability must
    never be able to break the git operation it is observing, so an unwritable
    logs/runs/ is reported, not raised.
    """
    try:
        os.makedirs(runs_dir, exist_ok=True)
        path = os.path.join(runs_dir, f"{record['id']}.json")
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(record, fh, indent=2)
            fh.write("\n")
        # Prune oldest-first: names sort chronologically (see the id format).
        names = sorted(n for n in os.listdir(runs_dir) if n.endswith(".json"))
        for stale in names[:-retention] if retention > 0 else []:
            os.unlink(os.path.join(runs_dir, stale))
        return path
    except OSError:
        return None


def list_runs(runs_dir: str) -> list[dict]:
    """Newest-first lightweight summaries of retained runs.

    Unreadable or corrupt record files are skipped rather than aborting the
    listing — one bad file must not hide the rest of the history.
    """
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
        ok = sum(s in ("success", "dispatched") for s in statuses)
        out.append({"id": rec.get("id", name[:-5]), "event": rec.get("event"),
                    "timestamp": rec.get("timestamp"),
                    "final_outcome": rec.get("final_outcome"),
                    "ok": ok, "not_ok": len(statuses) - ok})
    return out


def load_run(runs_dir: str, run_id: str) -> dict | None:
    """Read one full record by id; None when missing or unparseable."""
    path = os.path.join(runs_dir, f"{run_id}.json")
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def _render(record: dict) -> str:
    """Format a record for `show`: what ran, what happened, and why (FR-002).

    Every skill line carries status, duration, the rule that applied, the
    outcome, and the reason — so an unexpected block can be diagnosed from the
    record alone, without re-running the automation.
    """
    lines = [
        f"run      {record['id']}",
        f"event    {record['event']}  branch {record['branch']}  at {record['timestamp']}",
        f"context  files={record['context_summary']['files']} "
        f"commits={record['context_summary']['commits']} "
        f"partial={record['context_summary']['partial']}",
        f"outcome  {record['final_outcome'].upper()}"
        + ("  (block downgraded)" if record.get("block_downgraded") else ""),
    ]
    if record.get("parent_run"):
        lines.append(f"async    worker for run {record['parent_run']}")
    if record.get("async_job"):
        lines.append(f"async    dispatched job {record['async_job']}")
    lines.append("")
    if not record["results"]:
        lines.append("no skills ran (empty plan)")
    for r in record["results"]:
        rule = json.dumps(r["rule"]) if r["rule"] else "default"
        verdict = f" verdict={r['verdict']}" if r.get("verdict") else ""
        lines.append(f"- {r['skill']} [{r.get('mode', 'sync')}]: {r['status']}{verdict} "
                     f"({r['duration_ms']}ms) -> {r['outcome']}  [rule: {rule}]")
        lines.append(f"    {r['reason']}")
        if r.get("output_file"):
            lines.append(f"    output: {r['output_file']}")
        if r["detail"]:
            lines.append(f"    detail: {r['detail']}")
    if record.get("warnings"):
        lines.append("")
        lines.extend(f"warning: {w}" for w in record["warnings"])
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    """CLI: `list [--limit N]` and `show <run-id>|--last`."""
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
