# Implementation Plan: Declarative AI Skills with Sandboxed `_aioutput/` Results

**Branch**: `009-aioutput-skills` | **Date**: 2026-10-02 | **Spec**: [spec.md](./spec.md)

## Summary

Skills become declarative: `skill.json` + `prompt.md`, contract v2.0, with no executable
code. For each routed skill the framework calls Claude through the bridge in a
**read-only** session:

- `--restricted`
- `--tools Read,Grep,Glob`
- no MCP
- no hooks
- the settings files are ignored

Claude returns `{verdict, reason, report}` as structured output. The **framework**, not
Claude, writes the report to `_aioutput/<skill>/<timestamp>-<event>.md`.

Each skill's mode is set in `routes.json`:

- **async** (default) skills run in one detached worker process per run and never block or
  delay git.
- **sync** skills run before git proceeds, bounded by their budgets and a sync ceiling. A
  `fail` verdict with `on_failure: block` aborts pre-commit/pre-push.

The terminal shows nothing except block messages. Run records and `logs/hooks.log` keep
every run diagnosable.

> **Starting state**: this branch carries the uncommitted Windows-support changes from
> `fix-windows-support` (see `specs/fix-windows-python/plan.md`). Task 2 deletes the
> `skill_command` part of that fix, which no executables means is dead code. The rest
> stays: the `orchestrate.sh` probe, the installer check and the `parse_context` paths.

## Technical Context

- **Language**: Python 3.10+ stdlib; POSIX sh for the hooks.
- **New modules**:
  - `src/ai_output.py`: result-file writer + retention, all pure except `write_result`.
  - `src/async_worker.py`: the detached entry point.
- **External**: Claude Code CLI ≥ 2.1.287, for `--restricted`, `--tools`, `--json-schema`
  and `--permission-prompts`.
- **Storage**:
  - `_aioutput/` (gitignored, new);
  - `logs/async/` job files (gitignored via `logs/`);
  - `logs/runs/`.
- **Testing**: pytest with an injected bridge runner. There are no real Claude calls in the
  unit tests; real calls happen only in the T0 spike and the T9 E2E.
- **Constraints**:
  - async dispatch < 200 ms;
  - sync bounded by `sync_ceiling_seconds`;
  - only a sync `fail` verdict blocks.

## Constitution Check

| Principle | Assessment | Notes |
|-----------|------------|-------|
| 1 · Incremental First | ✅ | the context is still the change set; the prompt constraint is kept |
| 3 · Claude Is The Engine | ✅ | Claude analyzes and *proposes* (reports); it no longer applies edits |
| 4 · Spec Before Automation | ✅ | trigger, input, target (`_aioutput/` only), exclusions, success and failure handling are in spec.md |
| 5 · Deterministic & Reviewable | ✅ | Claude's output is non-deterministic, as in 007; every output is a plain, reviewable file with provenance in its header |
| 6 · Safe By Default | ✅ strengthened | read-only Claude; default async; infrastructure errors never block |
| 8 · Explicit Exclusions | ✅ | `_aioutput/` is gitignored, so it is never in the context |
| 10 · Human Oversight | ✅ strengthened | nothing is applied automatically; a human reads the reports and acts |
| 11 · Small Composable Scripts | ✅ | the writer, the worker and the bridge are separate modules with JSON I/O |
| 12 · Structured I/O | ✅ | JSON-schema'd verdict; every schema is versioned |
| 13 · Idempotent | ⚠️ deviation | one file per run — see Complexity Tracking |
| 14 · Observable | ✅ | run record per run and per async job; log line per skill; missing-file causes recorded |

**Gate: PASS with one justified deviation.**

## Project Structure

```text
specs/009-aioutput-skills/
├── spec.md  plan.md  research.md  data-model.md  quickstart.md  tasks.md
├── checklists/requirements.md
└── contracts/skill-contract.md  contracts/execution-and-output.md
```

New:

```text
src/ai_output.py            result path, header render, atomic write, retention
src/async_worker.py         reads a job file, runs async skills, writes files + record
tests/test_ai_output.py
tests/test_async_worker.py
```

Modified:

```text
src/skill_registry.py       contract v2.0: prompt.md required, executable-code violation
src/claude_bridge.py        v2.0: confinement argv, json-schema verdict, allowlisted config
src/execute_skills.py       no subprocess skills; sync via bridge + deadline; async dispatch
src/run_records.py          block only on 'failure'; error status; run-record 1.1 fields
src/route_workflows.py      routes v2.0 (skills.<name>.mode/on_failure, ceilings);
                            terminal silence except block; DispatchResult 2.0
scripts/lib.sh              HOOK_CEILING_SECONDS=610; _finish_hook logs instead of printing warnings
scripts/orchestrate.sh      the no-python warning goes to hooks.log
config/routes.json          v2.0
config/bridge.json          v2.0
.gitignore                  _aioutput/
tests/test_*.py             matching updates (bridge, executor, registry, records, router)
TUTORIAL.md                 rewrite of the skill-authoring section
docs/living-documentation-roadmap.md      renumbering + incompatibility notice
docs/architecture-documentation-plan.md   renumbering + incompatibility notice
specs/00{2,5,6,7,8}-*/      a one-line "superseded in part by 009" pointer in each contract
CLAUDE.md                   Active Technologies / Recent Changes
```

## Key Design Decisions

See [research.md](./research.md).

1. **Confinement by tool allowlist, not by permission rules** (R1). Claude has no write
   tool at all.
2. **Structured verdict via `--json-schema`** (R2). If it is missing or invalid, the status
   is `error`, which never blocks.
3. **One detached worker per run**, fed by a job file (R3). There is no lock, because
   nothing shared is ever written (R4).
4. **Sync ceiling enforced in Python, with a 610 s shell backstop** (R5).
5. **Blocking means "Claude judged the change bad", never "infrastructure failed"** (R6).
6. **Terminal shows block lines only** (R7).
7. **Pure core, I/O at the edges**:
   - `render_result`, `result_path`, `prune_plan`, `build_argv`, `parse_verdict`,
     `evaluate_outcomes` are pure;
   - `write_result`, `dispatch_async`, `invoke` are the explicit side-effect points.

## Risks

| Risk | Mitigation |
|------|------------|
| A CLI flag behaves differently from `--help` | T0 spike before coding; SC-001 adversarial E2E |
| Older Claude CLI without `--restricted` | bridge detects the CLI version once per run; below 2.1.287 → status `unavailable` with "claude CLI too old for confinement". **Never** fall back to an unconfined call |
| Detached worker killed with the hook on Git Bash | verified in T0; fallback: worker double-forks (POSIX) / `start` via `cmd /c start /b` (Windows) |
| Sync skills make commits slow | default mode async; the ceiling is configurable; the delay is an explicit operator opt-in |
| Roadmap features 010–013 conflict with read-only Claude | flagged in both roadmap docs; must be re-scoped before they are specified |

## Complexity Tracking

| Deviation | Why needed | Simpler alternative rejected because |
|-----------|-----------|--------------------------------------|
| Principle 13: a new file per run instead of an idempotent overwrite | the user asked for a result history (2026-10-02) | overwrite loses earlier results; mitigated by gitignore (never in commits) and retention (bounded on disk) |
| 008 FR-007 "visible warn" relaxed to log-only | the user asked for skills to "not report anything back" | printing warnings contradicts the request; principle 14 is met by the log + records |
