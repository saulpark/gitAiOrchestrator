"""Tests for src/execute_skills.py — skill executor (006, declarative since 009)."""
import json
import subprocess
import sys
import time
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

from execute_skills import (  # noqa: E402
    SUMMARY_SCHEMA_VERSION,
    WORKER,
    budget_of,
    classify,
    detach_kwargs,
    dispatch_async,
    execute_plan,
)

CTX = {"schema_version": "1.0", "event": "pre-commit", "branch": "main",
       "files": ["a.py"], "commits": [], "partial": False,
       "unavailable": [], "errors": []}


def _make_skill(tmp_path, name, prompt=None, budget=None, register=True):
    d = tmp_path / "skills" / name
    d.mkdir(parents=True)
    (d / "prompt.md").write_text(prompt or f"Task for {name}.")
    manifest = {"name": name, "version": "1.0.0", "description": name,
                "input": "hook-context@1.0"}
    if budget is not None:
        manifest["time_budget_seconds"] = budget
    (d / "skill.json").write_text(json.dumps(manifest))
    if register:
        reg_path = tmp_path / "skills" / "registry.json"
        reg = json.loads(reg_path.read_text()) if reg_path.exists() else \
            {"contract_version": "2.0", "skills": {}}
        reg["skills"][name] = {"dir": name, "version": "1.0.0", "description": name}
        reg_path.write_text(json.dumps(reg))
    return d


def _bridge(calls, by_skill=None, default=None):
    """Fake bridge: answers per prompt text, records every request."""
    default = default or {"status": "ok", "verdict": "pass", "reason": "fine",
                          "report": "# ok", "error": ""}

    def bridge(request, config):
        calls.append(request)
        for name, answer in (by_skill or {}).items():
            if f"Task for {name}." == request["task"]:
                return answer
        return default
    return bridge


def _no_dispatch(job, jobs_dir):
    raise AssertionError("no async skills expected")


def _run(tmp_path, plan, modes=None, bridge=None, dispatch=_no_dispatch, **kw):
    return execute_plan(plan, CTX, skills_dir=str(tmp_path / "skills"),
                        root=str(tmp_path), run_id="RUN-1",
                        modes=modes if modes is not None else {s: "sync" for s in plan},
                        bridge=bridge or _bridge([]), dispatch=dispatch, **kw)


# --- sync path ---

def test_sync_pass_is_success_and_writes_result(tmp_path):
    _make_skill(tmp_path, "alpha")
    calls = []
    summary = _run(tmp_path, ["alpha"], bridge=_bridge(calls))
    r = summary["results"][0]
    assert (r["status"], r["verdict"], r["mode"]) == ("success", "pass", "sync")
    assert r["output_file"].startswith("_aioutput/alpha/")
    text = (tmp_path / r["output_file"]).read_text(encoding="utf-8")
    assert '"RUN-1"' in text and "# ok" in text
    assert calls[0]["task"] == "Task for alpha."
    assert calls[0]["context"] == CTX
    assert calls[0]["root"] == str(tmp_path)  # 010: Claude runs in the repo root
    assert summary["schema_version"] == SUMMARY_SCHEMA_VERSION
    assert summary["overall"] == "success"


def test_sync_fail_verdict_is_failure_with_file(tmp_path):
    _make_skill(tmp_path, "alpha")
    fail = {"status": "ok", "verdict": "fail", "reason": "TODO-BLOCK in a.py",
            "report": "found it", "error": ""}
    r = _run(tmp_path, ["alpha"], bridge=_bridge([], default=fail))["results"][0]
    assert (r["status"], r["detail"]) == ("failure", "TODO-BLOCK in a.py")
    assert r["output_file"]


@pytest.mark.parametrize("answer,status", [
    ({"status": "unavailable", "error": "no claude", "report": ""}, "error"),
    ({"status": "error", "error": "boom", "report": ""}, "error"),
    ({"status": "timeout", "error": "slow", "report": ""}, "timeout"),
])
def test_bridge_problems_are_error_or_timeout_without_file(tmp_path, answer, status):
    _make_skill(tmp_path, "alpha")
    r = _run(tmp_path, ["alpha"], bridge=_bridge([], default=answer))["results"][0]
    assert r["status"] == status and r["output_file"] is None
    assert not (tmp_path / "_aioutput").exists()


def test_report_without_verdict_is_kept_as_invalid(tmp_path):
    _make_skill(tmp_path, "alpha")
    answer = {"status": "error", "verdict": None, "report": "prose only",
              "error": "invalid verdict"}
    r = _run(tmp_path, ["alpha"], bridge=_bridge([], default=answer))["results"][0]
    assert r["status"] == "error"
    assert 'verdict: "invalid"' in (tmp_path / r["output_file"]).read_text(encoding="utf-8")


def test_unregistered_skill_is_skipped_without_calling_claude(tmp_path):
    calls = []
    r = _run(tmp_path, ["ghost"], bridge=_bridge(calls))["results"][0]
    assert r["status"] == "skipped" and "not registered" in r["detail"]
    assert calls == []


def test_skill_that_gained_code_after_registration_is_skipped(tmp_path):
    d = _make_skill(tmp_path, "alpha")
    (d / "run").write_text("#!/bin/sh\necho hi\n")
    calls = []
    r = _run(tmp_path, ["alpha"], bridge=_bridge(calls))["results"][0]
    assert r["status"] == "skipped" and "executable-code" in r["detail"]
    assert calls == []


def test_unwritable_output_degrades_to_error(tmp_path):
    _make_skill(tmp_path, "alpha")
    (tmp_path / "_aioutput").write_text("a file, not a dir")
    r = _run(tmp_path, ["alpha"])["results"][0]
    assert r["status"] == "error" and "not written" in r["detail"]


def test_timeout_is_min_of_budget_and_remaining_ceiling(tmp_path):
    _make_skill(tmp_path, "alpha", budget=45)
    _make_skill(tmp_path, "bravo", budget=5)
    calls = []
    _run(tmp_path, ["alpha", "bravo"], bridge=_bridge(calls), sync_ceiling=30)
    assert calls[0]["options"]["timeout_seconds"] == pytest.approx(30, abs=1)
    assert calls[1]["options"]["timeout_seconds"] == 5


def test_exhausted_ceiling_times_out_remaining_skills_without_a_call(tmp_path):
    _make_skill(tmp_path, "alpha")
    _make_skill(tmp_path, "bravo")
    ticks = iter([0.0, 0.0, 200.0, 200.0, 200.0])  # alpha "takes" 200 s
    calls = []
    summary = execute_plan(["alpha", "bravo"], CTX, skills_dir=str(tmp_path / "skills"),
                           root=str(tmp_path), run_id="R", modes={"alpha": "sync", "bravo": "sync"},
                           sync_ceiling=120, bridge=_bridge(calls),
                           dispatch=_no_dispatch, clock=lambda: next(ticks))
    assert [r["status"] for r in summary["results"]] == ["success", "timeout"]
    assert "ceiling" in summary["results"][1]["detail"]
    assert len(calls) == 1


def test_plan_order_preserved_and_mixed_overall(tmp_path):
    for n in ("bravo", "alpha"):
        _make_skill(tmp_path, n)
    summary = _run(tmp_path, ["bravo", "ghost", "alpha"])
    assert [r["skill"] for r in summary["results"]] == ["bravo", "ghost", "alpha"]
    assert summary["overall"] == "partial-failure"


def test_empty_plan(tmp_path):
    assert _run(tmp_path, [])["overall"] == "empty"


# --- async path ---

def test_async_skills_are_dispatched_not_run(tmp_path):
    _make_skill(tmp_path, "alpha")
    _make_skill(tmp_path, "bravo")
    jobs, calls = [], []

    def dispatch(job, jobs_dir):
        jobs.append((job, jobs_dir))
        return True, "", "logs/async/RUN-1.json"

    summary = _run(tmp_path, ["alpha", "bravo"], modes={"alpha": "async"},
                   bridge=_bridge(calls), dispatch=dispatch)
    statuses = {r["skill"]: (r["mode"], r["status"]) for r in summary["results"]}
    # bravo has no mode configured → the default, async.
    assert statuses == {"alpha": ("async", "dispatched"), "bravo": ("async", "dispatched")}
    assert jobs[0][0]["plan"] == ["alpha", "bravo"] and calls == []
    assert summary["async_job"] == "logs/async/RUN-1.json"


def test_failed_dispatch_is_recorded(tmp_path):
    _make_skill(tmp_path, "alpha")
    summary = _run(tmp_path, ["alpha"], modes={"alpha": "async"},
                   dispatch=lambda job, d: (False, "worker not started: nope", None))
    r = summary["results"][0]
    assert r["status"] == "dispatch-failed" and "nope" in r["detail"]


def test_dispatch_writes_job_and_spawns_detached_worker(tmp_path):
    spawned = []
    ok, detail, job_path = dispatch_async(
        {"run_id": "RUN-9", "plan": ["a"]}, str(tmp_path / "jobs"),
        spawn=lambda argv, **kw: spawned.append((argv, kw)), platform="posix")
    assert ok and detail == ""
    assert json.loads(Path(job_path).read_text())["run_id"] == "RUN-9"
    argv, kw = spawned[0]
    assert argv == [sys.executable, WORKER, job_path]
    assert kw["start_new_session"] is True and kw["stdin"] == subprocess.DEVNULL


def test_dispatch_spawn_failure(tmp_path):
    def boom(argv, **kw):
        raise OSError("no fork")
    ok, detail, _ = dispatch_async({"run_id": "R"}, str(tmp_path), spawn=boom)
    assert not ok and "no fork" in detail


def test_dispatch_unwritable_jobs_dir(tmp_path):
    blocker = tmp_path / "jobs"
    blocker.write_text("file")
    ok, _detail, job_path = dispatch_async({"run_id": "R"}, str(blocker),
                                          spawn=lambda *a, **k: None)
    assert not ok and job_path is None


def test_detach_kwargs_per_platform():
    nt = detach_kwargs("nt")
    assert nt["creationflags"] & 0x8 and "start_new_session" not in nt
    assert detach_kwargs("posix")["start_new_session"] is True


def test_real_dispatch_returns_before_worker_finishes(tmp_path):
    def spawn_sleeper(argv, **kw):
        return subprocess.Popen([sys.executable, "-c", "import time; time.sleep(3)"], **kw)
    t = time.monotonic()
    ok, _, _ = dispatch_async({"run_id": "R"}, str(tmp_path), spawn=spawn_sleeper)
    assert ok and time.monotonic() - t < 0.5


# --- pure helpers ---

@pytest.mark.parametrize("manifest,expected", [
    ({}, 60.0), ({"time_budget_seconds": 12}, 12.0), ({"time_budget_seconds": 0}, 60.0),
    ({"time_budget_seconds": 601}, 60.0), ({"time_budget_seconds": True}, 60.0),
])
def test_budget_of(manifest, expected):
    assert budget_of(manifest) == expected


@pytest.mark.parametrize("result,status", [
    ({"status": "ok", "verdict": "pass"}, "success"),
    ({"status": "ok", "verdict": "fail"}, "failure"),
    ({"status": "timeout"}, "timeout"),
    ({"status": "unavailable"}, "error"),
    ({"status": "bad-request"}, "error"),
    ({}, "error"),
])
def test_classify(result, status):
    assert classify(result)[0] == status
