"""Tests for src/ai_output.py — _aioutput/ result files (feature 009)."""
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

from ai_output import (  # noqa: E402
    DEFAULT_OUTPUT_RETENTION,
    prune,
    prune_plan,
    render_result,
    result_path,
    write_result,
)

NOW = datetime(2026, 10, 2, 10, 15, 30, tzinfo=timezone.utc)
META = {"skill": "todo-check", "skill_version": "1.0.0", "event": "pre-commit",
        "branch": "feature-x", "mode": "sync", "verdict": "fail",
        "reason": 'found "TODO-BLOCK": src/a.py\nline 3',
        "run_id": "20261002T101530.123456Z-pre-commit",
        "timestamp": "2026-10-02T10:15:30Z", "files": ["src/a.py", "docs/b c.md"]}


def _header(text):
    head = text.split("---\n")[1]
    fields = {}
    for line in head.splitlines():
        if not line.startswith("  - ") and ": " in line:
            key, value = line.split(": ", 1)
            fields[key] = json.loads(value)
    return fields


# --- result_path ---

def test_path_format(tmp_path):
    p = result_path(str(tmp_path), "todo-check", "pre-commit", NOW)
    assert p == os.path.join(str(tmp_path), "_aioutput", "todo-check",
                             "20261002T101530Z-pre-commit.md")


def test_path_collision_gets_suffix(tmp_path):
    taken = {result_path(str(tmp_path), "s", "pre-push", NOW)}
    second = result_path(str(tmp_path), "s", "pre-push", NOW, exists=taken.__contains__)
    taken.add(second)
    third = result_path(str(tmp_path), "s", "pre-push", NOW, exists=taken.__contains__)
    assert second.endswith("20261002T101530Z-pre-push-2.md")
    assert third.endswith("20261002T101530Z-pre-push-3.md")


def test_missing_event_is_named_unknown(tmp_path):
    assert result_path(str(tmp_path), "s", None, NOW).endswith("-unknown.md")


@pytest.mark.parametrize("skill", ["..", "a/b", "../x", "A", "", None])
def test_unsafe_skill_name_rejected(tmp_path, skill):
    with pytest.raises(ValueError):
        result_path(str(tmp_path), skill, "pre-commit", NOW)


def test_unsafe_event_rejected(tmp_path):
    with pytest.raises(ValueError):
        result_path(str(tmp_path), "s", "../pre-commit", NOW)


# --- render_result ---

def test_header_has_every_field_and_survives_awkward_values():
    text = render_result(META, "# Findings\n\nbody")
    fields = _header(text)
    for key in ("skill", "skill_version", "event", "branch", "mode", "verdict",
                "reason", "run_id", "timestamp"):
        assert fields[key] == META[key]
    assert '  - "docs/b c.md"' in text
    assert text.rstrip().endswith("body")


def test_invalid_verdict_rendering():
    text = render_result({**META, "verdict": "invalid"}, "r")
    assert _header(text)["verdict"] == "invalid"


def test_empty_files_list():
    assert "files: []" in render_result({**META, "files": []}, "r")


# --- write_result ---

def test_write_creates_dir_and_file_atomically(tmp_path):
    rel = write_result(str(tmp_path), "todo-check", META, "report", now=NOW)
    assert rel == "_aioutput/todo-check/20261002T101530Z-pre-commit.md"
    target = tmp_path / rel
    assert target.read_text(encoding="utf-8") == render_result(META, "report")
    assert not list((tmp_path / "_aioutput" / "todo-check").glob("*.tmp"))


def test_write_never_overwrites(tmp_path):
    first = write_result(str(tmp_path), "todo-check", META, "one", now=NOW)
    second = write_result(str(tmp_path), "todo-check", META, "two", now=NOW)
    assert first != second
    assert "one" in (tmp_path / first).read_text(encoding="utf-8")
    assert "two" in (tmp_path / second).read_text(encoding="utf-8")


def test_write_preserves_unicode(tmp_path):
    rel = write_result(str(tmp_path), "s", META, "café — ✓", now=NOW)
    assert "café — ✓" in (tmp_path / rel).read_text(encoding="utf-8")


def test_write_fails_when_aioutput_is_a_file(tmp_path):
    (tmp_path / "_aioutput").write_text("not a dir")
    with pytest.raises(OSError):
        write_result(str(tmp_path), "s", META, "r", now=NOW)


# --- retention ---

def _names(n):
    return [f"202610{d:02d}T000000Z-pre-commit.md" for d in range(1, n + 1)]


def test_prune_plan_keeps_newest():
    names = _names(5)
    assert prune_plan(names, 3) == names[:2]
    assert prune_plan(names, 5) == []


def test_prune_plan_orders_same_second_suffixes():
    names = ["20261002T000000Z-pre-commit-2.md", "20261002T000000Z-pre-commit.md",
             "20261001T000000Z-pre-commit.md"]
    assert prune_plan(names, 1) == ["20261001T000000Z-pre-commit.md",
                                    "20261002T000000Z-pre-commit.md"]


def test_prune_plan_ignores_foreign_files_and_bad_keep():
    names = _names(3) + ["notes.md", "x.tmp"]
    assert prune_plan(names, 2) == names[:1]
    assert prune_plan(_names(DEFAULT_OUTPUT_RETENTION + 1), 0) == _names(1)


def test_prune_deletes_on_disk_and_tolerates_missing_dir(tmp_path):
    d = tmp_path / "_aioutput" / "s"
    d.mkdir(parents=True)
    for name in _names(4):
        (d / name).write_text("x")
    removed = prune(str(tmp_path), "s", 2)
    assert removed == _names(2)
    assert sorted(os.listdir(d)) == _names(4)[2:]
    assert prune(str(tmp_path), "ghost", 2) == []
