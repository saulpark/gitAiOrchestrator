"""scripts/lib.sh — _run_with_timeout must only trust a GNU `timeout`.

On Windows, System32\\timeout.exe is a different program; using it makes every
hook fail with exit 1 and silently skips the pipeline (fix-windows-timeout).
"""
import os
import shutil
import stat
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
LIB = ROOT / "scripts" / "lib.sh"

pytestmark = pytest.mark.skipif(shutil.which("sh") is None, reason="needs a POSIX sh")


def _script(path: Path, body: str) -> Path:
    path.write_text("#!/bin/sh\n" + body, newline="\n")
    path.chmod(path.stat().st_mode | stat.S_IEXEC)
    return path


def _fake_timeout(bin_dir: Path, name: str, body: str) -> None:
    _script(bin_dir / name, body)


GNU_LIKE = """\
if [ "$1" = "--version" ]; then echo "timeout (GNU coreutils) 9.4"; exit 0; fi
echo "$@" > "$FAKE_LOG"
shift
exec "$@"
"""

WINDOWS_LIKE = """\
echo "ERROR: Invalid syntax." >&2
exit 1
"""


def _run(tmp_path: Path, command_body: str, bin_dir: Path | None = None):
    """Source lib.sh, run a command through _run_with_timeout, return the result."""
    cmd = _script(tmp_path / "cmd.sh", command_body)
    env = dict(os.environ, FAKE_LOG=str(tmp_path / "fake.log"))
    if bin_dir is not None:
        env["PATH"] = str(bin_dir) + os.pathsep + env["PATH"]
    shell = f'. "{LIB.as_posix()}"; HOOK_CEILING_SECONDS=7; _run_with_timeout "{cmd.as_posix()}"'
    return subprocess.run(["sh", "-c", shell], env=env, capture_output=True,
                          text=True, timeout=60, check=False)


def test_gnu_timeout_is_used_with_the_ceiling(tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _fake_timeout(bin_dir, "timeout", GNU_LIKE)
    result = _run(tmp_path, "echo ran; exit 0\n", bin_dir)
    assert result.returncode == 0 and "ran" in result.stdout
    assert (tmp_path / "fake.log").read_text().split()[0] == "7"


def test_non_gnu_timeout_is_not_used(tmp_path):
    # The Windows case: a `timeout` that rejects the call with exit 1.
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _fake_timeout(bin_dir, "timeout", WINDOWS_LIKE)
    result = _run(tmp_path, "echo ran; exit 3\n", bin_dir)
    assert result.returncode == 3          # the command's own code, not the fake's 1
    assert "ran" in result.stdout
    assert "Invalid syntax" not in result.stderr


def test_non_gnu_timeout_does_not_hide_a_gnu_gtimeout(tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _fake_timeout(bin_dir, "timeout", WINDOWS_LIKE)
    _fake_timeout(bin_dir, "gtimeout", GNU_LIKE)
    result = _run(tmp_path, "echo ran; exit 0\n", bin_dir)
    assert result.returncode == 0
    assert (tmp_path / "fake.log").exists()    # gtimeout, not the watchdog, ran it


def test_command_exit_code_and_output_survive_the_fallback(tmp_path):
    # No usable timeout at all -> the POSIX watchdog path.
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _fake_timeout(bin_dir, "timeout", WINDOWS_LIKE)
    result = _run(tmp_path, "echo out; echo err >&2; exit 10\n", bin_dir)
    assert result.returncode == 10
    assert "out" in result.stdout and "err" in result.stderr
