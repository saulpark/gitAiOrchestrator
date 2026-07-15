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
    make_skills_invoker,
    route,
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

def _make_skill(tmp_path, name, script="#!/bin/sh\ncat > /dev/null\nexit 0\n"):
    d = tmp_path / "skills" / name
    d.mkdir(parents=True)
    run = d / "run"
    run.write_text(script)
    run.chmod(0o755)
    return d


def test_skills_invoker_runs_executable_with_context_on_stdin(tmp_path):
    _make_skill(tmp_path, "echoer",
                "#!/bin/sh\ncat > \"$(dirname \"$0\")/got.json\"\nexit 0\n")
    invoker = make_skills_invoker(str(tmp_path / "skills"))
    outcome, detail = invoker("echoer", _ctx())
    assert outcome == "invoked"
    got = json.loads((tmp_path / "skills" / "echoer" / "got.json").read_text())
    assert got["event"] == "pre-commit"


def test_skills_invoker_nonzero_exit_is_failed(tmp_path):
    _make_skill(tmp_path, "broken", "#!/bin/sh\nexit 3\n")
    invoker = make_skills_invoker(str(tmp_path / "skills"))
    outcome, detail = invoker("broken", _ctx())
    assert outcome == "failed" and "3" in detail


def test_skills_invoker_missing_skill_unresolvable(tmp_path):
    invoker = make_skills_invoker(str(tmp_path / "skills"))
    outcome, _ = invoker("ghost", _ctx())
    assert outcome == "unresolvable"


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
