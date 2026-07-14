"""Tests for src/parse_context.py — hook context parser (feature 003)."""
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

from parse_context import SCHEMA_VERSION, VALID_EVENTS, parse_context  # noqa: E402

SCHEMA_KEYS = {
    "schema_version", "event", "branch", "files",
    "commits", "partial", "unavailable", "errors",
}


def _env(**kw):
    return dict(kw)


def test_same_schema_keys_for_all_three_events():
    contexts = [
        parse_context(_env(HOOK_EVENT=e, HOOK_BRANCH="main", HOOK_FILES="a.py",
                           HOOK_COMMITS=""), "/repo")
        for e in VALID_EVENTS
    ]
    assert [set(c) for c in contexts] == [SCHEMA_KEYS] * 3


def test_complete_pre_commit_context():
    ctx = parse_context(_env(HOOK_EVENT="pre-commit", HOOK_BRANCH="main",
                             HOOK_FILES="src/foo.py\nsrc/bar.py"), "/repo")
    assert ctx == {
        "schema_version": SCHEMA_VERSION,
        "event": "pre-commit",
        "branch": "main",
        "files": ["src/bar.py", "src/foo.py"],
        "commits": [],
        "partial": False,
        "unavailable": [],
        "errors": [],
    }


def test_post_merge_same_shape_as_pre_commit():
    ctx = parse_context(_env(HOOK_EVENT="post-merge", HOOK_BRANCH="main",
                             HOOK_FILES="m.py"), "/repo")
    assert ctx["event"] == "post-merge"
    assert ctx["files"] == ["m.py"]
    assert ctx["partial"] is False


def test_pre_push_includes_commits():
    sha = "a" * 40
    ctx = parse_context(_env(HOOK_EVENT="pre-push", HOOK_BRANCH="main",
                             HOOK_FILES="p.py", HOOK_COMMITS=sha), "/repo")
    assert ctx["commits"] == [sha]
    assert ctx["partial"] is False
