#!/usr/bin/env python3
"""Async skill worker (feature 009).

Started detached by execute_skills.dispatch_async with the path of a job
file; by the time it runs, the git operation that triggered it has usually
finished. Runs each async skill of the job through the same code path as a
sync skill (run_skill), writes its own run record `<parent-id>-async`, one
logs/hooks.log line per skill, then deletes the job file. Nothing it does can
reach the developer's terminal or the git exit code — its stdio is /dev/null —
so every problem is recorded instead. Contract:
specs/009-aioutput-skills/contracts/execution-and-output.md
"""
from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime, timezone

from claude_bridge import DEFAULT_CONFIG as BRIDGE_DEFAULTS
from claude_bridge import invoke as bridge_invoke
from execute_skills import JOB_SCHEMA_VERSION, run_skill, summarize
from run_records import (
    DEFAULT_RETENTION,
    build_run_record,
    evaluate_outcomes,
    write_run_record,
)


def _default_runs_dir(job_path: str) -> str:
    # Jobs live in <root>/logs/async/, records in <root>/logs/runs/ — usable
    # even when the job itself could not be read.
    return os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(job_path))), "runs")


def load_job(job_path: str) -> tuple[dict | None, str]:
    """Read and sanity-check a job file → (job, "") or (None, why)."""
    try:
        with open(job_path, encoding="utf-8") as fh:
            job = json.load(fh)
    except (OSError, ValueError) as exc:
        return None, f"job file unreadable: {exc}"
    if not isinstance(job, dict):
        return None, "job file is not a JSON object"
    if job.get("schema_version") != JOB_SCHEMA_VERSION:
        return None, f"unsupported job schema {job.get('schema_version')!r}"
    missing = [k for k in ("run_id", "context", "plan", "skills_dir", "root")
               if k not in job]
    if missing:
        return None, f"job file missing {', '.join(missing)}"
    if not isinstance(job["context"], dict) or not isinstance(job["plan"], list):
        return None, "job file has a malformed context or plan"
    return job, ""


def run_job(job: dict, bridge=bridge_invoke) -> tuple[dict, dict]:
    """Run every skill of the job in order → (summary, evaluation).

    No sync ceiling here: nobody is waiting, so each skill gets its own
    budget in full (timeout_cap=None).
    """
    started = time.monotonic()
    results = [run_skill(s, job["context"], skills_dir=job["skills_dir"],
                         root=job["root"], mode="async", timeout_cap=None,
                         run_id=job["run_id"],
                         bridge_config=job.get("bridge_config") or dict(BRIDGE_DEFAULTS),
                         output_retention=job.get("output_retention") or 0,
                         bridge=bridge)
               for s in job["plan"]]
    summary = {"schema_version": "2.0", "event": job["context"].get("event"),
               "overall": summarize(results),
               "duration_ms": int((time.monotonic() - started) * 1000),
               "results": results, "async_job": None}
    evaluation = evaluate_outcomes(summary, job.get("outcome_rules") or {},
                                   job["context"].get("event"))
    return summary, evaluation


def log_lines(run_id: str, evaluation: dict, now: datetime) -> list[str]:
    """One hooks.log line per skill. Pure."""
    stamp = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    return [f"[{stamp}] async run={run_id} skill={r['skill']} status={r['status']} "
            f"verdict={r.get('verdict') or '-'} outcome={r['outcome']} "
            f"output={r.get('output_file') or '-'}\n"
            for r in evaluation["results"]]


def _append_log(log_path: str | None, lines: list[str]) -> None:
    if not log_path:
        return
    try:
        os.makedirs(os.path.dirname(log_path) or ".", exist_ok=True)
        with open(log_path, "a", encoding="utf-8") as fh:
            fh.writelines(lines)
    except OSError:
        pass  # logging must never be the thing that fails


def main(argv: list[str] | None = None, bridge=bridge_invoke) -> int:
    """Entry point: `async_worker.py <job.json>`. Always exits 0."""
    argv = sys.argv[1:] if argv is None else argv
    if not argv:
        return 0
    job_path = argv[0]
    job, error = load_job(job_path)

    if job is None:
        # Leave a trace of the failure: a record with the error as warning.
        empty = {"results": [], "duration_ms": 0}
        record = build_run_record({"event": None}, [], empty,
                                  evaluate_outcomes(empty, {}, None), [error],
                                  run_id=f"{os.path.splitext(os.path.basename(job_path))[0]}-async")
        write_run_record(_default_runs_dir(job_path), record)
        return 0

    try:
        summary, evaluation = run_job(job, bridge)
        warnings: list[str] = []
    except Exception as exc:  # defensive: run_skill never raises by contract
        summary = {"results": [], "duration_ms": 0}
        evaluation = evaluate_outcomes(summary, {}, job["context"].get("event"))
        warnings = [f"async worker failure: {exc}"]
    record = build_run_record(job["context"], job["plan"], summary, evaluation,
                              warnings, run_id=f"{job['run_id']}-async",
                              parent_run=job["run_id"])
    write_run_record(job.get("runs_dir") or _default_runs_dir(job_path), record,
                     job.get("run_retention") or DEFAULT_RETENTION)
    # Stamped at write time: the lines must sort after the dispatching run's.
    _append_log(job.get("log"), log_lines(job["run_id"], evaluation,
                                          datetime.now(timezone.utc)))
    try:
        os.remove(job_path)
    except OSError:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
