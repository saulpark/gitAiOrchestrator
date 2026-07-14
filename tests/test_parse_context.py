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


def test_files_deduped_sorted_blanks_dropped():
    ctx = parse_context(_env(HOOK_EVENT="pre-commit", HOOK_BRANCH="b",
                             HOOK_FILES="b.py\n\n  \na.py\nb.py\n./c.py"), "/repo")
    assert ctx["files"] == ["a.py", "b.py", "c.py"]


def test_absolute_path_inside_repo_relativized():
    ctx = parse_context(_env(HOOK_EVENT="pre-commit", HOOK_BRANCH="b",
                             HOOK_FILES="/repo/src/x.py"), "/repo")
    assert ctx["files"] == ["src/x.py"]
    assert ctx["partial"] is False


def test_absolute_path_outside_repo_dropped_with_error():
    ctx = parse_context(_env(HOOK_EVENT="pre-commit", HOOK_BRANCH="b",
                             HOOK_FILES="/etc/passwd\na.py"), "/repo")
    assert ctx["files"] == ["a.py"]
    assert any("outside repository" in e for e in ctx["errors"])
    assert ctx["partial"] is False  # dropped path is noted, not an unavailability


def test_missing_event_and_branch_partial():
    ctx = parse_context(_env(HOOK_FILES="a.py"), "/repo")
    assert ctx["event"] is None and ctx["branch"] is None
    assert ctx["partial"] is True
    assert set(ctx["unavailable"]) == {"event", "branch"}
    assert set(ctx) == SCHEMA_KEYS  # full key set even when partial


def test_unknown_event_marked_unavailable():
    ctx = parse_context(_env(HOOK_EVENT="post-checkout", HOOK_BRANCH="b",
                             HOOK_FILES=""), "/repo")
    assert ctx["event"] is None
    assert "event" in ctx["unavailable"]
    assert any("post-checkout" in e for e in ctx["errors"])


def test_unset_files_unavailable_but_empty_files_valid():
    unset = parse_context(_env(HOOK_EVENT="pre-commit", HOOK_BRANCH="b"), "/repo")
    assert "files" in unset["unavailable"] and unset["partial"] is True
    empty = parse_context(_env(HOOK_EVENT="pre-commit", HOOK_BRANCH="b",
                               HOOK_FILES=""), "/repo")
    assert empty["files"] == [] and empty["partial"] is False


def test_commits_unavailable_only_for_pre_push():
    push = parse_context(_env(HOOK_EVENT="pre-push", HOOK_BRANCH="b",
                              HOOK_FILES="a.py"), "/repo")
    assert "commits" in push["unavailable"]
    commit = parse_context(_env(HOOK_EVENT="pre-commit", HOOK_BRANCH="b",
                                HOOK_FILES="a.py"), "/repo")
    assert "commits" not in commit["unavailable"]


def test_invalid_commit_token_dropped_with_error():
    good = "b" * 40
    ctx = parse_context(_env(HOOK_EVENT="pre-push", HOOK_BRANCH="b", HOOK_FILES="",
                             HOOK_COMMITS=f"{good}\nnot-a-sha\n{good}"), "/repo")
    assert ctx["commits"] == [good]  # deduped, order preserved
    assert any("not-a-sha" in e for e in ctx["errors"])


def test_detached_head_branch_is_valid():
    ctx = parse_context(_env(HOOK_EVENT="pre-commit", HOOK_BRANCH="HEAD",
                             HOOK_FILES=""), "/repo")
    assert ctx["branch"] == "HEAD" and ctx["partial"] is False
