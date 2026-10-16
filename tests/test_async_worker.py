"""Tests for src/async_worker.py — detached async skill worker (feature 009)."""
import json
import sys
import time
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

from async_worker import load_job, main  # noqa: E402
from execute_skills import JOB_SCHEMA_VERSION, dispatch_async  # noqa: E402

CTX = {"schema_version": "1.0", "event": "pre-push", "branch": "main",
       "files": ["a.py"], "commits": [], "partial": False,
       "unavailable": [], "errors": []}


def _make_skill(tmp_path, name):
    d = tmp_path / "skills" / name
    d.mkdir(parents=True)
    (d / "prompt.md").write_text(f"Task for {name}.")
    (d / "skill.json").write_text(json.dumps(
        {"name": name, "version": "1.0.0", "description": name,
         "input": "hook-context@1.0"}))
    reg_path = tmp_path / "skills" / "registry.json"
    reg = json.loads(reg_path.read_text()) if reg_path.exists() else \
        {"contract_version": "2.0", "skills": {}}
    reg["skills"][name] = {"dir": name, "version": "1.0.0", "description": name}
    reg_path.write_text(json.dumps(reg))


def _job(tmp_path, plan, **extra):
    job = {"schema_version": JOB_SCHEMA_VERSION, "run_id": "RUN-1", "context": CTX,
           "plan": plan, "skills_dir": str(tmp_path / "skills"), "root": str(tmp_path),
           "bridge_config": None, "output_retention": 50,
           "runs_dir": str(tmp_path / "logs" / "runs"), "run_retention": 50,
           "log": str(tmp_path / "logs" / "hooks.log"), "outcome_rules": {}, **extra}
    path = tmp_path / "logs" / "async" / "RUN-1.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(job))
    return path


def _bridge(request, config):
    verdict = "fail" if "bravo" in request["task"] else "pass"
    return {"status": "ok", "verdict": verdict, "reason": f"{verdict} reason",
            "report": f"report for {request['task']}", "error": ""}


def _record(tmp_path, name="RUN-1-async"):
    return json.loads((tmp_path / "logs" / "runs" / f"{name}.json").read_text())


def test_valid_job_runs_skills_records_logs_and_cleans_up(tmp_path):
    _make_skill(tmp_path, "alpha")
    _make_skill(tmp_path, "bravo")
    job_path = _job(tmp_path, ["alpha", "bravo"],
                    outcome_rules={"bravo": {"mode": "async", "on_failure": "block"}})
    assert main([str(job_path)], bridge=_bridge) == 0

    rec = _record(tmp_path)
    assert rec["parent_run"] == "RUN-1" and rec["plan"] == ["alpha", "bravo"]
    by_skill = {r["skill"]: r for r in rec["results"]}
    assert by_skill["alpha"]["status"] == "success"
    assert by_skill["bravo"]["status"] == "failure"
    assert by_skill["bravo"]["outcome"] == "warn"  # async never blocks
    for r in rec["results"]:
        assert r["mode"] == "async"
        assert (tmp_path / r["output_file"]).exists()

    log = (tmp_path / "logs" / "hooks.log").read_text().splitlines()
    assert len(log) == 2 and "skill=alpha" in log[0] and "status=failure" in log[1]
    assert not job_path.exists()


def test_unregistered_skill_is_recorded_as_skipped(tmp_path):
    job_path = _job(tmp_path, ["ghost"])
    main([str(job_path)], bridge=_bridge)
    assert _record(tmp_path)["results"][0]["status"] == "skipped"


@pytest.mark.parametrize("content", ["{nope", "[]", json.dumps({"schema_version": "9"}),
                                     json.dumps({"schema_version": JOB_SCHEMA_VERSION})])
def test_corrupt_job_leaves_error_record_and_exits_zero(tmp_path, content):
    job_path = tmp_path / "logs" / "async" / "RUN-1.json"
    job_path.parent.mkdir(parents=True)
    job_path.write_text(content)
    assert main([str(job_path)], bridge=_bridge) == 0
    rec = _record(tmp_path)
    assert rec["results"] == [] and rec["warnings"]


def test_missing_job_file_exits_zero(tmp_path):
    job_path = tmp_path / "logs" / "async" / "GONE.json"
    assert main([str(job_path)], bridge=_bridge) == 0
    assert "unreadable" in _record(tmp_path, "GONE-async")["warnings"][0]


def test_no_arguments_exits_zero():
    assert main([]) == 0


def test_load_job_rejects_malformed_plan(tmp_path):
    path = _job(tmp_path, "alpha")  # a string, not a list
    job, error = load_job(str(path))
    assert job is None and "malformed" in error


def test_real_detached_worker_completes_after_dispatch_returns(tmp_path):
    # An unregistered skill: the real worker runs end to end with no Claude call.
    job = json.loads(_job(tmp_path, ["ghost"]).read_text())
    started = time.monotonic()
    ok, detail, _job_path = dispatch_async(job, str(tmp_path / "logs" / "async"))
    assert ok, detail
    assert time.monotonic() - started < 0.2
    record = tmp_path / "logs" / "runs" / "RUN-1-async.json"
    deadline = time.monotonic() + 20
    while not record.exists() and time.monotonic() < deadline:
        time.sleep(0.1)
    assert record.exists()
    assert json.loads(record.read_text())["results"][0]["status"] == "skipped"
