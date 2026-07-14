"""Tests for src/route_workflows.py — workflow router (feature 004)."""
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

from route_workflows import RESULT_SCHEMA_VERSION, route  # noqa: E402


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
