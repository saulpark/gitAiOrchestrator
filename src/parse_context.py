#!/usr/bin/env python3
"""Hook context parser (feature 003).

Normalizes the raw hook environment (HOOK_EVENT, HOOK_BRANCH, HOOK_FILES,
HOOK_COMMITS) into the JSON context schema defined in
specs/003-hook-context-parser/contracts/context-schema.md. Invoked standalone
or by scripts/orchestrate.sh; always exits 0 so malformed input can never
abort the triggering git operation.
"""
from __future__ import annotations

import json
import os
import re
import sys
from collections.abc import Mapping

SCHEMA_VERSION = "1.0"          # bumped only on a breaking context-schema change
VALID_EVENTS = ("pre-commit", "post-merge", "pre-push")
_SHA_RE = re.compile(r"[0-9a-f]{40}|[0-9a-f]{64}")  # SHA-1 (40) or SHA-256 (64)


def _normalize_paths(raw: str, repo_root: str, errors: list[str]) -> list[str]:
    """Newline-separated paths -> sorted, de-duplicated, repo-relative list.

    Hooks may hand us absolute paths (or the same path twice, e.g. a file
    touched by several pushed commits). Downstream components compare paths as
    plain strings, so they must be normalized here, exactly once.
    """
    paths = set()  # a set: the same file may be reported by several commits
    for line in raw.splitlines():
        p = line.strip()
        if not p:
            continue
        if os.path.isabs(p):
            rel = os.path.relpath(p, repo_root)
            # A relative path starting with ".." escapes the repo — never pass
            # it on; skills are only ever allowed to see in-repo files.
            if rel == ".." or rel.startswith(".." + os.sep):
                errors.append(f"path outside repository dropped: {p}")
                continue
            p = rel
        paths.add(os.path.normpath(p))
    return sorted(paths)


def _parse_commits(raw: str, errors: list[str]) -> list[str]:
    """Validate commit ids, preserving push order (unlike files, order matters).

    Anything that is not a full hex SHA is dropped with a recorded error rather
    than passed through — skills must never receive an unusable commit id.
    """
    commits: list[str] = []  # a list, not a set: push order is meaningful
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
    """Build the context document from the hook environment.

    Nothing here raises or exits non-zero. Every problem is recorded instead:
    the affected field is named in "unavailable", the reason is appended to
    "errors", and "partial" flips to true. Consumers (router, skills) can then
    decide for themselves whether a partial context is good enough, rather than
    being handed a silently truncated one.
    """
    unavailable: list[str] = []  # field names we could NOT determine
    errors: list[str] = []       # human-readable reasons, one per problem

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

    # HOOK_COMMITS is only set by pre-push (003 contract v1.1); its absence is
    # normal for the other two events and only an error for pre-push.
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


def main() -> int:
    """CLI: env -> context JSON on stdout. Exit code is always 0."""
    try:
        context = parse_context(os.environ, os.getcwd())
    except Exception as exc:  # SC-005: never abort the triggering git operation
        # Last-resort context: fully partial, but still schema-valid, so the
        # router downstream can parse it instead of choking on empty stdin.
        context = {
            "schema_version": SCHEMA_VERSION,
            "event": None,
            "branch": None,
            "files": [],
            "commits": [],
            "partial": True,
            "unavailable": ["event", "branch", "files", "commits"],
            "errors": [f"parser failure: {exc}"],
        }
    json.dump(context, sys.stdout)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
