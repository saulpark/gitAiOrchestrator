#!/usr/bin/env python3
"""Hook context parser (feature 003).

Normalizes the raw hook environment (HOOK_EVENT, HOOK_BRANCH, HOOK_FILES,
HOOK_COMMITS) into the JSON context schema defined in
specs/003-hook-context-parser/contracts/context-schema.md. Invoked standalone
or by scripts/orchestrate.sh; always exits 0 so malformed input can never
abort the triggering git operation.
"""
from __future__ import annotations

import os
import re
from collections.abc import Mapping

SCHEMA_VERSION = "1.0"
VALID_EVENTS = ("pre-commit", "post-merge", "pre-push")
_SHA_RE = re.compile(r"[0-9a-f]{40}|[0-9a-f]{64}")


def _normalize_paths(raw: str, repo_root: str, errors: list[str]) -> list[str]:
    paths = set()
    for line in raw.splitlines():
        p = line.strip()
        if not p:
            continue
        if os.path.isabs(p):
            rel = os.path.relpath(p, repo_root)
            if rel == ".." or rel.startswith(".." + os.sep):
                errors.append(f"path outside repository dropped: {p}")
                continue
            p = rel
        paths.add(os.path.normpath(p))
    return sorted(paths)


def _parse_commits(raw: str, errors: list[str]) -> list[str]:
    commits: list[str] = []
    for line in raw.splitlines():
        tok = line.strip()
        if not tok:
            continue
        if _SHA_RE.fullmatch(tok):
            if tok not in commits:
                commits.append(tok)
        else:
            errors.append(f"invalid commit id dropped: {tok}")
    return commits


def parse_context(env: Mapping[str, str], repo_root: str) -> dict:
    unavailable: list[str] = []
    errors: list[str] = []

    event = env.get("HOOK_EVENT")
    if not event or event not in VALID_EVENTS:
        errors.append(
            f"unknown HOOK_EVENT: {event}" if event else "HOOK_EVENT missing or empty"
        )
        event = None
        unavailable.append("event")

    branch = env.get("HOOK_BRANCH")
    if not branch:
        errors.append("HOOK_BRANCH missing or empty")
        branch = None
        unavailable.append("branch")

    raw_files = env.get("HOOK_FILES")
    if raw_files is None:
        errors.append("HOOK_FILES not set")
        unavailable.append("files")
        files: list[str] = []
    else:
        files = _normalize_paths(raw_files, repo_root, errors)

    raw_commits = env.get("HOOK_COMMITS")
    if event == "pre-push" and raw_commits is None:
        errors.append("HOOK_COMMITS not set for pre-push")
        unavailable.append("commits")
        commits: list[str] = []
    else:
        commits = _parse_commits(raw_commits or "", errors)

    return {
        "schema_version": SCHEMA_VERSION,
        "event": event,
        "branch": branch,
        "files": files,
        "commits": commits,
        "partial": bool(unavailable),
        "unavailable": unavailable,
        "errors": errors,
    }
