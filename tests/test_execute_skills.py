"""Tests for src/execute_skills.py — skill executor (feature 006)."""
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

from execute_skills import SUMMARY_SCHEMA_VERSION, execute_plan  # noqa: E402

CTX = {"schema_version": "1.0", "event": "pre-commit", "branch": "main",
       "files": ["a.py"], "commits": [], "partial": False,
       "unavailable": [], "errors": []}

OK_RESULT = ('{"schema_version": "1.0", "skill": "%s", "status": "ok", '
             '"summary": "did the thing", "details": {}}')


def _ok_script(name):
    return f"#!/bin/sh\ncat > /dev/null\nprintf %s '{OK_RESULT % name}'\n"


def _make_skill(tmp_path, name, script=None, budget=None, register=True):
    d = tmp_path / "skills" / name
    d.mkdir(parents=True)
    run = d / "run"
    run.write_text(script if script is not None else _ok_script(name))
    run.chmod(0o755)
    manifest = {"name": name, "version": "1.0.0", "description": name,
                "input": "hook-context@1.0", "output": "skill-result@1.0",
                "behaviors": {"non_blocking": True, "idempotent": True}}
    if budget is not None:
        manifest["time_budget_seconds"] = budget
    (d / "skill.json").write_text(json.dumps(manifest))
    if register:
        reg_path = tmp_path / "skills" / "registry.json"
        reg = json.loads(reg_path.read_text()) if reg_path.exists() else \
            {"contract_version": "1.1", "skills": {}}
        reg["skills"][name] = {"dir": name, "version": "1.0.0", "description": name}
        reg_path.write_text(json.dumps(reg))
    return d


def _skills(tmp_path):
    return str(tmp_path / "skills")


def test_plan_order_preserved_and_all_success(tmp_path):
    for n in ("bravo", "alpha", "charlie"):
        _make_skill(tmp_path, n)
    summary = execute_plan(["bravo", "alpha", "charlie"], CTX, _skills(tmp_path))
    assert [r["skill"] for r in summary["results"]] == ["bravo", "alpha", "charlie"]
    assert all(r["status"] == "success" for r in summary["results"])
    assert summary["overall"] == "success"
    assert summary["schema_version"] == SUMMARY_SCHEMA_VERSION
    assert summary["event"] == "pre-commit"


def test_context_delivered_unmodified_on_stdin(tmp_path):
    _make_skill(tmp_path, "capture",
                "#!/bin/sh\ncat > \"$(dirname \"$0\")/got.json\"\n"
                f"printf %s '{OK_RESULT % 'capture'}'\n")
    execute_plan(["capture"], CTX, _skills(tmp_path))
    got = json.loads((tmp_path / "skills" / "capture" / "got.json").read_text())
    assert got == CTX


def test_failure_isolated_subsequent_skills_run(tmp_path):
    _make_skill(tmp_path, "fails", "#!/bin/sh\ncat > /dev/null\necho boom >&2\nexit 1\n")
    _make_skill(tmp_path, "works")
    summary = execute_plan(["fails", "works"], CTX, _skills(tmp_path))
    statuses = {r["skill"]: r["status"] for r in summary["results"]}
    assert statuses == {"fails": "failure", "works": "success"}
    assert summary["overall"] == "partial-failure"
    fails = summary["results"][0]
    assert "boom" in fails["detail"] and fails["result"] is None


def test_timeout_enforced_and_isolated(tmp_path):
    _make_skill(tmp_path, "slow", "#!/bin/sh\nsleep 10\n", budget=1)
    _make_skill(tmp_path, "after")
    summary = execute_plan(["slow", "after"], CTX, _skills(tmp_path))
    slow, after = summary["results"]
    assert slow["status"] == "timeout"
    assert slow["duration_ms"] >= 900
    assert after["status"] == "success"


def test_unregistered_skill_skipped(tmp_path):
    _make_skill(tmp_path, "real")
    summary = execute_plan(["ghost", "real"], CTX, _skills(tmp_path))
    assert summary["results"][0]["status"] == "skipped"
    assert "not registered" in summary["results"][0]["detail"]
    assert summary["results"][1]["status"] == "success"


def test_malformed_stdout_is_failure(tmp_path):
    _make_skill(tmp_path, "chatty", "#!/bin/sh\ncat > /dev/null\necho not-json\n")
    summary = execute_plan(["chatty"], CTX, _skills(tmp_path))
    assert summary["results"][0]["status"] == "failure"
    assert "malformed output" in summary["results"][0]["detail"]


def test_success_carries_parsed_result_and_summary_detail(tmp_path):
    _make_skill(tmp_path, "good")
    summary = execute_plan(["good"], CTX, _skills(tmp_path))
    r = summary["results"][0]
    assert r["result"]["status"] == "ok"
    assert r["detail"] == "did the thing"


def test_duplicate_identifier_runs_per_occurrence(tmp_path):
    _make_skill(tmp_path, "twice")
    summary = execute_plan(["twice", "twice"], CTX, _skills(tmp_path))
    assert [r["skill"] for r in summary["results"]] == ["twice", "twice"]


def test_all_fail_overall_failure(tmp_path):
    _make_skill(tmp_path, "bad1", "#!/bin/sh\nexit 1\n")
    _make_skill(tmp_path, "bad2", "#!/bin/sh\nexit 2\n")
    summary = execute_plan(["bad1", "bad2"], CTX, _skills(tmp_path))
    assert summary["overall"] == "failure"


def test_empty_plan_overall_empty(tmp_path):
    summary = execute_plan([], CTX, _skills(tmp_path))
    assert summary["overall"] == "empty" and summary["results"] == []


def test_durations_present(tmp_path):
    _make_skill(tmp_path, "quick")
    summary = execute_plan(["quick"], CTX, _skills(tmp_path))
    assert summary["duration_ms"] >= 0
    assert all(isinstance(r["duration_ms"], int) for r in summary["results"])
