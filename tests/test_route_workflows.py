"""Tests for src/route_workflows.py — workflow router (004, modes since 009)."""
import io
import json
import subprocess
import sys
import time
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

from route_workflows import (  # noqa: E402
    RESULT_SCHEMA_VERSION,
    load_config,
    main,
    route,
    select_plan,
)


def _ctx(event="pre-commit", **kw):
    return {"event": event, "branch": "main", "files": ["a.py"], **kw}


def _config(**routes):
    return {"version": "1.0", "routes": {k.replace("_", "-"): v for k, v in routes.items()}}


def _recording_invoker(calls, outcome="invoked", detail=""):
    def invoker(identifier, context):
        calls.append((identifier, context))
        return outcome, detail
    return invoker


def test_mapped_workflows_invoked_in_configured_order_with_context():
    calls = []
    ctx = _ctx()
    result = route(ctx, _config(pre_commit=["b-flow", "a-flow"]), _recording_invoker(calls))
    assert [c[0] for c in calls] == ["b-flow", "a-flow"]  # configured order, not sorted
    assert all(c[1] is ctx for c in calls)
    assert result["schema_version"] == RESULT_SCHEMA_VERSION
    assert result["event"] == "pre-commit"
    assert [r["workflow"] for r in result["results"]] == ["b-flow", "a-flow"]
    assert all(r["outcome"] == "invoked" for r in result["results"])
    assert result["warnings"] == []


def test_other_events_workflows_not_invoked():
    calls = []
    route(_ctx("post-merge"), _config(pre_commit=["a"], post_merge=["m"]),
          _recording_invoker(calls))
    assert [c[0] for c in calls] == ["m"]


def test_unconfigured_event_skips_dispatch():
    calls = []
    result = route(_ctx("pre-push"), _config(pre_commit=["a"]), _recording_invoker(calls))
    assert calls == [] and result["results"] == []


def test_empty_route_list_skips_dispatch():
    calls = []
    result = route(_ctx(), _config(pre_commit=[]), _recording_invoker(calls))
    assert calls == [] and result["results"] == []


def test_failure_is_isolated_and_warned():
    calls = []

    def flaky(identifier, context):
        calls.append(identifier)
        if identifier == "boom":
            raise RuntimeError("kaput")
        return "invoked", ""

    result = route(_ctx(), _config(pre_commit=["boom", "after"]), flaky)
    assert calls == ["boom", "after"]  # subsequent workflow still ran
    outcomes = {r["workflow"]: r["outcome"] for r in result["results"]}
    assert outcomes == {"boom": "failed", "after": "invoked"}
    assert any("boom" in w for w in result["warnings"])


def test_unresolvable_and_failed_outcomes_produce_warnings():
    def invoker(identifier, context):
        return ("unresolvable", "no such skill") if identifier == "ghost" \
            else ("failed", "exit 2")

    result = route(_ctx(), _config(pre_commit=["ghost", "broken"]), invoker)
    assert any("ghost" in w for w in result["warnings"])
    assert any("broken" in w for w in result["warnings"])


def test_unroutable_context_warns_and_skips():
    calls = []
    result = route({"event": None, "branch": None, "files": []},
                   _config(pre_commit=["a"]), _recording_invoker(calls))
    assert calls == [] and result["results"] == []
    assert any("event" in w for w in result["warnings"])
    assert result["event"] is None


def test_invalid_invoker_outcome_coerced_to_failed():
    result = route(_ctx(), _config(pre_commit=["odd"]), lambda i, c: ("weird", "?"))
    assert result["results"][0]["outcome"] == "failed"


# --- load_config (Task 3) ---

def test_load_config_valid_file(tmp_path):
    p = tmp_path / "routes.json"
    p.write_text('{"version": "1.0", "routes": {"pre-commit": ["a"]}}')
    warnings = []
    cfg = load_config(str(p), warnings)
    assert cfg["routes"] == {"pre-commit": ["a"]} and warnings == []


def test_load_config_missing_file(tmp_path):
    warnings = []
    cfg = load_config(str(tmp_path / "nope.json"), warnings)
    assert cfg["routes"] == {} and len(warnings) == 1


def test_load_config_malformed_json(tmp_path):
    p = tmp_path / "routes.json"
    p.write_text("{not json")
    warnings = []
    cfg = load_config(str(p), warnings)
    assert cfg["routes"] == {} and any("routes.json" in w for w in warnings)


def test_load_config_routes_not_a_dict(tmp_path):
    p = tmp_path / "routes.json"
    p.write_text('{"version": "1.0", "routes": ["a"]}')
    warnings = []
    cfg = load_config(str(p), warnings)
    assert cfg["routes"] == {} and warnings


def test_load_config_bad_route_value_isolated(tmp_path):
    p = tmp_path / "routes.json"
    p.write_text('{"version": "1.0", "routes": {"pre-commit": "oops", "pre-push": ["ok"]}}')
    warnings = []
    cfg = load_config(str(p), warnings)
    assert cfg["routes"]["pre-commit"] == []
    assert cfg["routes"]["pre-push"] == ["ok"]
    assert any("pre-commit" in w for w in warnings)


def test_load_config_unknown_event_key_ignored(tmp_path):
    p = tmp_path / "routes.json"
    p.write_text('{"version": "1.0", "routes": {"post-checkout": ["x"], "pre-push": []}}')
    warnings = []
    cfg = load_config(str(p), warnings)
    assert "post-checkout" not in cfg["routes"]
    assert any("post-checkout" in w for w in warnings)




# --- select_plan ---

def test_select_plan_returns_configured_order():
    warnings = []
    plan = select_plan(_ctx(), _config(pre_commit=["b", "a"]), warnings)
    assert plan == ["b", "a"] and warnings == []


def test_select_plan_unroutable_context_warns():
    warnings = []
    plan = select_plan({"event": None}, _config(pre_commit=["a"]), warnings)
    assert plan == [] and any("event" in w for w in warnings)


def test_select_plan_unconfigured_event_empty_no_warning():
    warnings = []
    plan = select_plan(_ctx("pre-push"), _config(pre_commit=["a"]), warnings)
    assert plan == [] and warnings == []


# --- routes v2.0 config (009) ---

def _load(tmp_path, raw):
    p = tmp_path / "routes.json"
    p.write_text(json.dumps(raw))
    warnings = []
    return load_config(str(p), warnings), warnings


def test_v2_skill_modes_default_async_and_invalid_warns(tmp_path):
    cfg, warnings = _load(tmp_path, {"version": "2.0", "routes": {},
                                     "skills": {"a": {"mode": "sync", "on_failure": "block"},
                                                "b": {}, "c": {"mode": "later"}}})
    assert {n: r["mode"] for n, r in cfg["skills"].items()} == \
        {"a": "sync", "b": "async", "c": "async"}
    assert len(warnings) == 1 and "later" in warnings[0]


def test_v2_block_on_async_skill_warns(tmp_path):
    _cfg, warnings = _load(tmp_path, {"routes": {},
                                      "skills": {"a": {"on_failure": "block"}}})
    assert any("only sync skills block" in w for w in warnings)


@pytest.mark.parametrize("value,expected,warned", [
    (30, 30.0, False), (600, 600.0, False), (0, 120.0, True),
    (601, 120.0, True), ("soon", 120.0, True), (True, 120.0, True)])
def test_v2_sync_ceiling_bounds(tmp_path, value, expected, warned):
    cfg, warnings = _load(tmp_path, {"routes": {}, "sync_ceiling_seconds": value})
    assert cfg["sync_ceiling_seconds"] == expected
    assert bool(warnings) is warned


def test_v2_retentions(tmp_path):
    cfg, warnings = _load(tmp_path, {"routes": {}, "run_retention": 7,
                                     "output_retention": 3})
    assert (cfg["run_retention"], cfg["output_retention"]) == (7, 3) and warnings == []
    cfg, warnings = _load(tmp_path, {"routes": {}, "output_retention": -1,
                                     "run_retention": "many"})
    assert (cfg["run_retention"], cfg["output_retention"]) == (50, 50)
    assert len(warnings) == 2


def test_legacy_outcomes_fallback_with_deprecation(tmp_path):
    cfg, warnings = _load(tmp_path, {
        "version": "1.1", "routes": {},
        "skills": {"b": {"mode": "sync", "on_failure": "warn"}},
        "outcomes": {"a": {"on_failure": "block"}, "b": {"on_failure": "block"}}})
    assert cfg["skills"]["a"] == {"on_failure": "block", "mode": "async"}
    assert cfg["skills"]["b"]["on_failure"] == "warn"  # skills wins
    assert any("deprecated" in w for w in warnings)


def test_bad_skills_and_outcomes_shapes_ignored(tmp_path):
    cfg, warnings = _load(tmp_path, {"routes": {}, "skills": ["x"], "outcomes": ["y"]})
    assert cfg["skills"] == {}
    assert any("'skills'" in w for w in warnings) and any("'outcomes'" in w for w in warnings)


def test_shipped_routes_config_is_clean():
    warnings = []
    cfg = load_config(str(REPO_ROOT / "config" / "routes.json"), warnings)
    assert warnings == [] and cfg["version"] == "2.0"


# --- CLI (in-process: the fake bridge stands in for Claude) ---

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
    return d


def _fake_bridge(verdict="pass", status="ok"):
    def bridge(request, config):
        return {"status": status, "verdict": verdict if status == "ok" else None,
                "reason": f"verdict {verdict}", "report": "# report",
                "error": "" if status == "ok" else "claude not found"}
    return bridge


def _no_dispatch(job, jobs_dir):
    raise AssertionError("unexpected async dispatch")


def _main(tmp_path, monkeypatch, capsys, ctx, routes, bridge=None,
          dispatch=_no_dispatch):
    cfg = tmp_path / "routes.json"
    cfg.write_text(json.dumps(routes))
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(ctx)))
    code = main(["--config", str(cfg), "--skills-dir", str(tmp_path / "skills"),
                 "--root", str(tmp_path), "--log", str(tmp_path / "logs" / "hooks.log"),
                 "--bridge-config", str(tmp_path / "no-bridge.json")],
                bridge=bridge or _fake_bridge(), dispatch=dispatch)
    captured = capsys.readouterr()
    return code, json.loads(captured.out), captured.err


def _gate(event="pre-commit", rule=None, mode="sync"):
    return {"version": "2.0", "routes": {event: ["gate"]},
            "skills": {"gate": {"mode": mode, **({"on_failure": rule} if rule else {})}}}


def _log(tmp_path):
    return (tmp_path / "logs" / "hooks.log").read_text(encoding="utf-8")


def test_cli_sync_block_exits_ten_with_single_blocked_line(tmp_path, monkeypatch, capsys):
    _make_skill(tmp_path, "gate")
    code, out, err = _main(tmp_path, monkeypatch, capsys, _ctx(), _gate(rule="block"),
                           bridge=_fake_bridge("fail"))
    assert code == 10
    lines = err.strip().splitlines()
    assert len(lines) == 1
    assert lines[0].startswith("[hook blocked] skill 'gate': verdict fail (see _aioutput/gate/")
    entry = out["results"][0]
    assert (entry["mode"], entry["status"], entry["verdict"]) == ("sync", "failure", "fail")
    assert (tmp_path / entry["output_file"]).exists()
    assert out["schema_version"] == RESULT_SCHEMA_VERSION == "2.0"
    rec = json.loads(Path(out["run_record"]).read_text())
    assert rec["id"] == out["run_id"] and rec["final_outcome"] == "block"


def test_cli_warn_is_silent_and_logged(tmp_path, monkeypatch, capsys):
    _make_skill(tmp_path, "gate")
    code, out, err = _main(tmp_path, monkeypatch, capsys, _ctx(), _gate(rule="warn"),
                           bridge=_fake_bridge("fail"))
    assert code == 0 and err == ""
    assert out["final_outcome"] == "warn"
    assert "warning workflow 'gate' failed: verdict fail" in _log(tmp_path)


def test_cli_claude_unavailable_never_blocks(tmp_path, monkeypatch, capsys):
    _make_skill(tmp_path, "gate")
    code, out, err = _main(tmp_path, monkeypatch, capsys, _ctx(), _gate(rule="block"),
                           bridge=_fake_bridge(status="unavailable"))
    assert code == 0 and err == ""
    assert out["results"][0]["status"] == "error"
    assert "claude not found" in _log(tmp_path)


def test_cli_post_merge_block_downgraded(tmp_path, monkeypatch, capsys):
    _make_skill(tmp_path, "gate")
    code, out, err = _main(tmp_path, monkeypatch, capsys, _ctx("post-merge"),
                           _gate("post-merge", rule="block"), bridge=_fake_bridge("fail"))
    assert code == 0 and err == "" and out["final_outcome"] == "warn"


def test_cli_skip_rule_silent_but_recorded(tmp_path, monkeypatch, capsys):
    _make_skill(tmp_path, "gate")
    code, out, err = _main(tmp_path, monkeypatch, capsys, _ctx(), _gate(rule="skip"),
                           bridge=_fake_bridge("fail"))
    assert code == 0 and err == "" and out["final_outcome"] == "none"
    assert out["outcomes"][0]["outcome"] == "skip"


def test_cli_success_silent(tmp_path, monkeypatch, capsys):
    _make_skill(tmp_path, "gate")
    code, out, err = _main(tmp_path, monkeypatch, capsys, _ctx(), _gate(rule="block"))
    assert code == 0 and err == "" and out["final_outcome"] == "none"


def test_cli_async_skill_dispatched_with_job(tmp_path, monkeypatch, capsys):
    _make_skill(tmp_path, "gate")
    jobs = []

    def dispatch(job, jobs_dir):
        jobs.append((job, jobs_dir))
        return True, "", "logs/async/x.json"

    code, out, err = _main(tmp_path, monkeypatch, capsys, _ctx(),
                           _gate(rule="block", mode="async"), dispatch=dispatch)
    assert code == 0 and err == ""
    assert out["results"][0]["status"] == "dispatched"
    job, jobs_dir = jobs[0]
    assert job["run_id"] == out["run_id"] and job["plan"] == ["gate"]
    assert job["outcome_rules"]["gate"]["mode"] == "async"
    assert jobs_dir == str(tmp_path / "logs" / "async")


def test_cli_mixed_plan_shape(tmp_path, monkeypatch, capsys):
    _make_skill(tmp_path, "good")
    routes = {"version": "2.0", "routes": {"pre-commit": ["good", "ghost"]},
              "skills": {"good": {"mode": "sync"}, "ghost": {"mode": "sync"}}}
    code, out, err = _main(tmp_path, monkeypatch, capsys, _ctx(), routes)
    entries = {e["workflow"]: e for e in out["results"]}
    assert entries["good"]["outcome"] == "invoked"
    assert entries["ghost"]["outcome"] == "unresolvable"
    assert out["overall"] == "partial-failure" and code == 0 and err == ""


# --- CLI as a subprocess (no skills, so no Claude) ---

def _run_cli(stdin_text, *args, cwd=None):
    return subprocess.run(
        [sys.executable, str(REPO_ROOT / "src" / "route_workflows.py"), *args],
        input=stdin_text, capture_output=True, text=True, timeout=10,
        cwd=cwd or REPO_ROOT,
    )


def test_cli_routes_context_from_stdin_exit_zero(tmp_path):
    cfg = tmp_path / "routes.json"
    cfg.write_text('{"version": "2.0", "routes": {"pre-commit": []}}')
    r = _run_cli(json.dumps(_ctx()), "--config", str(cfg), "--root", str(tmp_path))
    assert r.returncode == 0 and r.stderr == ""
    out = json.loads(r.stdout)
    assert out["event"] == "pre-commit" and out["results"] == []
    assert out["overall"] == "empty" and out["execution"]["results"] == []
    assert list((tmp_path / "logs" / "runs").glob("*.json"))


def test_cli_garbage_stdin_exit_zero_and_logged(tmp_path):
    log = tmp_path / "hooks.log"
    r = _run_cli("{not json", "--log", str(log), "--root", str(tmp_path))
    assert r.returncode == 0 and r.stderr == ""
    assert "unreadable context" in log.read_text()


def test_cli_missing_config_logged(tmp_path):
    log = tmp_path / "hooks.log"
    r = _run_cli(json.dumps(_ctx()), "--config", str(tmp_path / "none.json"),
                 "--log", str(log), "--root", str(tmp_path))
    assert r.returncode == 0 and r.stderr == ""
    assert "routing config not found" in log.read_text()


def test_cli_log_appends_summary_line(tmp_path):
    cfg = tmp_path / "routes.json"
    cfg.write_text('{"version": "2.0", "routes": {"pre-commit": []}}')
    log = tmp_path / "hooks.log"
    _run_cli(json.dumps(_ctx()), "--config", str(cfg), "--log", str(log),
             "--root", str(tmp_path))
    line = log.read_text().strip()
    assert "pre-commit" in line and line.startswith("[")


def test_selection_under_100ms(tmp_path):
    cfg = tmp_path / "routes.json"
    cfg.write_text(json.dumps(
        {"version": "2.0", "routes": {"pre-commit": [f"wf{i}" for i in range(100)]}}))
    warnings = []
    t0 = time.monotonic()
    config = load_config(str(cfg), warnings)
    route(_ctx(), config, lambda i, c: ("invoked", ""))
    assert time.monotonic() - t0 < 0.1
