#!/usr/bin/env python3
"""Skill result files under _aioutput/ (feature 009).

The framework — never Claude — writes each completed skill run's report to
_aioutput/<skill>/<UTC stamp>-<event>[-N].md at the repository root, with a
provenance header. Files are never overwritten (history, one per run) and the
per-skill count is bounded by retention. Path, header and pruning decisions
are pure functions; write_result / prune are the only I/O. Contract:
specs/009-aioutput-skills/contracts/execution-and-output.md
"""
from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone

OUTPUT_DIR = "_aioutput"
DEFAULT_OUTPUT_RETENTION = 50
_STAMP_FORMAT = "%Y%m%dT%H%M%SZ"
# Same rule as skill names (005): safe as a single path component, so neither
# a skill name nor an event can climb out of _aioutput/.
_TOKEN_RE = re.compile(r"[a-z0-9][a-z0-9-]{0,63}")
_RESULT_NAME_RE = re.compile(r"(\d{8}T\d{6}Z)-([a-z0-9-]+?)(?:-(\d+))?\.md")
# Header field order is part of the format: humans scan it top-down.
HEADER_FIELDS = ("skill", "skill_version", "event", "branch", "mode", "verdict",
                 "reason", "run_id", "timestamp")


def _token(value, what: str) -> str:
    if not isinstance(value, str) or not _TOKEN_RE.fullmatch(value):
        raise ValueError(f"unsafe {what} for an output path: {value!r}")
    return value


def result_path(root: str, skill: str, event, now: datetime,
                exists=os.path.exists) -> str:
    """The first free result path for this run. Pure apart from `exists`.

    Two runs in the same second get -2, -3, ... rather than overwriting.
    """
    directory = os.path.join(root, OUTPUT_DIR, _token(skill, "skill name"))
    base = f"{now.strftime(_STAMP_FORMAT)}-{_token(event or 'unknown', 'event')}"
    candidate = os.path.join(directory, f"{base}.md")
    n = 2
    while exists(candidate):
        candidate = os.path.join(directory, f"{base}-{n}.md")
        n += 1
    return candidate


def render_result(meta: dict, report: str) -> str:
    """Header + Claude's report, verbatim. Pure.

    Scalars are JSON-encoded, which is also valid YAML: a reason containing
    quotes, colons or newlines can never break the header.
    """
    lines = ["---"]
    for key in HEADER_FIELDS:
        lines.append(f"{key}: {json.dumps(meta.get(key), ensure_ascii=False)}")
    files = meta.get("files") or []
    lines.append("files:" if files else "files: []")
    lines.extend(f"  - {json.dumps(f, ensure_ascii=False)}" for f in files)
    lines += ["---", "", (report or "").rstrip(), ""]
    return "\n".join(lines)


def write_result(root: str, skill: str, meta: dict, report: str,
                 now: datetime | None = None) -> str:
    """Write one result file; return its repo-relative path (forward slashes).

    Never overwrites: the name is reserved with an exclusive create, then the
    content is written to a temp file and atomically swapped in, so a reader
    sees either an empty reservation or the complete file — never half of it.
    Raises OSError for the caller to classify (e.g. _aioutput is a file).
    """
    now = now or datetime.now(timezone.utc)
    content = render_result(meta, report)
    while True:
        path = result_path(root, skill, meta.get("event"), now)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        try:
            with open(path, "x", encoding="utf-8"):
                break  # reserved
        except FileExistsError:
            continue  # lost a race for that name — take the next suffix
    tmp = f"{path}.tmp"
    try:
        with open(tmp, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(content)
        os.replace(tmp, path)
    except OSError:
        for leftover in (tmp, path):
            try:
                os.remove(leftover)
            except OSError:
                pass
        raise
    return os.path.relpath(path, root).replace(os.sep, "/")


def prune_plan(names: list[str], keep: int) -> list[str]:
    """Which result files to delete so only the newest `keep` remain. Pure.

    Only names in the result-file format count; anything else a developer put
    in the directory is left alone. keep < 1 means the default.
    """
    if not isinstance(keep, int) or isinstance(keep, bool) or keep < 1:
        keep = DEFAULT_OUTPUT_RETENTION
    results = []
    for name in names:
        match = _RESULT_NAME_RE.fullmatch(name)
        if match:
            # Sort by (stamp, suffix): lexically "-2.md" < ".md", which would
            # rank the later same-second file as older.
            results.append(((match.group(1), int(match.group(3) or 1)), name))
    results.sort()
    return [name for _key, name in results[:-keep]] if len(results) > keep else []


def prune(root: str, skill: str, keep: int) -> list[str]:
    """Delete the oldest result files of one skill beyond `keep`. Best-effort."""
    directory = os.path.join(root, OUTPUT_DIR, _token(skill, "skill name"))
    try:
        names = os.listdir(directory)
    except OSError:
        return []
    removed = []
    for name in prune_plan(names, keep):
        try:
            os.remove(os.path.join(directory, name))
            removed.append(name)
        except OSError:
            pass
    return removed
