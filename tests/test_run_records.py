"""Tests for src/run_records.py — run observability (feature 008)."""
import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

from run_records import (  # noqa: E402
    BLOCK_EXIT_CODE,
    build_run_record,
    evaluate_outcomes,
    list_runs,
    load_run,
    write_run_record,
)


def _summary(*results, event="pre-commit"):
    return {"schema_version": "1.0", "event": event,
            "overall": "partial-failure", "duration_ms": 100,
            "results": list(results)}


def _r(skill, status, detail="boom"):
    return {"skill": skill, "status": status, "duration_ms": 5,
            "detail": detail, "result": None}


CTX = {"event": "pre-commit", "branch": "main", "files": ["a.py"],
       "commits": [], "partial": False, "unavailable": [], "errors": []}


# --- evaluate_outcomes (Task 1) ---

def test_success_is_none_outcome():
    ev = evaluate_outcomes(_summary(_r("ok-skill", "success", "done")), {}, "pre-commit")
    assert ev["results"][0]["outcome"] == "none"
    assert ev["final_outcome"] == "none"


def test_failure_without_rule_defaults_to_warn():
    ev = evaluate_outcomes(_summary(_r("s", "failure")), {}, "pre-commit")
    assert ev["results"][0]["outcome"] == "warn"
    assert ev["results"][0]["rule"] is None
    assert ev["final_outcome"] == "warn"


def test_block_warn_skip_rules_honored():
    rules = {"a": {"on_failure": "block"}, "b": {"on_failure": "warn"},
             "c": {"on_failure": "skip"}}
    ev = evaluate_outcomes(
        _summary(_r("a", "failure"), _r("b", "timeout"), _r("c", "skipped")),
        rules, "pre-commit")
    outcomes = {r["skill"]: r["outcome"] for r in ev["results"]}
    assert outcomes == {"a": "block", "b": "warn", "c": "skip"}
    assert ev["final_outcome"] == "block"


def test_all_nonsuccess_statuses_trigger_rule():
    rules = {"s": {"on_failure": "block"}}
    for status in ("failure", "timeout", "skipped"):
        ev = evaluate_outcomes(_summary(_r("s", status)), rules, "pre-commit")
        assert ev["results"][0]["outcome"] == "block", status


def test_invalid_rule_value_defaults_to_warn_with_note():
    ev = evaluate_outcomes(_summary(_r("s", "failure")),
                           {"s": {"on_failure": "explode"}}, "pre-commit")
    assert ev["results"][0]["outcome"] == "warn"
    assert any("explode" in n for n in ev["notes"])


def test_two_blocks_both_named():
    rules = {"a": {"on_failure": "block"}, "b": {"on_failure": "block"}}
    ev = evaluate_outcomes(_summary(_r("a", "failure"), _r("b", "failure")),
                           rules, "pre-commit")
    blocking = [r["skill"] for r in ev["results"] if r["outcome"] == "block"]
    assert blocking == ["a", "b"]


def test_post_merge_block_downgraded_to_warn():
    ev = evaluate_outcomes(_summary(_r("s", "failure"), event="post-merge"),
                           {"s": {"on_failure": "block"}}, "post-merge")
    assert ev["results"][0]["outcome"] == "warn"
    assert ev["block_downgraded"] is True
    assert ev["final_outcome"] == "warn"


def test_empty_results_final_none():
    ev = evaluate_outcomes(_summary(), {}, "pre-commit")
    assert ev["final_outcome"] == "none" and ev["results"] == []


def test_reason_names_rule_and_status():
    ev = evaluate_outcomes(_summary(_r("doc", "failure")),
                           {"doc": {"on_failure": "block"}}, "pre-commit")
    reason = ev["results"][0]["reason"]
    assert "doc" in reason and "block" in reason and "failure" in reason


def test_block_exit_code_is_ten():
    assert BLOCK_EXIT_CODE == 10


# --- record store (Task 2) ---

def _make_record(event="pre-commit", results=None):
    summary = _summary(*(results or [_r("s", "failure")]), event=event)
    ev = evaluate_outcomes(summary, {}, event)
    return build_run_record({**CTX, "event": event}, [r["skill"] for r in summary["results"]],
                            summary, ev, warnings=["w1"])


def test_record_carries_required_fields():
    rec = _make_record()
    assert rec["schema_version"] == "1.0"
    assert rec["event"] == "pre-commit" and rec["branch"] == "main"
    assert rec["timestamp"].endswith("Z") and rec["id"]
    assert rec["plan"] == ["s"]
    entry = rec["results"][0]
    for key in ("skill", "status", "duration_ms", "detail", "rule", "outcome", "reason"):
        assert key in entry
    assert rec["final_outcome"] == "warn"
    assert rec["context_summary"]["files"] == 1


def test_write_read_and_ordering(tmp_path):
    runs = str(tmp_path / "runs")
    paths = []
    for event in ("pre-commit", "pre-push", "post-merge"):
        paths.append(write_run_record(runs, _make_record(event=event), retention=50))
    assert all(p for p in paths)
    listed = list_runs(runs)
    assert len(listed) == 3
    assert listed[0]["event"] == "post-merge"  # newest first
    loaded = load_run(runs, listed[0]["id"])
    assert loaded["event"] == "post-merge"


def test_retention_prunes_oldest(tmp_path):
    runs = str(tmp_path / "runs")
    for _ in range(7):
        write_run_record(runs, _make_record(), retention=3)
    assert len(list_runs(runs)) == 3


def test_write_failure_returns_none_no_raise(tmp_path):
    target = tmp_path / "blocked"
    target.write_text("i am a file, not a directory")
    assert write_run_record(str(target), _make_record(), retention=5) is None


def test_empty_plan_record(tmp_path):
    summary = _summary(event="pre-commit")
    ev = evaluate_outcomes(summary, {}, "pre-commit")
    rec = build_run_record(CTX, [], summary, ev, warnings=[])
    path = write_run_record(str(tmp_path / "runs"), rec, retention=5)
    assert path and json.loads(Path(path).read_text())["plan"] == []


# --- history CLI ---

def _run_cli(*args, cwd):
    return subprocess.run(
        [sys.executable, str(REPO_ROOT / "src" / "run_records.py"), *args],
        capture_output=True, text=True, timeout=10, cwd=cwd,
    )


def test_cli_list_and_show(tmp_path):
    runs = str(tmp_path / "runs")
    write_run_record(runs, _make_record(), retention=5)
    r = _run_cli("list", "--runs-dir", runs, cwd=tmp_path)
    assert r.returncode == 0
    line = r.stdout.strip().splitlines()[0]
    assert "pre-commit" in line and "warn" in line
    r = _run_cli("show", "--last", "--runs-dir", runs, cwd=tmp_path)
    assert r.returncode == 0
    assert "warn" in r.stdout and "s" in r.stdout and "boom" in r.stdout


def test_cli_show_unknown_id_exit_one(tmp_path):
    r = _run_cli("show", "nope", "--runs-dir", str(tmp_path / "runs"), cwd=tmp_path)
    assert r.returncode == 1
