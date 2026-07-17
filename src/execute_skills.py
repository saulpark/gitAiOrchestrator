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
STATUSES = ("success", "failure", "timeout", "skipped")
DEFAULT_BUDGET_SECONDS = 30.0
MAX_BUDGET_SECONDS = 600


def _resolve(skills_dir: str, identifier: str) -> tuple[str | None, str]:
    """Return (skill_dir, detail). skill_dir None → skipped with detail."""
    try:
        with open(os.path.join(skills_dir, "registry.json"), encoding="utf-8") as fh:
            entries = json.load(fh).get("skills", {})
    except FileNotFoundError:
        entries = {}
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
    try:
        with open(os.path.join(skill_dir, "skill.json"), encoding="utf-8") as fh:
            declared = json.load(fh).get("time_budget_seconds")
        if isinstance(declared, (int, float)) and 0 < declared <= MAX_BUDGET_SECONDS:
            return float(declared)
    except (OSError, ValueError):
        pass
    return default_budget


def _parse_result(stdout: str) -> dict | None:
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
    started = time.monotonic()

    def done(status: str, detail: str, result: dict | None = None) -> dict:
        return {"skill": identifier, "status": status,
                "duration_ms": int((time.monotonic() - started) * 1000),
                "detail": detail, "result": result}

    skill_dir, detail = _resolve(skills_dir, identifier)
    if skill_dir is None:
        return done("skipped", detail)

    budget = _budget(skill_dir, default_budget)
    try:
        proc = subprocess.run(
            [os.path.join(skill_dir, "run")], input=context_json, text=True,
            capture_output=True, timeout=budget,
        )
    except subprocess.TimeoutExpired:
        return done("timeout", f"exceeded time budget ({budget:g}s)")
    except Exception as exc:  # FR-003: one skill's crash never stops the plan
        return done("failure", f"executor error: {exc}")

    if proc.returncode != 0:
        return done("failure",
                    f"exit {proc.returncode}: {proc.stderr.strip()[:200]}")
    result = _parse_result(proc.stdout)
    if result is None:
        return done("failure",
                    "malformed output (not skill-result@1.0 JSON): "
                    f"{proc.stdout.strip()[:120]}")
    return done("success", str(result.get("summary", "")), result)


def execute_plan(plan: list[str], context: dict, skills_dir: str,
                 default_budget: float = DEFAULT_BUDGET_SECONDS) -> dict:
    started = time.monotonic()
    context_json = json.dumps(context)
    results = [_run_one(identifier, context_json, skills_dir, default_budget)
               for identifier in plan]

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
