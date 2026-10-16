#!/usr/bin/env python3
"""Skill executor (feature 006, declarative skills since 009).

Runs an ordered plan of registered skills. A skill is a prompt (contract
v2.0): for each one the executor asks Claude — through the read-only bridge —
for a {verdict, reason, report}, and the framework writes the report to
_aioutput/<skill>/. Sync skills run inline, each bounded by its time budget
and all of them together by the sync ceiling; async skills are handed to one
detached worker process (src/async_worker.py) so the git operation never
waits for them. Produces an ExecutionSummary and never raises. Contracts:
specs/006-skill-executor/contracts/execution-summary.md,
specs/009-aioutput-skills/contracts/execution-and-output.md
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone

import ai_output
from claude_bridge import DEFAULT_CONFIG as BRIDGE_DEFAULTS
from claude_bridge import invoke as bridge_invoke
from claude_bridge import load_bridge_config
from skill_registry import MANIFEST_FILE, PROMPT_FILE, validate_manifest

SUMMARY_SCHEMA_VERSION = "2.0"
# Terminal states of a skill run. "skipped" = never started (unregistered or
# invalid); "failure" = Claude ran and judged the change bad (verdict fail);
# "error" = Claude could not give a usable verdict, or the result could not be
# written; async skills end the dispatching run as "dispatched".
STATUSES = ("success", "failure", "error", "timeout", "skipped",
            "dispatched", "dispatch-failed")
MODES = ("sync", "async")
DEFAULT_MODE = "async"          # never delays and never blocks git
DEFAULT_BUDGET_SECONDS = 60.0   # applies unless the manifest overrides it
MAX_BUDGET_SECONDS = 600        # ceiling — a skill may not hold git hostage
DEFAULT_SYNC_CEILING = 120.0    # all sync skills of one run, together
JOB_SCHEMA_VERSION = "1.0"
WORKER = os.path.join(os.path.dirname(os.path.abspath(__file__)), "async_worker.py")


def _resolve(skills_dir: str, identifier: str) -> tuple[dict | None, str]:
    """Turn a routed identifier into {dir, manifest, prompt}, or (None, why).

    Resolution goes through skills/registry.json only: a directory on disk
    that was never registered is not runnable. The skill is re-validated here
    too — a skill edited after registration (say, a script dropped into it)
    must not run.
    """
    try:
        with open(os.path.join(skills_dir, "registry.json"), encoding="utf-8") as fh:
            entries = json.load(fh).get("skills", {})
    except FileNotFoundError:
        entries = {}  # no registry yet = nothing registered, not an error
    except (OSError, ValueError, AttributeError) as exc:
        return None, f"skill registry unreadable: {exc}"
    entry = entries.get(identifier) if isinstance(entries, dict) else None
    if not isinstance(entry, dict):
        return None, f"'{identifier}' not registered"
    skill_dir = os.path.join(skills_dir, entry.get("dir", identifier))
    violations = validate_manifest(skill_dir)
    if violations:
        return None, f"'{identifier}' no longer valid: {'; '.join(violations)}"
    with open(os.path.join(skill_dir, MANIFEST_FILE), encoding="utf-8") as fh:
        manifest = json.load(fh)
    with open(os.path.join(skill_dir, PROMPT_FILE), encoding="utf-8") as fh:
        prompt = fh.read().strip()
    return {"dir": skill_dir, "manifest": manifest, "prompt": prompt}, ""


def budget_of(manifest: dict, default_budget: float = DEFAULT_BUDGET_SECONDS) -> float:
    """Per-skill time budget from its manifest, else the default. Pure."""
    declared = manifest.get("time_budget_seconds")
    if (isinstance(declared, (int, float)) and not isinstance(declared, bool)
            and 0 < declared <= MAX_BUDGET_SECONDS):
        return float(declared)
    return default_budget


def classify(bridge_result: dict) -> tuple[str, str]:
    """Bridge result → (executor status, detail). Pure.

    Only a usable verdict maps to success/failure; everything else is error
    or timeout, which can never block (R6).
    """
    status = bridge_result.get("status")
    if status == "ok":
        verdict = bridge_result.get("verdict")
        reason = bridge_result.get("reason", "")
        return ("failure" if verdict == "fail" else "success"), reason
    if status == "timeout":
        return "timeout", bridge_result.get("error", "")
    return "error", f"{status}: {bridge_result.get('error', '')}"


def run_skill(identifier: str, context: dict, *, skills_dir: str, root: str,
              mode: str, timeout_cap: float | None, run_id: str,
              bridge_config: dict, output_retention: int,
              bridge=bridge_invoke) -> dict:
    """Run one skill end to end: resolve → Claude → result file. Never raises.

    Every exit path goes through done(), so each skill always yields exactly
    one result entry with a duration.
    """
    started = time.monotonic()

    def done(status: str, detail: str, verdict=None, output_file=None) -> dict:
        return {"skill": identifier, "mode": mode, "status": status,
                "verdict": verdict, "output_file": output_file,
                "duration_ms": int((time.monotonic() - started) * 1000),
                "detail": detail}

    try:
        skill, detail = _resolve(skills_dir, identifier)
    except (OSError, ValueError) as exc:
        skill, detail = None, f"cannot read skill '{identifier}': {exc}"
    if skill is None:
        return done("skipped", detail)  # unresolvable ≠ failed

    budget = budget_of(skill["manifest"])
    timeout = budget if timeout_cap is None else min(budget, timeout_cap)
    if timeout <= 0:
        return done("timeout", "sync ceiling exhausted before the skill could start")

    try:
        result = bridge({"schema_version": "2.0", "context": context,
                         "task": skill["prompt"], "root": root,
                         "options": {"timeout_seconds": timeout}},
                        bridge_config)
    except Exception as exc:  # the bridge promises not to raise; belt and braces
        result = {"status": "error", "error": f"bridge failure: {exc}"}
    status, detail = classify(result)

    # A report is worth keeping even without a verdict — it may explain why.
    report = result.get("report") or ""
    if not report:
        return done(status, detail)
    verdict = result.get("verdict") or "invalid"
    meta = {"skill": identifier,
            "skill_version": skill["manifest"].get("version"),
            "event": context.get("event"), "branch": context.get("branch"),
            "mode": mode, "verdict": verdict,
            "reason": result.get("reason", ""), "run_id": run_id,
            "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "files": context.get("files") or []}
    try:
        output_file = ai_output.write_result(root, identifier, meta, report)
        ai_output.prune(root, identifier, output_retention)
    except (OSError, ValueError) as exc:
        # The verdict is still trusted for blocking only if we could keep the
        # evidence; an unwritable _aioutput degrades the skill to error.
        return done("error", f"result not written: {exc}", verdict)
    return done(status, detail, verdict, output_file)


def detach_kwargs(platform: str = os.name) -> dict:
    """Popen kwargs that let the worker outlive the git hook. Pure.

    Verified in the 009 T0 spike: dispatch ~10 ms, child survives the hook.
    """
    kwargs = {"stdin": subprocess.DEVNULL, "stdout": subprocess.DEVNULL,
              "stderr": subprocess.DEVNULL, "close_fds": True}
    if platform == "nt":
        kwargs["creationflags"] = (getattr(subprocess, "DETACHED_PROCESS", 0x8)
                                   | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x200)
                                   | getattr(subprocess, "CREATE_NO_WINDOW", 0x8000000))
    else:
        kwargs["start_new_session"] = True
    return kwargs


def dispatch_async(job: dict, jobs_dir: str, spawn=subprocess.Popen,
                   platform: str = os.name) -> tuple[bool, str, str | None]:
    """Write the job file and start the detached worker; don't wait.

    Returns (started, detail, job_path). A job file instead of a stdin pipe:
    holding a pipe across a detached boundary is unreliable on Windows.
    """
    try:
        os.makedirs(jobs_dir, exist_ok=True)
        job_path = os.path.join(jobs_dir, f"{job['run_id']}.json")
        with open(job_path, "w", encoding="utf-8") as fh:
            json.dump(job, fh)
    except OSError as exc:
        return False, f"job file not written: {exc}", None
    try:
        # sys.executable: the interpreter orchestrate.sh already probed — never
        # the Windows Store `python3` stub.
        spawn([sys.executable, WORKER, job_path], **detach_kwargs(platform))
    except Exception as exc:
        return False, f"worker not started: {exc}", job_path
    return True, "", job_path


def execute_plan(plan: list[str], context: dict, *, skills_dir: str, root: str,
                 run_id: str, modes: dict | None = None,
                 sync_ceiling: float = DEFAULT_SYNC_CEILING,
                 bridge_config: dict | None = None,
                 output_retention: int = ai_output.DEFAULT_OUTPUT_RETENTION,
                 jobs_dir: str | None = None, runs_dir: str | None = None,
                 log_path: str | None = None, outcome_rules: dict | None = None,
                 run_retention: int | None = None,
                 bridge=bridge_invoke, dispatch=dispatch_async,
                 clock=time.monotonic) -> dict:
    """Dispatch the async part of the plan, then run the sync part in order.

    Async first, so a slow sync skill never delays the start of the async
    ones. Sync skills run sequentially, each capped by the time left in the
    sync ceiling; once it is spent the rest are "timeout" without a call.
    """
    started = clock()
    modes = modes or {}
    bridge_config = bridge_config or dict(BRIDGE_DEFAULTS)
    mode_of = {s: (modes.get(s) if modes.get(s) in MODES else DEFAULT_MODE)
               for s in plan}
    async_plan = [s for s in plan if mode_of[s] == "async"]
    results_by_skill: dict[int, dict] = {}
    async_job = None

    if async_plan:
        job = {"schema_version": JOB_SCHEMA_VERSION, "run_id": run_id,
               "context": context, "plan": async_plan, "skills_dir": skills_dir,
               "root": root, "bridge_config": bridge_config,
               "output_retention": output_retention, "runs_dir": runs_dir,
               "run_retention": run_retention, "log": log_path,
               "outcome_rules": outcome_rules or {}}
        ok, detail, async_job = dispatch(job, jobs_dir or os.path.join(root, "logs", "async"))
        for i, s in enumerate(plan):
            if mode_of[s] == "async":
                results_by_skill[i] = {
                    "skill": s, "mode": "async",
                    "status": "dispatched" if ok else "dispatch-failed",
                    "verdict": None, "output_file": None, "duration_ms": 0,
                    "detail": detail or f"handed to async worker ({async_job})"}

    for i, s in enumerate(plan):
        if mode_of[s] != "sync":
            continue
        remaining = sync_ceiling - (clock() - started)
        results_by_skill[i] = run_skill(
            s, context, skills_dir=skills_dir, root=root, mode="sync",
            timeout_cap=remaining, run_id=run_id, bridge_config=bridge_config,
            output_retention=output_retention, bridge=bridge)

    results = [results_by_skill[i] for i in range(len(plan))]
    return {"schema_version": SUMMARY_SCHEMA_VERSION,
            "event": context.get("event"),
            "overall": summarize(results),
            "duration_ms": int((clock() - started) * 1000),
            "results": results, "async_job": async_job}


def summarize(results: list[dict]) -> str:
    """Human/log summary; the outcome rules (008) are what decide blocking."""
    if not results:
        return "empty"
    good = [r["status"] in ("success", "dispatched") for r in results]
    if all(good):
        return "success"
    return "partial-failure" if any(good) else "failure"


def main(argv: list[str] | None = None) -> int:
    """CLI (debugging aid): context JSON on stdin + plan as args -> summary.

    Every skill runs sync here — this entry point exists to try a skill by
    hand and see its verdict, not to dispatch work in the background.
    """
    parser = argparse.ArgumentParser(
        description="Execute an ordered plan of registered skills (sync)")
    parser.add_argument("plan", nargs="*", help="skill identifiers, in order")
    parser.add_argument("--skills-dir", default="skills")
    parser.add_argument("--root", default=".")
    parser.add_argument("--sync-ceiling", type=float, default=MAX_BUDGET_SECONDS)
    args = parser.parse_args(argv)

    try:
        context = json.load(sys.stdin)
        if not isinstance(context, dict):
            raise ValueError("context must be a JSON object")
        plan = list(args.plan)
    except Exception as exc:
        print(f"[executor warning] unreadable context on stdin: {exc}",
              file=sys.stderr)
        context, plan = {"event": None}, []

    warnings: list[str] = []
    bridge_config = load_bridge_config(
        os.path.join(args.root, "config", "bridge.json"), warnings)
    for w in warnings:
        print(f"[executor warning] {w}", file=sys.stderr)
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ") + "-manual"
    summary = execute_plan(plan, context, skills_dir=args.skills_dir,
                           root=args.root, run_id=run_id,
                           modes={s: "sync" for s in plan},
                           sync_ceiling=args.sync_ceiling,
                           bridge_config=bridge_config)
    json.dump(summary, sys.stdout)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
