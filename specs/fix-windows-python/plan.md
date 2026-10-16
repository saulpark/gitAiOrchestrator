# Fix: Windows support (Python resolution, skill execution, paths, tests)

> **Note (009):** feature 009 made skills declarative (prompt only), so `skill_command` and the shebang handling were removed from `src/execute_skills.py`. The interpreter probe in `scripts/orchestrate.sh`/`install.py` and the UTF-8 handling remain.

**Branch:** `fix-windows-support`
**Date:** 2026-10-02
**Status:** done (uncommitted)

## Problem

On Windows the pipeline never runs, and would fail at three more points once it did:

1. `scripts/orchestrate.sh` calls `python3`, which on Windows is usually the Microsoft
   Store stub (exit 49). The hook fails open, so commits work but nothing ever runs.
2. `install.py` never checks the interpreter the hooks use, so it reports success anyway.
3. `src/execute_skills.py` executes `skills/<name>/run` directly. Windows cannot execute a
   shebang script (`WinError 193`), so every skill would fail with "executor error".
4. `src/parse_context.py` emits `src\foo.py` (via `os.path.normpath`), violating
   `hook-context@1.0`, which uses `/`. `os.path.relpath` also raises `ValueError` for a
   path on another drive, breaking the parser's "always exit 0" promise.
5. The test suite has 18 failures on Windows; 6 are test-only portability issues, and the
   bridge CLI tests silently invoke the **real** `claude` CLI (PATH joined with `:`).

## Approach

Every platform-specific branch is guarded by `os.name == "nt"`; POSIX behavior is unchanged.

- **Interpreter probe (runtime, no stored state):** `orchestrate.sh` tries `python3`,
  `python`, `py -3` and uses the first that runs Python ≥ 3.10. None → stderr message +
  non-zero exit (normal fail-open warning, never a block).
- **Installer:** same probe, same order, as a prerequisite check; aborts with a hint.
  The candidate list exists in two places (sh + py); both carry a cross-reference comment.
- **Skill command:** pure `skill_command(run_path, shebang, ...)`. POSIX → `[run_path]`.
  Windows → read the shebang: python* → `[sys.executable, *args, run_path]`;
  `sh`/`bash` → `[which(name), *args, run_path]`; anything else / no shebang → a clear
  failure detail. `/usr/bin/env X` is unwrapped.
- **Paths:** normalize with `.replace(os.sep, "/")`; cross-drive `ValueError` → dropped as
  outside the repository.
- **Tests:** keep `SYSTEMROOT` in the emptied env; bridge fake renamed
  `claude-fake-for-tests` and PATH joined with `os.pathsep` (real CLI never reachable);
  fake-claude CLI tests skipped on Windows (a `.cmd` fake would mangle the multi-line
  prompt through `cmd.exe`); X_OK test skipped on Windows (no executable bit).

## Out of scope / known limitations

- Windows skills must be Python or sh/bash scripts.
- An npm-installed `claude.cmd` is not supported by the bridge on Windows (same `cmd.exe`
  argument mangling). The native installer's `claude.exe` works.
- No CI workflow (offered separately).

## Tasks

- [x] T1 `scripts/orchestrate.sh`: interpreter probe
- [x] T2 `install.py`: `check_hook_python` prerequisite + `tests/test_install.py`
- [x] T3 `src/execute_skills.py`: `skill_command` + tests (POSIX passthrough, python/sh/env
      shebangs, unsupported interpreter, missing sh)
- [x] T4 `src/parse_context.py`: POSIX separators + cross-drive guard + test
- [x] T5 Test portability: `SYSTEMROOT`, bridge fake name/pathsep/skips, X_OK skip
- [x] T6 `TUTORIAL.md`: short Windows note
- [x] T7 Verify: full suite + ruff on Windows; real `git commit` writes `logs/hooks.log`
