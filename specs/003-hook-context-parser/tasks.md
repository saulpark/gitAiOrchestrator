# Tasks: Hook Context Parser

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Standalone Python parser turning `HOOK_*` env vars into a uniform JSON context for all three hook types.

**Architecture:** Pure function `parse_context(env, repo_root) -> dict` in `src/parse_context.py` with a thin `main()` CLI wrapper that always exits 0. `scripts/pre-push.sh` gains `HOOK_COMMITS` capture (hook contract v1.1). pytest drives everything (TDD).

**Tech Stack:** Python 3.10+ stdlib (`json`, `os`, `re`, `sys`), pytest, ruff.

## Global Constraints

- Python 3.10+, stdlib only at runtime — no third-party packages
- Parser never executes git commands
- Exit code always 0 (SC-005)
- All eight schema keys present in every output (FR-003); `schema_version: "1.0"`
- Hook scripts stay ≤ 30 lines, POSIX sh, no bash-isms (002 SC-004 carries over)
- < 1 s for 1,000 files (SC-003)

---

## Task 1: Schema uniformity + complete contexts (US1, P1)

**Files:**
- Create: `src/parse_context.py`
- Test: `tests/test_parse_context.py`

**Interfaces:**
- Produces: `parse_context(env: Mapping[str, str], repo_root: str) -> dict` returning the 8-key schema; `SCHEMA_VERSION = "1.0"`; `VALID_EVENTS = ("pre-commit", "post-merge", "pre-push")`

- [x] **Step 1: Write failing tests** — same key set for all three events (SC-004), complete pre-commit/post-merge/pre-push contexts:

```python
"""Tests for src/parse_context.py — hook context parser (feature 003)."""
import json
import subprocess
import sys
import time
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
```

- [x] **Step 2: Run to verify failure** — `pytest tests/test_parse_context.py -v` → FAIL (ModuleNotFoundError)
- [x] **Step 3: Implement minimal `parse_context`** (event/branch pass-through, newline-split files sorted+deduped, commit list pass-through, fixed key set)
- [x] **Step 4: Run to verify pass** — 4 passed
- [x] **Step 5: Commit** — `test+feat(003): schema-uniform context for all hook types`

---

## Task 2: Path normalization (US2, P2)

**Files:**
- Modify: `src/parse_context.py` (`_normalize_paths`)
- Test: `tests/test_parse_context.py`

**Interfaces:**
- Consumes: `parse_context` from Task 1
- Produces: `_normalize_paths(raw: str, repo_root: str, errors: list[str]) -> list[str]`

- [x] **Step 1: Write failing tests**:

```python
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
```

- [x] **Step 2: Run to verify failure**
- [x] **Step 3: Implement `_normalize_paths`** (strip, drop blanks, `os.path.relpath` for absolute, drop `..`-escaping with error, `normpath`, `sorted(set(...))`)
- [x] **Step 4: Run to verify pass**
- [x] **Step 5: Commit** — `feat(003): normalize affected paths to repo-relative`

---

## Task 3: Partial contexts + commit validation (US3, P3)

**Files:**
- Modify: `src/parse_context.py` (`_parse_commits`, unavailability logic)
- Test: `tests/test_parse_context.py`

**Interfaces:**
- Produces: `_parse_commits(raw: str, errors: list[str]) -> list[str]`; unavailability semantics per data-model.md

- [x] **Step 1: Write failing tests**:

```python
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
```

- [x] **Step 2: Run to verify failure**
- [x] **Step 3: Implement** unavailability tracking, `_parse_commits` with `[0-9a-f]{40}|[0-9a-f]{64}` fullmatch
- [x] **Step 4: Run to verify pass**
- [x] **Step 5: Commit** — `feat(003): partial contexts with explicit unavailability markers`

---

## Task 4: CLI entry point — always exit 0 (SC-005, FR-007)

**Files:**
- Modify: `src/parse_context.py` (`main()`, `__main__` guard)
- Test: `tests/test_parse_context.py`

**Interfaces:**
- Produces: `python3 src/parse_context.py` → one JSON line on stdout, exit 0

- [x] **Step 1: Write failing tests**:

```python
def _run_cli(env):
    return subprocess.run(
        [sys.executable, str(REPO_ROOT / "src" / "parse_context.py")],
        env={"PATH": "/usr/bin:/bin", **env}, cwd=REPO_ROOT,
        capture_output=True, text=True, timeout=10,
    )

def test_cli_complete_context_exit_zero():
    r = _run_cli({"HOOK_EVENT": "pre-commit", "HOOK_BRANCH": "main",
                  "HOOK_FILES": "a.py"})
    assert r.returncode == 0
    ctx = json.loads(r.stdout)
    assert ctx["event"] == "pre-commit" and set(ctx) == SCHEMA_KEYS

def test_cli_empty_environment_still_exit_zero():
    r = _run_cli({})
    assert r.returncode == 0
    ctx = json.loads(r.stdout)
    assert ctx["partial"] is True

def test_thousand_files_under_one_second():
    files = "\n".join(f"src/mod_{i}.py" for i in range(1000))
    t0 = time.monotonic()
    ctx = parse_context(_env(HOOK_EVENT="pre-commit", HOOK_BRANCH="b",
                             HOOK_FILES=files), "/repo")
    assert time.monotonic() - t0 < 1.0
    assert len(ctx["files"]) == 1000
```

- [x] **Step 2: Run to verify failure**
- [x] **Step 3: Implement `main()`** with try/except emitting fallback all-unavailable context; `json.dump` single line; `return 0`
- [x] **Step 4: Run full suite + `ruff check src/`** — all pass, no lint errors
- [x] **Step 5: Commit** — `feat(003): CLI entry point, exit 0 on all inputs`

---

## Task 5: pre-push HOOK_COMMITS capture (hook contract v1.1)

**Files:**
- Modify: `scripts/pre-push.sh`

**Interfaces:**
- Produces: `HOOK_COMMITS` env var (newline-delimited SHAs) exported to orchestrate.sh

- [x] **Step 1: Rewrite the ref loop** to collect `REVS` via `git rev-list` for both ref cases, derive files per commit via `git diff-tree`, accumulate `HOOK_COMMITS`; export it
- [x] **Step 2: Verify constraints** — `sh -n`, `wc -l` ≤ 30, business-logic grep clean
- [x] **Step 3: Smoke test** — pipe a fabricated ref line with an unpushed commit; confirm `logs/hooks.log` entry and `HOOK_COMMITS` observed by a debug orchestrate stub
- [x] **Step 4: Commit** — `feat(003): pre-push captures pushed commits (contract v1.1)`

---

## Task 6: Docs sync + quickstart verification

**Files:**
- Modify: `CLAUDE.md` (003 tech line), `specs/002-git-hook-scripts/contracts/orchestration-interface.md` (HOOK_COMMITS addendum pointer)

- [x] **Step 1: Run quickstart.md commands** — manual CLI, partial context, SC-004 key-list comparison
- [x] **Step 2: Sync docs** — CLAUDE.md active technologies; 002 contract points to 003 addendum
- [x] **Step 3: Full suite** — `pytest tests/ -v && ruff check src/` all green
- [x] **Step 4: Commit** — `docs(003): sync contracts and project docs`
