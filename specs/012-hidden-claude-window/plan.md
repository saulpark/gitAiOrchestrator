# 012 — Claude runs without a console window on Windows

**Status:** implemented (uncommitted), awaiting live check T5, on `012-hidden-claude-window` (branched from `009-aioutput-skills`)
· **Date:** 2026-10-30 · **Touches:** 007 (`src/claude_bridge.py`) · **Kind:** bug fix, no
contract change

## Problem

Async skills run in a detached worker that has no console (`DETACHED_PROCESS |
CREATE_NO_WINDOW`, `execute_skills.detach_kwargs`). The worker then starts `claude` with
`subprocess.run`, with no window flag. On Windows, a console program started by a process
that has no console gets a **new visible console window**. Observed 2026-10-30: a console
window stays open while a skill runs, and closing it cancels the skill. The earlier
`claude exited 129` failure (2026-10-16) fits the same cause.

This is the inferred mechanism. It is consistent with the code and with what the user
sees, but it has not been reproduced in isolation. Task T5 checks it on the real machine.

## Decision (from the user)

Option 1: hide the window. No visible console, so nothing can be closed by accident.
Progress output on a console, or a toast notification, is out of scope. Results stay in
`_aioutput/` and `logs/hooks.log`.

## Design

- New pure helper `hidden_window_kwargs(platform=os.name)` in `src/claude_bridge.py`:
  returns `{"creationflags": CREATE_NO_WINDOW}` (0x08000000, via `getattr` with the
  numeric fallback, like `detach_kwargs`) when `platform == "nt"`, else `{}`.
- Both `subprocess.run` calls in the bridge use it: the Claude call in `_default_runner`
  and the `--version` probe in `_cli_version`. `_default_runner` gets a `platform`
  keyword (default `os.name`) so it is testable without patching `os.name`.
- Not changed: `detach_kwargs` (already correct), `install.py`'s probe (it runs in the
  user's own terminal, which exists), the hook scripts.
- The sync path runs inside git's console; `CREATE_NO_WINDOW` there only means the child
  gets no console of its own. Output is captured through pipes either way.

## Tests (`tests/test_claude_bridge.py`)

- Happy path: `hidden_window_kwargs("nt")` has the `CREATE_NO_WINDOW` bit set.
- Other platform: `hidden_window_kwargs("posix")` is `{}`.
- `_default_runner(..., platform="nt")` passes `creationflags` with that bit to
  `subprocess.run`; with `platform="posix"` it passes no `creationflags`. Existing
  arguments (`input`, `cwd`, `timeout`, `capture_output`) are unchanged.

## Docs

- TUTORIAL §6, 007 entry: one sentence. `CLAUDE.md`: Recent Changes line.

## Tasks

- [x] T1 Failing tests.
- [x] T2 Implement `hidden_window_kwargs` and use it in both `subprocess.run` calls.
- [x] T3 Full pytest + ruff: no new findings in changed files.
- [x] T4 Docs.
- [ ] T5 Live check on the user's machine: run a skill and confirm no console window
  appears and the run still completes with `status=success`.
- [ ] T6 Report. Commit only when the user asks.

## Outcome (2026-10-30)

- Tests: 257 passed, 4 skipped (4 new in `tests/test_claude_bridge.py`).
- Ruff: no new findings in the two changed files (6 and 2, as before). The repo total
  stays at 45 from the ruff 0.17.1 upgrade (see fix-windows-timeout).
- Not verified: the live behavior. T5 needs a real async run on the user's machine to
  confirm that no console window appears.
