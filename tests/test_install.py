"""Tests for install.py — hook interpreter check (fix-windows-support)."""
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from install import _probe_python, check_hook_python  # noqa: E402


def test_first_working_candidate_is_reported():
    result = check_hook_python([["python3"], ["python"]], probe=lambda argv: True)
    assert result.status == "ok"
    assert "'python3'" in result.message


def test_store_stub_is_skipped_for_next_candidate():
    # python3 present but broken (the Windows Store stub) → falls through.
    result = check_hook_python(
        [["python3"], ["python"], ["py", "-3"]],
        probe=lambda argv: argv == ["py", "-3"],
    )
    assert result.status == "ok"
    assert "'py -3'" in result.message


def test_no_working_candidate_is_missing():
    result = check_hook_python([["python3"], ["python"]], probe=lambda argv: False)
    assert result.status == "missing"
    assert "python3, python" in result.message


def test_probe_accepts_running_interpreter():
    assert _probe_python([sys.executable]) is True


def test_probe_rejects_nonexistent_command():
    assert _probe_python(["python-not-on-path-xyz"]) is False


def test_probe_ignores_interpreter_not_on_path(monkeypatch):
    # The hooks only search PATH; the running interpreter's own directory
    # (which Windows subprocess would search first) must not count.
    monkeypatch.setenv("PATH", "")
    assert _probe_python([Path(sys.executable).stem]) is False


# --- 011: Claude can run the way the hooks run it ---------------------------

import json
import subprocess

import pytest

sys.path.insert(0, str(REPO_ROOT / "src"))

from claude_bridge import CONFINEMENT_ARGS
from install import (
    PREREQUISITES,
    check_claude_auth,
    check_tool,
    ignored_settings,
    missing_env,
    probe_claude,
    read_user_settings,
)

BEDROCK = {"env": {"CLAUDE_CODE_USE_BEDROCK": "1", "AWS_REGION": "eu-west-1",
                   "DISABLE_TELEMETRY": "1"}}


def test_missing_env_lists_only_relevant_absent_names():
    assert missing_env(BEDROCK, {"AWS_REGION": "x"}) == ["CLAUDE_CODE_USE_BEDROCK"]


def test_missing_env_empty_when_all_present():
    environ = {"CLAUDE_CODE_USE_BEDROCK": "1", "AWS_REGION": "x"}
    assert missing_env(BEDROCK, environ) == []


@pytest.mark.parametrize("settings", [{}, {"env": "nope"}, {"env": ["AWS_REGION"]}])
def test_missing_env_tolerates_absent_or_malformed_env(settings):
    assert missing_env(settings, {}) == []


@pytest.mark.parametrize("content", [None, "{nope", "[1, 2]"])
def test_read_user_settings_degrades_to_empty(tmp_path, content):
    path = tmp_path / "settings.json"
    if content is not None:
        path.write_text(content)
    assert read_user_settings(path) == {}


def test_read_user_settings_reads_object(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text(json.dumps(BEDROCK))
    assert read_user_settings(path) == BEDROCK


def test_ignored_settings_detects_auth_helpers():
    assert ignored_settings({"apiKeyHelper": "x", "model": "y"}) == ["apiKeyHelper"]


def _probe(ok, error=""):
    return lambda: (ok, error)


def test_auth_ok():
    result = check_claude_auth(BEDROCK, {"CLAUDE_CODE_USE_BEDROCK": "1", "AWS_REGION": "x"},
                               _probe(True))
    assert result.status == "ok" and result.notes == []


def test_auth_fail_names_missing_variables():
    result = check_claude_auth(BEDROCK, {}, _probe(False, "Not logged in"))
    assert result.status == "failed"
    assert result.missing == ["AWS_REGION", "CLAUDE_CODE_USE_BEDROCK"]
    assert "Not logged in" in result.error


def test_auth_fail_without_missing_names_keeps_error():
    result = check_claude_auth({}, {}, _probe(False, "api_error_status=403"))
    assert result.status == "failed" and result.missing == []
    assert "403" in result.error


def test_auth_pass_with_missing_names_is_a_note_not_a_failure():
    settings = {"env": {"ANTHROPIC_DEFAULT_SONNET_MODEL": "m"}}
    result = check_claude_auth(settings, {}, _probe(True))
    assert result.status == "ok"
    assert any("ANTHROPIC_DEFAULT_SONNET_MODEL" in n for n in result.notes)


def test_auth_skip_does_not_call_claude():
    def probe():
        raise AssertionError("probe must not run when skipped")
    result = check_claude_auth(BEDROCK, {}, probe, skip=True)
    assert result.status == "skipped"
    assert any("CLAUDE_CODE_USE_BEDROCK" in n for n in result.notes)


def test_auth_notes_ignored_settings_and_claude_session():
    result = check_claude_auth({"awsAuthRefresh": "aws sso login"}, {"CLAUDECODE": "1"},
                               _probe(True))
    assert result.ignored == ["awsAuthRefresh"]
    assert any("awsAuthRefresh" in n for n in result.notes)
    assert any("Claude Code session" in n for n in result.notes)


def _runner(calls, rc=0, stdout=None, stderr="", exc=None):
    if stdout is None:
        stdout = json.dumps({"type": "result", "subtype": "success",
                             "is_error": False, "result": "OK"})

    def run(argv, stdin, timeout):
        calls.append(argv)
        if exc:
            raise exc
        return rc, stdout, stderr
    return run


def _contains_sequence(argv, seq):
    n = len(seq)
    return any(tuple(argv[i:i + n]) == tuple(seq) for i in range(len(argv) - n + 1))


def test_probe_uses_the_hooks_confinement():
    calls = []
    assert probe_claude("claude", run=_runner(calls), which=lambda c: c) == (True, "")
    assert _contains_sequence(calls[0], CONFINEMENT_ARGS)
    assert calls[0][calls[0].index("--max-turns") + 1] == "1"


def test_probe_error_payload_is_failure():
    stdout = json.dumps({"is_error": True, "subtype": "success",
                         "result": "Not logged in · Please run /login"})
    ok, error = probe_claude("claude", run=_runner([], rc=1, stdout=stdout),
                             which=lambda c: c)
    assert not ok and "Not logged in" in error


def test_probe_nonzero_exit_uses_stderr():
    ok, error = probe_claude("claude", run=_runner([], rc=2, stdout="", stderr="boom"),
                             which=lambda c: c)
    assert not ok and "boom" in error


def test_probe_timeout_is_failure():
    exc = subprocess.TimeoutExpired(["claude"], 90)
    ok, error = probe_claude("claude", run=_runner([], exc=exc), which=lambda c: c)
    assert not ok and "90" in error


def test_probe_missing_cli_is_failure():
    ok, error = probe_claude("claude-nope", run=_runner([]), which=lambda c: None)
    assert not ok and "claude-nope" in error


@pytest.mark.parametrize("version,status", [("2.1.286 (Claude Code)", "outdated"),
                                            ("2.1.287 (Claude Code)", "ok")])
def test_claude_cli_minimum_version(monkeypatch, version, status):
    import install
    cli = next(p for p in PREREQUISITES if p.command == "claude")
    monkeypatch.setattr(install.shutil, "which", lambda c: c)
    monkeypatch.setattr(install.subprocess, "run", lambda *a, **k:
                        subprocess.CompletedProcess(a, 0, stdout=version, stderr=""))
    assert check_tool(cli).status == status
