#!/usr/bin/env python3
"""Workflow router (feature 004).

Reads a hook context (003 schema) on stdin, loads config/routes.json fresh on
every invocation, and dispatches each mapped workflow identifier through an
invoker. Emits a DispatchResult JSON on stdout, warnings on stderr, and always
exits 0 so routing can never abort the triggering git operation. Contract:
specs/004-workflow-router/contracts/routing-config.md
"""
from __future__ import annotations

RESULT_SCHEMA_VERSION = "1.0"
OUTCOMES = ("invoked", "unresolvable", "failed")
VALID_EVENTS = ("pre-commit", "post-merge", "pre-push")


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
