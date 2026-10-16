# fix-windows-timeout — Hooks must not mistake Windows `timeout.exe` for GNU timeout

**Status:** implemented (uncommitted) on `009-aioutput-skills` (user decision, 2026-10-16) ·
**Touches:** 002 (`scripts/lib.sh`) · **Kind:** bug fix, no contract change

## Problem

`_run_with_timeout` in `scripts/lib.sh` uses the first `timeout` on PATH, assuming it is
GNU `timeout`. On Windows, `C:\Windows\System32\timeout.exe` also exists, and it is a
different program (a "wait N seconds" command). When it comes first on PATH, the call
`timeout 610 <script>` fails at once with `ERROR: Invalid syntax` and exit 1. Verified on
2026-10-16 from Git Bash.

Effect: the whole pipeline is skipped. The hook logs `orchestration failed (exit 1)`,
git proceeds, and no skill runs. Seen on a commit made from GitHub Desktop (whose
bundled Git resolves `timeout` differently from Git Bash and PowerShell). The mechanism
is verified. That GitHub Desktop was the cause is probable, not proven.

## Decision (from the user)

Fix it in `lib.sh` with a small, deliberate change to 002. No contract change: the
documented behavior ("bounded by `HOOK_CEILING_SECONDS`, never blocks") is unchanged.

## Design

- New helper `_gnu_timeout`: for each of `timeout`, `gtimeout` that exists on PATH, run
  `<cmd> --version` (stdin from `/dev/null`, stderr discarded) and accept it only if the
  output contains `GNU`. Print the accepted command name; return 1 if none qualifies.
- `_run_with_timeout` uses the helper's result. If none qualifies it falls through to the
  existing POSIX watchdog, which needs no external command. No other behavior changes.
- Cost: one extra `--version` process per hook run (milliseconds).

## Tests (`tests/test_hook_timeout.py`)

Run `sh` with a fake command directory first on PATH. Skip if no `sh`.

- Happy path: a fake `timeout` that reports `GNU` for `--version` and records its
  arguments is used, with the ceiling as its first argument.
- Bad `timeout` (the Windows case): a fake that prints an error and exits 1 for every
  call is not used. The command still runs and its own exit code (3) comes back.
- No `timeout` at all: the watchdog path runs the command and returns its exit code.
- Boundary: the command's output reaches the caller in the fallback path.

## Docs

- Comment in `lib.sh` (why `--version` is checked).
- TUTORIAL §6, 002 entry: one sentence. CLAUDE.md: Recent Changes line.

## Tasks

- [x] T1 Failing tests.
- [x] T2 Implement `_gnu_timeout` and use it in `_run_with_timeout`.
- [x] T3 Pytest + ruff: no new findings over 37.
- [x] T4 Docs (above).
- [x] T5 Live check: `timeout.exe` forced first on PATH in the hook still runs the pipeline.
- [x] T6 Report. Commit only when the user asks.

## Outcome (2026-10-16)

- Tests: 253 passed, 4 skipped (4 new in `tests/test_hook_timeout.py`; the new file has no
  ruff findings).
- Ruff: 45 findings, up from 37. None are in the changed files. The cause is ruff
  0.17.1 (the earlier baseline ran on 0.16.10) applying newer rules to untouched code.
- Live check: with a fake `timeout` that exits 1 placed first on PATH, the real
  `_run_with_timeout` + `orchestrate.sh` still ran the pipeline (`route event=post-merge`
  logged, wrapper exit 0).
- Not verified: an actual commit from GitHub Desktop.
