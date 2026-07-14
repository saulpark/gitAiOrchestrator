#!/usr/bin/env python3
"""Hook context parser (feature 003).

Normalizes the raw hook environment (HOOK_EVENT, HOOK_BRANCH, HOOK_FILES,
HOOK_COMMITS) into the JSON context schema defined in
specs/003-hook-context-parser/contracts/context-schema.md. Invoked standalone
or by scripts/orchestrate.sh; always exits 0 so malformed input can never
abort the triggering git operation.
"""
from __future__ import annotations

from collections.abc import Mapping

SCHEMA_VERSION = "1.0"
VALID_EVENTS = ("pre-commit", "post-merge", "pre-push")


def parse_context(env: Mapping[str, str], repo_root: str) -> dict:
    files = sorted({line for line in env.get("HOOK_FILES", "").splitlines() if line})
    commits = [line for line in env.get("HOOK_COMMITS", "").splitlines() if line]
    return {
        "schema_version": SCHEMA_VERSION,
        "event": env.get("HOOK_EVENT"),
        "branch": env.get("HOOK_BRANCH"),
        "files": files,
        "commits": commits,
        "partial": False,
        "unavailable": [],
        "errors": [],
    }
