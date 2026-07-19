"""Tests for src/claude_bridge.py — Claude Code bridge (feature 007)."""
import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

from claude_bridge import (  # noqa: E402
    DEFAULT_CONFIG,
    RESULT_SCHEMA_VERSION,
    build_prompt,
    invoke,
    load_bridge_config,
)

CTX = {"schema_version": "1.0", "event": "pre-commit", "branch": "main",
       "files": ["src/a.py", "src/b.py"], "commits": ["c" * 40],
       "partial": False, "unavailable": [], "errors": []}


def _request(**kw):
    return {"schema_version": "1.0", "context": CTX,
            "task": "Summarize the change.", **kw}


def _fake_runner(calls, returncode=0, stdout=None, stderr=""):
    if stdout is None:
        stdout = json.dumps({"result": "hello", "is_error": False})

    def runner(argv, prompt_stdin, timeout):
        calls.append({"argv": argv, "stdin": prompt_stdin, "timeout": timeout})
        return returncode, stdout, stderr
    return runner


# --- prompt ---

def test_prompt_contains_bounded_context_and_constraint():
    prompt = build_prompt(CTX, "Do the thing.")
    for expected in ("pre-commit", "main", "src/a.py", "src/b.py",
                     "c" * 40, "Do the thing.",
                     "Only examine the files listed above"):
        assert expected in prompt


def test_prompt_flags_partial_context():
    ctx = {**CTX, "partial": True, "unavailable": ["branch"]}
    prompt = build_prompt(ctx, "t")
    assert "partial" in prompt and "branch" in prompt


def test_prompt_states_empty_change_set():
    ctx = {**CTX, "files": [], "commits": []}
    prompt = build_prompt(ctx, "t")
    assert "no changed files" in prompt.lower()


# --- config ---

def test_config_defaults_on_missing_file(tmp_path):
    warnings = []
    cfg = load_bridge_config(str(tmp_path / "nope.json"), warnings)
    assert cfg == DEFAULT_CONFIG and warnings


def test_config_malformed_falls_back(tmp_path):
    p = tmp_path / "bridge.json"
    p.write_text("{nope")
    warnings = []
    cfg = load_bridge_config(str(p), warnings)
    assert cfg == DEFAULT_CONFIG and warnings


def test_config_bad_field_type_falls_back_per_field(tmp_path):
    p = tmp_path / "bridge.json"
    p.write_text('{"version": "1.0", "timeout_seconds": "soon", "max_turns": 2}')
    warnings = []
    cfg = load_bridge_config(str(p), warnings)
    assert cfg["timeout_seconds"] == DEFAULT_CONFIG["timeout_seconds"]
    assert cfg["max_turns"] == 2
    assert any("timeout_seconds" in w for w in warnings)


# --- invoke (injectable runner, FR-008) ---

def test_invoke_argv_shape_hooks_disabled():
    calls = []
    result = invoke(_request(), {**DEFAULT_CONFIG, "hooks_enabled": False},
                    _fake_runner(calls))
    argv = calls[0]["argv"]
    assert argv[0] == "claude" and "-p" in argv
    assert "--output-format" in argv and "json" in argv
    assert "--max-turns" in argv
    i = argv.index("--settings")
    assert json.loads(argv[i + 1]) == {"disableAllHooks": True}
    assert result["status"] == "ok"


def test_invoke_hooks_enabled_omits_override():
    calls = []
    invoke(_request(), {**DEFAULT_CONFIG, "hooks_enabled": True},
           _fake_runner(calls))
    assert "--settings" not in calls[0]["argv"]


def test_invoke_options_override_turns_and_timeout():
    calls = []
    invoke(_request(options={"max_turns": 9, "timeout_seconds": 7}),
           DEFAULT_CONFIG, _fake_runner(calls))
    argv = calls[0]["argv"]
    assert argv[argv.index("--max-turns") + 1] == "9"
    assert calls[0]["timeout"] == 7


def test_invoke_extra_args_appended():
    calls = []
    invoke(_request(), {**DEFAULT_CONFIG, "extra_args": ["--model", "opus"]},
           _fake_runner(calls))
    argv = calls[0]["argv"]
    assert argv[-2:] == ["--model", "opus"]


def test_invoke_ok_parses_output():
    result = invoke(_request(), DEFAULT_CONFIG, _fake_runner([]))
    assert result["schema_version"] == RESULT_SCHEMA_VERSION
    assert result["status"] == "ok"
    assert result["output"]["result"] == "hello"
    assert result["output_text"] == "hello"
    assert result["duration_ms"] >= 0


def test_invoke_ok_nonjson_output_kept_as_text():
    result = invoke(_request(), DEFAULT_CONFIG,
                    _fake_runner([], stdout="plain text answer"))
    assert result["status"] == "ok"
    assert result["output"] is None
    assert result["output_text"] == "plain text answer"


def test_invoke_nonzero_exit_is_error():
    result = invoke(_request(), DEFAULT_CONFIG,
                    _fake_runner([], returncode=2, stderr="boom"))
    assert result["status"] == "error" and "boom" in result["error"]


def test_invoke_timeout_status():
    def runner(argv, prompt_stdin, timeout):
        raise subprocess.TimeoutExpired(argv, timeout)
    result = invoke(_request(), DEFAULT_CONFIG, runner)
    assert result["status"] == "timeout"


def test_invoke_bad_request_missing_task():
    result = invoke({"schema_version": "1.0", "context": CTX},
                    DEFAULT_CONFIG, _fake_runner([]))
    assert result["status"] == "bad-request" and "task" in result["error"]


def test_invoke_bad_request_missing_context():
    result = invoke({"schema_version": "1.0", "task": "x"},
                    DEFAULT_CONFIG, _fake_runner([]))
    assert result["status"] == "bad-request" and "context" in result["error"]
