#!/usr/bin/env python3
"""Skill executor (feature 006).

Runs an ordered execution plan of registered skills: each gets the unmodified
hook context on stdin, bounded by its time budget, with per-skill failure
isolation. Produces an ExecutionSummary and always exits 0. Contract:
specs/006-skill-executor/contracts/execution-summary.md
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time

SUMMARY_SCHEMA_VERSION = "1.0"
# The four terminal states of a skill run. "skipped" means the skill never
# started (not registered / no executable); "failure" means it ran and failed.
STATUSES = ("success", "failure", "timeout", "skipped")
DEFAULT_BUDGET_SECONDS = 30.0   # applies unless the manifest overrides it
MAX_BUDGET_SECONDS = 600        # ceiling — a skill may not hold git hostage


def _resolve(skills_dir: str, identifier: str) -> tuple[str | None, str]:
    """Turn a routed identifier into a runnable directory.

    Returns (skill_dir, detail). skill_dir None → the skill is "skipped" and
    detail explains why. Resolution goes through skills/registry.json only:
    a directory that exists on disk but was never registered is not runnable
    (feature 005 owns what counts as a valid skill).
    """
    try:
        with open(os.path.join(skills_dir, "registry.json"), encoding="utf-8") as fh:
            entries = json.load(fh).get("skills", {})
    except FileNotFoundError:
        entries = {}  # no registry yet = nothing registered, not an error
    except (OSError, ValueError) as exc:
        return None, f"skill registry unreadable: {exc}"
    entry = entries.get(identifier) if isinstance(entries, dict) else None
    if not isinstance(entry, dict):
        return None, f"'{identifier}' not registered"
    skill_dir = os.path.join(skills_dir, entry.get("dir", identifier))
    run_path = os.path.join(skill_dir, "run")
    if not (os.path.isfile(run_path) and os.access(run_path, os.X_OK)):
        return None, f"no executable at {run_path}"
    return skill_dir, ""


def _budget(skill_dir: str, default_budget: float) -> float:
    """Per-skill time budget from its manifest, else the default.

    Re-read from skill.json at run time (not from the registry) so editing a
    budget takes effect without re-registering. Anything unreadable, absurd,
    or out of range silently falls back to the default.
    """
    try:
        with open(os.path.join(skill_dir, "skill.json"), encoding="utf-8") as fh:
            declared = json.load(fh).get("time_budget_seconds")
        if isinstance(declared, (int, float)) and 0 < declared <= MAX_BUDGET_SECONDS:
            return float(declared)
    except (OSError, ValueError):
        pass
    return default_budget


def _parse_result(stdout: str) -> dict | None:
    """Accept stdout only if it is a skill-result@1.0 object, else None.

    Deliberately shallow: the three keys below are what the executor itself
    needs. Anything richer is the consuming skill's business.
    """
    try:
        result = json.loads(stdout)
        if (isinstance(result, dict) and "schema_version" in result
                and "skill" in result and "status" in result):
            return result
    except ValueError:
        pass
    return None


def _run_one(identifier: str, context_json: str, skills_dir: str,
             default_budget: float) -> dict:
    """Run one skill in its own subprocess and classify the outcome.

    Every exit path goes through done(), so each skill always yields exactly
    one result entry with a duration — never an exception to the caller.
    """
    started = time.monotonic()  # monotonic: immune to clock changes mid-run

    def done(status: str, detail: str, result: dict | None = None) -> dict:
        return {"skill": identifier, "status": status,
                "duration_ms": int((time.monotonic() - started) * 1000),
                "detail": detail, "result": result}

    skill_dir, detail = _resolve(skills_dir, identifier)
    if skill_dir is None:
        return done("skipped", detail)  # unresolvable ≠ failed

    budget = _budget(skill_dir, default_budget)
    try:
        # The skill gets the context on stdin, unmodified — same bytes every
        # skill sees, so runs stay reproducible and comparable.
        proc = subprocess.run(
            [os.path.join(skill_dir, "run")], input=context_json, text=True,
            capture_output=True, timeout=budget,
        )
    except subprocess.TimeoutExpired:
        return done("timeout", f"exceeded time budget ({budget:g}s)")
    except Exception as exc:  # FR-003: one skill's crash never stops the plan
        return done("failure", f"executor error: {exc}")

    if proc.returncode != 0:
        # stderr is truncated: it lands in a run record meant to stay readable.
        return done("failure",
                    f"exit {proc.returncode}: {proc.stderr.strip()[:200]}")
    result = _parse_result(proc.stdout)
    if result is None:
        # Exit 0 but unusable output is still a failure — a skill that cannot
        # be understood cannot be trusted to have done its job.
        return done("failure",
                    "malformed output (not skill-result@1.0 JSON): "
                    f"{proc.stdout.strip()[:120]}")
    return done("success", str(result.get("summary", "")), result)


def execute_plan(plan: list[str], context: dict, skills_dir: str,
                 default_budget: float = DEFAULT_BUDGET_SECONDS) -> dict:
    """Run the whole plan in order and summarize it (execution-summary@1.0).

    Sequential by design: skills may touch the working tree, so running them
    concurrently would make outcomes order-dependent and irreproducible.
    """
    started = time.monotonic()
    context_json = json.dumps(context)  # serialized once, shared by all skills
    results = [_run_one(identifier, context_json, skills_dir, default_budget)
               for identifier in plan]

    # "overall" is a summary for humans and logs; the per-skill outcome rules
    # in feature 008 are what actually decide block/warn/skip.
    if not results:
        overall = "empty"
    elif all(r["status"] == "success" for r in results):
        overall = "success"
    elif any(r["status"] == "success" for r in results):
        overall = "partial-failure"
    else:
        overall = "failure"

    return {
        "schema_version": SUMMARY_SCHEMA_VERSION,
        "event": context.get("event"),
        "overall": overall,
        "duration_ms": int((time.monotonic() - started) * 1000),
        "results": results,
    }


def main(argv: list[str] | None = None) -> int:
    """CLI: context JSON on stdin + plan as args -> summary JSON on stdout."""
    parser = argparse.ArgumentParser(
        description="Execute an ordered plan of registered skills")
    parser.add_argument("plan", nargs="*", help="skill identifiers, in order")
    parser.add_argument("--skills-dir", default="skills")
    parser.add_argument("--default-budget", type=float,
                        default=DEFAULT_BUDGET_SECONDS)
    args = parser.parse_args(argv)

    try:
        context = json.load(sys.stdin)
        if not isinstance(context, dict):
            raise ValueError("context must be a JSON object")
        plan = list(args.plan)
    except Exception as exc:  # FR-007: never abort the git operation
        print(f"[executor warning] unreadable context on stdin: {exc}",
              file=sys.stderr)
        context, plan = {"event": None}, []

    try:
        summary = execute_plan(plan, context, args.skills_dir,
                               args.default_budget)
    except Exception as exc:
        # The executor itself broke: still emit a well-formed summary marking
        # every planned skill failed, so the router has something to record.
        summary = {"schema_version": SUMMARY_SCHEMA_VERSION,
                   "event": context.get("event"), "overall": "failure",
                   "duration_ms": 0,
                   "results": [{"skill": s, "status": "failure", "duration_ms": 0,
                                "detail": f"executor failure: {exc}", "result": None}
                               for s in plan]}
    json.dump(summary, sys.stdout)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
