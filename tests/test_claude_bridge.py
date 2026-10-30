"""Tests for src/claude_bridge.py — Claude Code bridge (007, read-only since 009)."""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

from claude_bridge import (  # noqa: E402
    CONFINEMENT_ARGS,
    DEFAULT_CONFIG,
    RESULT_SCHEMA_VERSION,
    VERDICT_SCHEMA,
    _default_runner,
    build_argv,
    build_prompt,
    cli_supports_confinement,
    hidden_window_kwargs,
    invoke,
    load_bridge_config,
    parse_verdict,
)

CTX = {"schema_version": "1.0", "event": "pre-commit", "branch": "main",
       "files": ["src/a.py", "src/b.py"], "commits": ["c" * 40],
       "partial": False, "unavailable": [], "errors": []}


def _request(**kw):
    return {"schema_version": "2.0", "context": CTX,
            "task": "Summarize the change.", **kw}


def _payload(verdict="pass", reason="all good", report="# Report\nfine"):
    data = {"verdict": verdict, "reason": reason, "report": report}
    return json.dumps({"type": "result", "subtype": "success", "is_error": False,
                       "result": json.dumps(data), "structured_output": data})


def _fake_runner(calls, returncode=0, stdout=None, stderr=""):
    if stdout is None:
        stdout = _payload()

    def runner(argv, prompt_stdin, timeout, cwd=None):
        calls.append({"argv": argv, "stdin": prompt_stdin, "timeout": timeout,
                      "cwd": cwd})
        return returncode, stdout, stderr
    return runner


# --- prompt ---

def test_prompt_contains_context_focus_scope_and_output_rules():
    prompt = build_prompt(CTX, "Do the thing.")
    for expected in ("pre-commit", "main", "src/a.py", "src/b.py",
                     "c" * 40, "Do the thing.", "focus of this run",
                     "any file inside the repository", "read-only", "verdict"):
        assert expected in prompt
    # 010: the whole repository is readable — the old do-not-scan rule is gone.
    assert "Do not scan" not in prompt


def test_prompt_names_the_repository_root_when_given(tmp_path):
    prompt = build_prompt(CTX, "t", root=str(tmp_path))
    assert str(tmp_path) in prompt
    assert "Do not read files outside it" in prompt


def test_prompt_flags_partial_context():
    ctx = {**CTX, "partial": True, "unavailable": ["branch"]}
    prompt = build_prompt(ctx, "t")
    assert "partial" in prompt and "branch" in prompt


def test_prompt_states_empty_change_set():
    prompt = build_prompt({**CTX, "files": [], "commits": []}, "t")
    assert "no changed files" in prompt.lower()


# --- argv: the confinement is unconditional (FR-003..FR-005) ---

def _contains_sequence(argv, seq):
    n = len(seq)
    return any(tuple(argv[i:i + n]) == tuple(seq) for i in range(len(argv) - n + 1))


def test_argv_always_carries_every_confinement_flag():
    argv = build_argv(DEFAULT_CONFIG, 4)
    assert _contains_sequence(argv, CONFINEMENT_ARGS)
    assert argv[argv.index("--tools") + 1] == "Read,Grep,Glob"
    assert json.loads(argv[argv.index("--settings") + 1]) == {"disableAllHooks": True}
    assert json.loads(argv[argv.index("--json-schema") + 1]) == VERDICT_SCHEMA
    assert argv[argv.index("--max-turns") + 1] == "4"


def test_removed_keys_are_ignored_with_warning(tmp_path):
    p = tmp_path / "bridge.json"
    p.write_text(json.dumps({"hooks_enabled": True,
                             "extra_args": ["--tools", "Bash,Write"]}))
    warnings = []
    cfg = load_bridge_config(str(p), warnings)
    assert "hooks_enabled" not in cfg and "extra_args" not in cfg
    assert any("hooks_enabled" in w for w in warnings)
    assert any("extra_args" in w for w in warnings)
    argv = build_argv(cfg, cfg["max_turns"])
    assert "Bash,Write" not in argv
    assert _contains_sequence(argv, CONFINEMENT_ARGS)


def test_model_is_appended_only_when_set():
    assert "--model" not in build_argv(DEFAULT_CONFIG, 1)
    argv = build_argv({**DEFAULT_CONFIG, "model": "sonnet"}, 1)
    assert argv[-2:] == ["--model", "sonnet"]


# --- config ---

def test_default_max_turns_allows_repo_wide_work():
    assert DEFAULT_CONFIG["max_turns"] == 20

def test_config_defaults_on_missing_file(tmp_path):
    warnings = []
    cfg = load_bridge_config(str(tmp_path / "nope.json"), warnings)
    assert cfg == DEFAULT_CONFIG and warnings


def test_config_malformed_falls_back(tmp_path):
    p = tmp_path / "bridge.json"
    p.write_text("{nope")
    warnings = []
    assert load_bridge_config(str(p), warnings) == DEFAULT_CONFIG and warnings


def test_config_bad_field_type_falls_back_per_field(tmp_path):
    p = tmp_path / "bridge.json"
    p.write_text('{"timeout_seconds": "soon", "max_turns": 2, "model": 5}')
    warnings = []
    cfg = load_bridge_config(str(p), warnings)
    assert cfg["timeout_seconds"] == DEFAULT_CONFIG["timeout_seconds"]
    assert cfg["max_turns"] == 2
    assert cfg["model"] == ""
    assert any("timeout_seconds" in w for w in warnings)


# --- version gate ---

@pytest.mark.parametrize("output,ok", [
    ("2.1.287 (Claude Code)", True), ("3.0.0", True), ("2.2.0 (Claude Code)", True),
    ("2.1.286 (Claude Code)", False), ("1.9.999", False), ("", False), ("garbage", False),
])
def test_cli_supports_confinement(output, ok):
    assert cli_supports_confinement(output) is ok


def test_old_cli_is_unavailable_never_unconfined():
    # sys.executable is on disk, so which() passes and the version gate decides.
    cfg = {**DEFAULT_CONFIG, "claude_command": sys.executable}
    result = invoke(_request(), cfg, version_probe=lambda _cmd: "2.0.0 (Claude Code)")
    assert result["status"] == "unavailable"
    assert "too old" in result["error"]


def test_invoke_unavailable_when_command_missing():
    cfg = {**DEFAULT_CONFIG, "claude_command": "claude-not-on-path-xyz"}
    result = invoke(_request(), cfg)
    assert result["status"] == "unavailable"
    assert "claude-not-on-path-xyz" in result["error"]


# --- verdict parsing ---

def test_parse_verdict_structured_output():
    fields, error = parse_verdict(json.loads(_payload("fail", "bad", "body")))
    assert error == ""
    assert fields == {"verdict": "fail", "reason": "bad", "report": "body"}


def test_parse_verdict_falls_back_to_result_string():
    data = {"verdict": "pass", "reason": "r", "report": "x"}
    fields, error = parse_verdict({"result": json.dumps(data)})
    assert error == "" and fields["verdict"] == "pass"


def test_parse_verdict_invalid_verdict_keeps_report():
    fields, error = parse_verdict({"structured_output":
                                   {"verdict": "maybe", "reason": "", "report": "r"}})
    assert fields["verdict"] is None and fields["report"] == "r"
    assert "invalid verdict" in error


def test_parse_verdict_plain_text_is_report_without_verdict():
    fields, error = parse_verdict({"result": "just prose"})
    assert fields == {"verdict": None, "reason": "", "report": "just prose"}
    assert error


def test_parse_verdict_nothing_usable():
    assert parse_verdict(None)[0] is None
    assert parse_verdict({"result": None})[0] is None


# --- invoke (injectable runner) ---

def test_invoke_ok_returns_verdict_and_sends_prompt_on_stdin():
    calls = []
    result = invoke(_request(), DEFAULT_CONFIG, _fake_runner(calls))
    assert result["schema_version"] == RESULT_SCHEMA_VERSION
    assert result["status"] == "ok"
    assert (result["verdict"], result["reason"]) == ("pass", "all good")
    assert result["report"].startswith("# Report")
    assert "Summarize the change." in calls[0]["stdin"]
    assert "Summarize the change." not in calls[0]["argv"]


def test_invoke_options_override_turns_and_timeout():
    calls = []
    invoke(_request(options={"max_turns": 9, "timeout_seconds": 7}),
           DEFAULT_CONFIG, _fake_runner(calls))
    argv = calls[0]["argv"]
    assert argv[argv.index("--max-turns") + 1] == "9"
    assert calls[0]["timeout"] == 7


def test_invoke_missing_verdict_is_error_with_report_kept():
    stdout = json.dumps({"subtype": "success", "is_error": False, "result": "prose"})
    result = invoke(_request(), DEFAULT_CONFIG, _fake_runner([], stdout=stdout))
    assert result["status"] == "error"
    assert result["verdict"] is None and result["report"] == "prose"


def test_invoke_non_json_stdout_is_error():
    result = invoke(_request(), DEFAULT_CONFIG, _fake_runner([], stdout="not json"))
    assert result["status"] == "error"


def test_invoke_nonzero_exit_is_error():
    result = invoke(_request(), DEFAULT_CONFIG,
                    _fake_runner([], returncode=2, stdout="", stderr="boom"))
    assert result["status"] == "error" and "boom" in result["error"]


def test_invoke_timeout_status():
    def runner(argv, prompt_stdin, timeout, cwd=None):
        raise subprocess.TimeoutExpired(argv, timeout)
    assert invoke(_request(), DEFAULT_CONFIG, runner)["status"] == "timeout"


def test_invoke_runner_crash_is_error():
    def runner(argv, prompt_stdin, timeout, cwd=None):
        raise OSError("exec format error")
    result = invoke(_request(), DEFAULT_CONFIG, runner)
    assert result["status"] == "error" and "exec format" in result["error"]


def test_invoke_runs_claude_in_the_repository_root(tmp_path):
    calls = []
    result = invoke(_request(root=str(tmp_path)), DEFAULT_CONFIG, _fake_runner(calls))
    assert result["status"] == "ok"
    assert calls[0]["cwd"] == str(tmp_path)
    assert str(tmp_path) in calls[0]["stdin"]


def test_invoke_without_root_inherits_the_working_directory():
    calls = []
    invoke(_request(), DEFAULT_CONFIG, _fake_runner(calls))
    assert calls[0]["cwd"] is None


@pytest.mark.parametrize("root", ["", 42, "does/not/exist"])
def test_invoke_bad_request_invalid_root(root):
    calls = []
    result = invoke(_request(root=root), DEFAULT_CONFIG, _fake_runner(calls))
    assert result["status"] == "bad-request" and "root" in result["error"]
    assert calls == []


def test_invoke_bad_request_missing_task():
    result = invoke({"context": CTX}, DEFAULT_CONFIG, _fake_runner([]))
    assert result["status"] == "bad-request" and "task" in result["error"]


def test_invoke_bad_request_missing_context():
    result = invoke({"task": "x"}, DEFAULT_CONFIG, _fake_runner([]))
    assert result["status"] == "bad-request" and "context" in result["error"]


# --- error payloads ---

def test_nonzero_exit_reports_payload_reason_not_empty_stderr():
    stdout = json.dumps({"is_error": True, "subtype": "error_during_execution",
                         "result": "Failed to authenticate: OAuth session expired"})
    result = invoke(_request(), DEFAULT_CONFIG,
                    _fake_runner([], returncode=1, stdout=stdout))
    assert result["status"] == "error" and "OAuth session expired" in result["error"]


def test_nonzero_exit_names_subtype_when_result_is_null():
    stdout = json.dumps({"is_error": True, "subtype": "error_max_turns", "result": None})
    result = invoke(_request(), DEFAULT_CONFIG,
                    _fake_runner([], returncode=1, stdout=stdout))
    assert "error_max_turns" in result["error"]


def test_error_payload_with_zero_exit_is_an_error():
    stdout = json.dumps({"is_error": True, "api_error_status": 429,
                         "result": "requires usage credits."})
    result = invoke(_request(), DEFAULT_CONFIG, _fake_runner([], stdout=stdout))
    assert result["status"] == "error"
    assert "usage credits" in result["error"] and "429" in result["error"]


# --- CLI with a fake claude on PATH (POSIX only) ---

# A name no real install uses: if the fake is ever not found, the bridge
# reports "unavailable" instead of silently invoking the real Claude CLI.
FAKE_CLAUDE_NAME = "claude-fake-for-tests"

FAKE_CLAUDE_OK = """#!/bin/sh
if [ "$1" = "--version" ]; then echo "2.1.287 (Claude Code)"; exit 0; fi
printf '%s\\n' "$@" > "$(dirname "$0")/argv.txt"
cat > "$(dirname "$0")/stdin.txt"
printf '%s' '{"subtype": "success", "is_error": false, "structured_output": {"verdict": "fail", "reason": "fake", "report": "fake report"}}'
"""

# Windows cannot execute the shebang fake, and a .cmd wrapper would go through
# cmd.exe. invoke() is covered on every platform by the injected-runner tests.
needs_posix_fake = pytest.mark.skipif(
    os.name == "nt", reason="fake claude is a shebang script")


def _write_fake_claude(tmp_path, script=FAKE_CLAUDE_OK):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    fake = bin_dir / FAKE_CLAUDE_NAME
    fake.write_text(script)
    fake.chmod(0o755)
    return bin_dir


def _run_cli(tmp_path, stdin_text, path_prefix=None):
    cfg_path = tmp_path / "bridge.json"
    cfg_path.write_text(json.dumps({**DEFAULT_CONFIG,
                                    "claude_command": FAKE_CLAUDE_NAME}))
    env = dict(os.environ)
    if path_prefix is not None:
        env["PATH"] = f"{path_prefix}{os.pathsep}{env['PATH']}"
    return subprocess.run(
        [sys.executable, str(REPO_ROOT / "src" / "claude_bridge.py"),
         "--config", str(cfg_path)],
        input=stdin_text, capture_output=True, text=True, timeout=30, env=env,
    )


@needs_posix_fake
def test_cli_ok_with_fake_claude(tmp_path):
    bin_dir = _write_fake_claude(tmp_path)
    r = _run_cli(tmp_path, json.dumps(_request()), path_prefix=str(bin_dir))
    assert r.returncode == 0
    result = json.loads(r.stdout)
    assert (result["status"], result["verdict"]) == ("ok", "fail")
    argv = (bin_dir / "argv.txt").read_text()
    assert "--restricted" in argv and "Read,Grep,Glob" in argv
    assert "src/a.py" in (bin_dir / "stdin.txt").read_text()


@needs_posix_fake
def test_cli_fake_claude_failure_exit_zero(tmp_path):
    script = FAKE_CLAUDE_OK.split("printf")[0] + "echo nope >&2\nexit 7\n"
    bin_dir = _write_fake_claude(tmp_path, script)
    r = _run_cli(tmp_path, json.dumps(_request()), path_prefix=str(bin_dir))
    assert r.returncode == 0
    result = json.loads(r.stdout)
    assert result["status"] == "error" and "7" in result["error"]


@needs_posix_fake
def test_cli_fake_claude_timeout(tmp_path):
    script = FAKE_CLAUDE_OK.split("printf")[0] + "sleep 10\n"
    bin_dir = _write_fake_claude(tmp_path, script)
    r = _run_cli(tmp_path, json.dumps(_request(options={"timeout_seconds": 1})),
                 path_prefix=str(bin_dir))
    assert json.loads(r.stdout)["status"] == "timeout"


def test_cli_garbage_stdin_bad_request(tmp_path):
    r = _run_cli(tmp_path, "{nope")
    assert r.returncode == 0
    assert json.loads(r.stdout)["status"] == "bad-request"


# --- 012: no console window for the Claude child on Windows --------------------

CREATE_NO_WINDOW = 0x08000000


def test_hidden_window_kwargs_sets_create_no_window_on_windows():
    assert hidden_window_kwargs("nt")["creationflags"] & CREATE_NO_WINDOW


def test_hidden_window_kwargs_is_empty_elsewhere():
    assert hidden_window_kwargs("posix") == {}


@pytest.mark.parametrize("platform,expected", [("nt", True), ("posix", False)])
def test_default_runner_hides_the_window_only_on_windows(monkeypatch, platform, expected):
    seen = {}

    def fake_run(argv, **kwargs):
        seen.update(kwargs)
        return subprocess.CompletedProcess(argv, 0, "out", "err")

    monkeypatch.setattr(subprocess, "run", fake_run)
    code, out, err = _default_runner(["claude"], "prompt", 5, cwd="/repo", platform=platform)
    assert (code, out, err) == (0, "out", "err")
    assert ("creationflags" in seen) is expected
    assert seen["input"] == "prompt" and seen["cwd"] == "/repo" and seen["timeout"] == 5
