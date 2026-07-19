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


# --- availability + CLI (Task 2) ---

def test_invoke_unavailable_when_command_missing():
    cfg = {**DEFAULT_CONFIG, "claude_command": "claude-not-on-path-xyz"}
    result = invoke(_request(), cfg)  # no runner injected → which() gate
    assert result["status"] == "unavailable"
    assert "claude-not-on-path-xyz" in result["error"]


FAKE_CLAUDE_OK = """#!/bin/sh
printf '%s\\n' "$@" > "$(dirname "$0")/argv.txt"
printf '%s' '{"result": "fake says hi", "is_error": false}'
"""


def _write_fake_claude(tmp_path, script=FAKE_CLAUDE_OK):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    fake = bin_dir / "claude"
    fake.write_text(script)
    fake.chmod(0o755)
    return bin_dir


def _run_cli(tmp_path, stdin_text, config=None, path_prefix=None):
    import os
    cfg_path = tmp_path / "bridge.json"
    cfg_path.write_text(json.dumps(config or DEFAULT_CONFIG))
    env = dict(os.environ)
    if path_prefix is not None:
        env["PATH"] = f"{path_prefix}:{env['PATH']}"
    return subprocess.run(
        [sys.executable, str(REPO_ROOT / "src" / "claude_bridge.py"),
         "--config", str(cfg_path)],
        input=stdin_text, capture_output=True, text=True, timeout=30, env=env,
    )


def test_cli_ok_with_fake_claude(tmp_path):
    bin_dir = _write_fake_claude(tmp_path)
    r = _run_cli(tmp_path, json.dumps(_request()), path_prefix=str(bin_dir))
    assert r.returncode == 0
    result = json.loads(r.stdout)
    assert result["status"] == "ok"
    assert result["output"]["result"] == "fake says hi"
    argv = (tmp_path / "bin" / "argv.txt").read_text()
    assert "-p" in argv and "src/a.py" in argv and "disableAllHooks" in argv


def test_cli_fake_claude_failure_exit_zero(tmp_path):
    bin_dir = _write_fake_claude(tmp_path, "#!/bin/sh\necho nope >&2\nexit 7\n")
    r = _run_cli(tmp_path, json.dumps(_request()), path_prefix=str(bin_dir))
    assert r.returncode == 0
    result = json.loads(r.stdout)
    assert result["status"] == "error" and "7" in result["error"]


def test_cli_fake_claude_timeout(tmp_path):
    bin_dir = _write_fake_claude(tmp_path, "#!/bin/sh\nsleep 10\n")
    r = _run_cli(tmp_path,
                 json.dumps(_request(options={"timeout_seconds": 1})),
                 path_prefix=str(bin_dir))
    assert r.returncode == 0
    assert json.loads(r.stdout)["status"] == "timeout"


def test_cli_garbage_stdin_bad_request(tmp_path):
    r = _run_cli(tmp_path, "{nope")
    assert r.returncode == 0
    assert json.loads(r.stdout)["status"] == "bad-request"


def test_cli_hooks_enabled_omits_settings_override(tmp_path):
    bin_dir = _write_fake_claude(tmp_path)
    r = _run_cli(tmp_path, json.dumps(_request()),
                 config={**DEFAULT_CONFIG, "hooks_enabled": True},
                 path_prefix=str(bin_dir))
    assert json.loads(r.stdout)["status"] == "ok"
    argv = (tmp_path / "bin" / "argv.txt").read_text()
    assert "disableAllHooks" not in argv
