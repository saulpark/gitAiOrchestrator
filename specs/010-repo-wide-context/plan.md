# 010 — Repo-wide read context for skills

**Status:** implemented (uncommitted, on `009-aioutput-skills` per user) · **Date:** 2026-10-02 · **Builds on:** 009

## Goal

Every skill's Claude session may **read the whole repository**. The changed files of the
git event are still listed, as the run's *focus*. What is protected is unchanged: Claude
cannot modify anything (009 read-only confinement), and only the framework writes
`_aioutput/`.

This is a framework capability decided for its own sake (user decision, 2026-10-02), not
a change shaped by one skill. file-counter is just the first skill to use it.

## Decisions (from the user)

| # | Decision |
|---|----------|
| D1 | **Global**: applies to every skill. No per-skill opt-in. |
| D2 | **Everything in the folder**: no tracked-files list, no exclusions. Gitignored files (`.env`, `logs/`, local credentials) are readable. |
| D3 | Default `max_turns` goes from **6 to 20** (`DEFAULT_CONFIG` and `config/bridge.json`). |
| D4 | file-counter switches to counting the **whole repository** (sizes are line counts). |

## Constitution amendment (required: principle 15, "constitution wins")

The current text forbids this, so the amendment is part of 010 and is applied first.

- **Principle 1 (Incremental First)**: add *"Read-only analysis by Claude may consult
  the whole repository; the change set defines what triggered the run and what it
  focuses on. Writes remain limited to framework-owned outputs (`_aioutput/`)."*
- **Principle 3**: replace *"must receive bounded context derived from the detected
  change set and must not operate on the entire repository by default"* with *"must
  receive the detected change set as the focus of each run. It may read the entire
  repository but never modify it."*
- **Principle 8 (Explicit Exclusions)**: this spec overrides it for **reading** (D2).
  Exclusions become each skill's own job; for example, file-counter skips `.git/`.

## Accepted risks (stated, not mitigated, per D2)

1. **Secrets in reports**: Claude can read gitignored secrets, and they may be quoted
   into `_aioutput/` files. `_aioutput/` is gitignored, so they are not committed by
   default, but they are on disk in plain text.
2. *(Corrected by 011: the CLI docs state `--restricted` confines file tools to the
   working directory, so this boundary is enforced by the CLI, not only by the prompt.
   Not verified locally.)* **The boundary is an instruction**: "stay inside the repository folder" is a prompt
   instruction. Claude's Read tool can technically open absolute paths elsewhere on the
   machine. Read-only confinement is the only hard guarantee, and it is unchanged.
3. **Cost and latency**: more turns and more tokens per run. A sync skill is still
   capped by min(budget, sync ceiling), so a commit's worst-case wait is unchanged.

## Changes

### `src/claude_bridge.py`

- Replace `CONSTRAINT` ("Only examine the files listed above. Do not scan…") with
  `SCOPE`: *"The changed files above triggered this run and are its focus. You may
  read any file inside the repository (the current working directory, `<root>`) for
  context. Do not read files outside it."*
- Change the files header from "Changed files (n):" to "Changed files — the focus of
  this run (n):". The empty change-set line stays as it is.
- **Pin the working directory**: the request gets an optional `root`. When present,
  `subprocess.run(..., cwd=root)` and the root appears in `SCOPE`. Today the bridge
  inherits the hook's cwd. That is correct inside hooks but wrong if the router is run
  from a subdirectory, and "the repository" must equal the cwd. A missing or
  non-directory `root` is rejected with `bad-request`.
- `DEFAULT_CONFIG["max_turns"]`: 6 → 20. Update the comment and the docstrings that
  say "bounded / never the full repository".
- `CONFINEMENT_ARGS`, `VERDICT_SCHEMA` and the CLI version gate are **unchanged**.

### `src/execute_skills.py`

- `run_skill` passes `"root": root` in the bridge request. This is the only change.

### `config/bridge.json`

- `"max_turns": 20`.

### Skill `skills/file-counter/` (skill-level, not framework)

- Prompt: enumerate every file in the repository, skipping `.git/`. Group the files by
  extension and give a table of Type / Files / Lines / % of files with a Total row,
  plus the largest 10 files by lines. The changed files of this commit get a short
  separate note. The verdict is always `pass`.
- `time_budget_seconds`: 300. It stays async, so nobody waits. Bump the version to
  1.1.0 and re-register.

## Tests (`tests/test_claude_bridge.py`, `tests/test_execute_skills.py`)

- Happy path: the prompt contains the `SCOPE` sentence with the root and the focus
  header, and **no longer** contains "Do not scan". The runner fake receives
  `cwd == root`.
- Invalid input: a non-directory `root` returns `bad-request` without calling the
  runner.
- Boundary: with no `root`, the bridge behaves as before (no cwd argument).
- Default `max_turns` is 20, and an override in `config/bridge.json` still wins.
- Executor: the bridge request built by `run_skill` carries `root`.
- Confinement regression: the argv still contains every `CONFINEMENT_ARGS` flag.

## Docs

- Constitution: as above.
- `specs/009-aioutput-skills/contracts/skill-contract.md`: change the Can/Cannot table
  to "Can: read any file in the repository". Change `execution-and-output.md`
  (`max_turns` default, scope) and add a "Superseded in part by 010" line to both.
- `specs/007-claude-code-bridge/contracts/bridge-interface.md`: add a superseded
  pointer for the constraint sentence.
- `TUTORIAL.md`: the "what Claude can/can't do" section, the `max_turns` default, and
  the secrets warning (risk 1).
- `CLAUDE.md`: an Active Technologies line and a Recent Changes entry.

## Tasks

- [x] T1 Amend the constitution (principles 1, 3, 8).
- [x] T2 Write failing tests (above).
- [x] T3 Implement the bridge and executor changes, and `config/bridge.json`.
- [x] T4 Pytest + ruff: no new findings over the current 37.
- [x] T5 Update the file-counter prompt and manifest; re-register and validate.
- [x] T6 Docs (above).
- [x] T7 Live E2E (throwaway copy of the repo):
  - a commit triggers file-counter;
  - the report covers the whole repo (file count ≈ `find . -path ./.git -prune -o -type f | wc -l`);
  - running it from a subdirectory still scopes the run to the root;
  - the tree hash outside `_aioutput/`, `logs/` and `__pycache__` is unchanged.
- [x] T8 Check off the tasks. Commit or open a PR **only when the user asks**.

## Outcome (2026-10-02)

- Branch: implemented on `009-aioutput-skills` (user decision), uncommitted.
- Tests: 226 passed, 4 skipped; ruff 37 findings (no new findings).
- Live E2E, async file-counter on a commit made from `src/`:
  - the commit returned in 3 s, silently;
  - the report covered 188 files (189 on disk; the extra is the run record written
    afterwards), with line counts for 166. The 22 gitignored files are skipped by
    Grep and shown as `n/a`;
  - the tree hash outside `_aioutput/`, `logs/` and `__pycache__` was unchanged.
- Cost finding: about 4 minutes and about $0.39 per run (33 turns). Two causes:
  - Glob truncates at 100 results, so Claude enumerates directory by directory;
  - most of the time is spent writing the final report.

  file-counter needed `time_budget_seconds: 600`, plus a single Grep `^` count call
  instead of reading every file. Its first two versions timed out.
