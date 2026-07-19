"""Tests for src/route_workflows.py — workflow router (feature 004)."""
import json
import subprocess
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

from route_workflows import (  # noqa: E402
    RESULT_SCHEMA_VERSION,
    load_config,
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


# --- skills invoker + CLI (Task 4) ---

OK_RESULT = ('{"schema_version": "1.0", "skill": "x", "status": "ok", '
             '"summary": "done", "details": {}}')


def _make_skill(tmp_path, name,
                script=f"#!/bin/sh\ncat > /dev/null\nprintf %s '{OK_RESULT}'\n",
                registered=True):
    d = tmp_path / "skills" / name
    d.mkdir(parents=True)
    run = d / "run"
    run.write_text(script)
    run.chmod(0o755)
    if registered:
        reg_path = tmp_path / "skills" / "registry.json"
        reg = json.loads(reg_path.read_text()) if reg_path.exists() else \
            {"contract_version": "1.1", "skills": {}}
        reg["skills"][name] = {"dir": name, "version": "1.0.0", "description": name}
        reg_path.write_text(json.dumps(reg))
    return d


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


def _run_cli(stdin_text, *args, cwd=None):
    return subprocess.run(
        [sys.executable, str(REPO_ROOT / "src" / "route_workflows.py"), *args],
        input=stdin_text, capture_output=True, text=True, timeout=10,
        cwd=cwd or REPO_ROOT,
    )


def test_cli_routes_context_from_stdin_exit_zero(tmp_path):
    cfg = tmp_path / "routes.json"
    cfg.write_text('{"version": "1.0", "routes": {"pre-commit": []}}')
    r = _run_cli(json.dumps(_ctx()), "--config", str(cfg))
    assert r.returncode == 0
    out = json.loads(r.stdout)
    assert out["event"] == "pre-commit" and out["results"] == []
    assert out["schema_version"] == RESULT_SCHEMA_VERSION
    assert out["overall"] == "empty"
    assert out["execution"]["results"] == []


def test_load_config_accepts_outcomes_and_retention(tmp_path):
    p = tmp_path / "routes.json"
    p.write_text(json.dumps({
        "version": "1.1", "routes": {"pre-commit": ["a"]},
        "outcomes": {"a": {"on_failure": "block"}}, "run_retention": 7}))
    warnings = []
    cfg = load_config(str(p), warnings)
    assert cfg["outcomes"] == {"a": {"on_failure": "block"}}
    assert cfg["run_retention"] == 7
    assert warnings == []


def test_load_config_bad_outcomes_shape_ignored_with_warning(tmp_path):
    p = tmp_path / "routes.json"
    p.write_text('{"version": "1.1", "routes": {}, "outcomes": ["nope"], "run_retention": "many"}')
    warnings = []
    cfg = load_config(str(p), warnings)
    assert cfg["outcomes"] == {} and cfg["run_retention"] == 50
    assert any("outcomes" in w for w in warnings)
    assert any("run_retention" in w for w in warnings)


def _outcome_cli(tmp_path, rule, event="pre-commit", skill_script="#!/bin/sh\nexit 1\n"):
    _make_skill(tmp_path, "gate", script=skill_script)
    cfg = tmp_path / "routes.json"
    outcomes = {"gate": rule} if rule else {}
    cfg.write_text(json.dumps({"version": "1.1", "routes": {event: ["gate"]},
                               "outcomes": outcomes}))
    runs = tmp_path / "runs"
    return _run_cli(json.dumps(_ctx(event)), "--config", str(cfg),
                    "--skills-dir", str(tmp_path / "skills"),
                    "--runs-dir", str(runs)), runs


def test_cli_block_rule_exits_ten_with_message(tmp_path):
    r, runs = _outcome_cli(tmp_path, {"on_failure": "block"})
    assert r.returncode == 10
    assert "[hook blocked]" in r.stderr and "gate" in r.stderr
    out = json.loads(r.stdout)
    assert out["final_outcome"] == "block"
    assert out["run_record"] and (runs / Path(out["run_record"]).name).exists()


def test_cli_default_warn_exits_zero_with_warning(tmp_path):
    r, runs = _outcome_cli(tmp_path, None)
    assert r.returncode == 0
    assert "[router warning]" in r.stderr
    assert json.loads(r.stdout)["final_outcome"] == "warn"


def test_cli_skip_rule_silent_but_recorded(tmp_path):
    r, runs = _outcome_cli(tmp_path, {"on_failure": "skip"})
    assert r.returncode == 0
    assert "[router warning]" not in r.stderr and "[hook blocked]" not in r.stderr
    out = json.loads(r.stdout)
    assert out["final_outcome"] == "none"
    rec = json.loads(next(runs.glob("*.json")).read_text())
    assert rec["results"][0]["outcome"] == "skip"


def test_cli_post_merge_block_downgraded(tmp_path):
    r, runs = _outcome_cli(tmp_path, {"on_failure": "block"}, event="post-merge")
    assert r.returncode == 0
    assert "[hook blocked]" not in r.stderr and "[router warning]" in r.stderr
    out = json.loads(r.stdout)
    assert out["final_outcome"] == "warn"


def test_cli_success_writes_record_no_messages(tmp_path):
    r, runs = _outcome_cli(tmp_path, {"on_failure": "block"},
                           skill_script=f"#!/bin/sh\ncat > /dev/null\nprintf %s '{OK_RESULT}'\n")
    assert r.returncode == 0
    assert r.stderr.strip() == ""
    out = json.loads(r.stdout)
    assert out["final_outcome"] == "none"
    assert len(list(runs.glob("*.json"))) == 1


def test_cli_dispatch_via_executor_v11_shape(tmp_path):
    _make_skill(tmp_path, "good")
    _make_skill(tmp_path, "bad", script="#!/bin/sh\nexit 1\n")
    cfg = tmp_path / "routes.json"
    cfg.write_text('{"version": "1.0", "routes": {"pre-commit": ["good", "bad", "ghost"]}}')
    r = _run_cli(json.dumps(_ctx()), "--config", str(cfg),
                 "--skills-dir", str(tmp_path / "skills"))
    assert r.returncode == 0
    out = json.loads(r.stdout)
    entries = {e["workflow"]: e for e in out["results"]}
    assert entries["good"]["outcome"] == "invoked"
    assert entries["good"]["status"] == "success"
    assert entries["bad"]["outcome"] == "failed"
    assert entries["bad"]["status"] == "failure"
    assert entries["ghost"]["outcome"] == "unresolvable"
    assert entries["ghost"]["status"] == "skipped"
    assert all(isinstance(e["duration_ms"], int) for e in out["results"])
    assert out["overall"] == "partial-failure"
    assert [e["skill"] for e in out["execution"]["results"]] == ["good", "bad", "ghost"]
    assert "ghost" in r.stderr and "bad" in r.stderr  # warnings still visible


def test_cli_garbage_stdin_exit_zero_with_warning():
    r = _run_cli("{not json")
    assert r.returncode == 0
    assert "[router warning]" in r.stderr


def test_cli_missing_config_warns_on_stderr(tmp_path):
    r = _run_cli(json.dumps(_ctx()), "--config", str(tmp_path / "none.json"))
    assert r.returncode == 0
    assert "[router warning]" in r.stderr


def test_cli_log_appends_summary_line(tmp_path):
    cfg = tmp_path / "routes.json"
    cfg.write_text('{"version": "1.0", "routes": {"pre-commit": []}}')
    log = tmp_path / "hooks.log"
    _run_cli(json.dumps(_ctx()), "--config", str(cfg), "--log", str(log))
    line = log.read_text().strip()
    assert "pre-commit" in line and line.startswith("[")


def test_selection_under_100ms(tmp_path):
    cfg = tmp_path / "routes.json"
    cfg.write_text(json.dumps(
        {"version": "1.0", "routes": {"pre-commit": [f"wf{i}" for i in range(100)]}}))
    warnings = []
    t0 = time.monotonic()
    config = load_config(str(cfg), warnings)
    route(_ctx(), config, lambda i, c: ("invoked", ""))
    assert time.monotonic() - t0 < 0.1
