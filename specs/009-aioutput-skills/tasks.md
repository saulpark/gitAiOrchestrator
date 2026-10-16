# Tasks: Declarative AI Skills with Sandboxed `_aioutput/` Results

**Goal:**

- Skills are prompts.
- Claude runs read-only.
- The framework writes results to `_aioutput/<skill>/`.
- Per-skill sync or async; only a sync `fail` verdict blocks.
- The terminal stays silent otherwise.

**Tech Stack:** Python 3.10+ stdlib, POSIX sh, pytest, ruff. Claude CLI ≥ 2.1.287.

## Global Constraints

- No confinement flag may be configurable away (FR-003–FR-005). An old CLI → `unavailable`,
  never an unconfined call.
- Only sync + `failure` (verdict fail) + `on_failure: block` + pre-commit/pre-push → exit 10.
- Nothing printed during a git operation except `[hook blocked]` lines.
- Every run leaves a run record, and every async job leaves its own.
- Pure functions for path/header/argv/verdict/outcome logic; I/O only in named edge
  functions.
- Tests per feature: happy path, invalid input, error cases (timeout, missing CLI,
  unwritable dir).

---

## Task 0: Spike — verify the CLI assumptions (no production code)

Use throwaway scripts in a temp dir, deleted afterwards. Record the findings in
research.md (R1–R3 "to verify").

- [x] (a) The tools available under
      `--restricted --tools Read,Grep,Glob --strict-mcp-config` are exactly
      Read/Grep/Glob.
- [x] (b) Adversarial prompt: edit README, create a file, run `git commit`. Nothing
      changes (hash every tracked file and `git status` before/after).
- [x] (c) Field name of the `--json-schema` result in the `--output-format json` payload.
- [x] (d) Whether CLAUDE.md is loaded under `--restricted`.
- [x] (e) Windows: the schema argv survives `claude.exe` quoting.
- [x] (f) A detached Python child started from inside `_run_with_timeout` outlives the
      hook, on Git Bash/Windows (and POSIX if available).
- [x] **Gate:** if (a) or (b) fails, stop and return to the user. The design is invalid.

## Task 1: Skill contract v2.0 + registry

**Files:** `src/skill_registry.py`, `tests/test_skill_registry.py`, `.gitignore`

**Interfaces:** `CONTRACT_VERSION = "2.0"`; `validate_manifest` adds the `prompt` and
`executable-code` rules and drops `output`/`behaviors`/`entry-point`.

- [x] **Failing tests:**
  - compliant v2 skill → no violations;
  - missing/empty `prompt.md` → `prompt`;
  - a `run` file, a `x.py`, or (POSIX) an exec-bit file → `executable-code`;
  - all violations in one pass;
  - `time_budget_seconds` 0 / 601 / "x" → `time-budget`;
  - `test_contract_version_is_two_zero`;
  - registry ops unchanged otherwise.
- [x] **Implement**; add `_aioutput/` to `.gitignore`.
- [x] **Verify** pytest + ruff (no new findings over the master baseline).

## Task 2: Bridge v2.0 — read-only invocation + verdict

**Files:** `src/claude_bridge.py`, `config/bridge.json`, `tests/test_claude_bridge.py`

**Interfaces:**

- `VERDICT_SCHEMA`
- `build_argv(prompt, config) -> list[str]` (pure)
- `parse_verdict(payload) -> (verdict|None, reason, report, error)` (pure)
- `invoke(request, config, runner=None) -> bridge-result@2.0`
- `cli_supports_confinement(version_str) -> bool` (pure)

Tasks:

- [x] **Failing tests:**
  - argv always contains every confinement flag, in any config;
  - `hooks_enabled`/`extra_args` in the config → ignored with a warning, never in argv;
  - `model` set → `--model` appended;
  - valid structured output → `ok` + verdict;
  - report without verdict / verdict not in the enum / non-JSON stdout → `error`;
  - CLI missing → `unavailable`;
  - CLI version < 2.1.287 or unparseable → `unavailable` ("too old for confinement");
  - timeout → `timeout`;
  - `is_error` payload → `error` (kept from 007).
- [x] **Implement** (the version probe `claude --version` is cached per process); bump
      `config/bridge.json` to 2.0.
- [x] **Delete** the obsolete 007 tests/fakes for the removed keys; keep the POSIX-fake CLI
      tests, adapted.

## Task 3: Result writer

**Files:** create `src/ai_output.py`, `tests/test_ai_output.py`

**Interfaces:**

- `result_path(root, skill, event, now, exists) -> str` (pure)
- `render_result(meta, report) -> str` (pure)
- `write_result(root, skill, meta, report) -> str` (I/O, atomic)
- `prune_plan(names, keep) -> list[str]` (pure)
- `prune(root, skill, keep)`

Tasks:

- [x] **Failing tests:**
  - path format `_aioutput/<skill>/<YYYYMMDDTHHMMSSZ>-<event>.md`;
  - collision → `-2`, `-3`;
  - the header contains every FR-008 field, with values escaped (quotes/newlines in the
    reason);
  - `verdict: invalid` rendering;
  - the write is atomic (no `.tmp` left behind, target never partially written);
  - `_aioutput` is a file / an unwritable dir → raises `OSError` for the caller to classify;
  - retention keeps the newest N, ignores non-matching files, keep < 1 → treated as the
    default;
  - a skill name containing `..`/`/` → `ValueError` (defense in depth; names are already
    regex-checked).
- [x] **Implement.**

## Task 4: Executor v2 — sync path

**Files:** `src/execute_skills.py`, `tests/test_execute_skills.py`

**Interfaces:**
`execute_plan(plan, context, skills_dir, modes, sync_ceiling, root, bridge=invoke, clock=time.monotonic)`
→ execution-summary@2.0, plus the list of async skills to dispatch.

- [x] **Remove** `skill_command`, `_read_shebang`, the `run` subprocess path and their
      tests (superseded Windows code).
- [x] **Failing tests** (fake bridge):
  - pass → `success` + file written;
  - fail → `failure` + file written;
  - bridge error/unavailable → `error`, with no file unless a report exists;
  - an unregistered/invalid skill → `skipped`;
  - per-skill timeout = min(budget, remaining ceiling);
  - ceiling exhausted → later skills `timeout` without calling the bridge;
  - write failure → `error` with the reason;
  - async skills are not executed here but returned for dispatch;
  - the prompt sent contains `prompt.md` + context + constraint.
- [x] **Implement.**

## Task 5: Async dispatch + worker

**Files:** `src/execute_skills.py` (`dispatch_async`), create `src/async_worker.py`,
`tests/test_async_worker.py`

- [x] **Failing tests:**
  - `dispatch_async` writes `logs/async/<run-id>.json` and calls the injected `spawn` with
    `[sys.executable, async_worker.py, job]` and the platform's detach kwargs (asserted for
    both `posix` and `nt`);
  - spawn raises → `dispatch-failed`;
  - worker on a valid job runs each skill via the fake bridge, writes files, writes a
    `<parent>-async.json` record with `parent_run`, appends one log line per skill, and
    deletes the job file;
  - corrupt/missing job → a record with the error, exit 0;
  - a real-process test: the dispatcher returns in < 200 ms while the worker sleeps.
- [x] **Implement.**

## Task 6: Outcomes + run record 1.1

**Files:** `src/run_records.py`, `tests/test_run_records.py`

- [x] **Failing tests:**
  - block applies only to `failure`;
  - `error`/`timeout` with a block rule → warn + reason;
  - `skipped` with block → downgraded + reason;
  - async + block → none, with a config note;
  - the post-merge downgrade is kept;
  - the record carries `mode`, `verdict`, `output_file`, `async_job`;
  - `show` renders them.
- [x] **Implement**; version 1.1.

## Task 7: Router + hooks

**Files:** `src/route_workflows.py`, `config/routes.json`, `scripts/lib.sh`,
`scripts/orchestrate.sh`, `tests/test_route_workflows.py`

- [x] **Failing tests:**
  - routes v2.0 parsing:
    - `skills.<n>.mode` defaults to async, invalid → warning;
    - `sync_ceiling_seconds` bounds 1–600;
    - `output_retention`;
    - a legacy `outcomes` fallback + deprecation note;
  - CLI with a sync block skill + fake bridge returning fail → exit 10, the only stderr
    line `[hook blocked] skill 'x': <reason> (see _aioutput/x/…)`;
  - warn/error → exit 0 and **empty stderr**, with the warning in `logs/hooks.log`;
  - DispatchResult 2.0.
- [x] **Implement**:
  - `HOOK_CEILING_SECONDS=610` in lib.sh, used by `_run_with_timeout`;
  - `_finish_hook` writes non-block warnings to `logs/hooks.log` instead of stderr;
  - the orchestrate.sh no-python warning → `logs/hooks.log`;
  - check `sh -n`, keep hooks ≤ 30 lines.

## Task 8: Docs + contract pointers

- [x] TUTORIAL.md:
  - write a skill as a prompt;
  - choose a mode;
  - where results go;
  - what Claude cannot do;
  - update the Windows section (no shebang notes).
- [x] The 002/005/006/007/008 contracts each get a one-line "Superseded in part by 009"
      pointer.
- [x] Roadmap docs (notice added at planning time, 2026-10-02):
  - numbering shift 009–012 → 010–013;
  - incompatibility notice (Python skill, doc-editing agents).
- [x] CLAUDE.md Active Technologies / Recent Changes; `.specify/feature.json` → 009.

## Task 9: Live E2E + finish

- [x] An async skill on pre-commit:
  - the commit returns immediately and silently;
  - the file appears;
  - `show --last` and the async record are present.
- [x] A sync block skill:
  - a `TODO-BLOCK` commit aborts with one line;
  - a clean commit is silent;
  - with `claude` removed from PATH, the commit proceeds and the error is recorded.
- [x] SC-001 adversarial skill on a real commit: hash every file outside `_aioutput/`
      before/after → identical.
- [x] Run on Windows (this machine); POSIX via CI or a Linux box if available. If not,
      state that it was not run.
      → Windows (Git Bash, Python 3.14, claude 2.1.287) run 2026-10-02. POSIX NOT run:
        no Linux box or CI available in this session.
- [x] Full suite + ruff; check off tasks; commit/PR **only when the user asks**.
