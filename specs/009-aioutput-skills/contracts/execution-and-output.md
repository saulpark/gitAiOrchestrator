# Contract: Execution Modes, Claude Invocation, `_aioutput/` Results

> **Superseded in part by 010** — Claude may read the whole repository (the change set is the run's focus, not its limit), runs with its working directory pinned to the repo root, and `max_turns` defaults to 20. See `specs/010-repo-wide-context/plan.md`.

**Branch**: `009-aioutput-skills` | **Date**: 2026-10-02
**Schema versions**:

- routes config `2.0`
- bridge config / bridge-result `2.0`
- run-record `1.1`
- DispatchResult `2.0`

## Claude invocation (bridge v2.0, non-negotiable argv)

```text
claude -p <prompt> --output-format json --max-turns <N>
       --restricted --tools Read,Grep,Glob --strict-mcp-config
       --permission-prompts none
       --settings {"disableAllHooks": true}
       --json-schema <verdict schema>
       [--model <model>]
```

The working directory is the repo root. No configuration key may add, remove or reorder
the confinement flags. `config/bridge.json` accepts only `claude_command`, `model`,
`max_turns` and `timeout_seconds`.

## Pipeline per git event

```text
hook → orchestrate.sh → parse_context → route_workflows
   ├─ sync skills (in order, each ≤ min(budget, remaining sync ceiling))
   │    bridge → verdict → write _aioutput file → outcome
   ├─ async skills → logs/async/<run-id>.json → detached async_worker.py
   │    worker: bridge → write _aioutput file → own run record + log line
   └─ run record (logs/runs/<id>.json) → exit 0, or 10 if a sync block matched
```

## Result file location

`<repo root>/_aioutput/<skill>/<YYYYMMDDTHHMMSSZ>-<event>[-N].md`. Format: see
data-model.md.

- Written only by the framework, atomically. Never overwritten.
- Retention: `output_retention` (default 50) files per skill. The oldest are pruned after
  each write.
- `_aioutput/` is in `.gitignore`.
- If writing fails, the status becomes `error` and the git operation is unaffected.

## Outcome matrix

| Mode | Status | `on_failure` | pre-commit / pre-push | post-merge |
|------|--------|--------------|-----------------------|------------|
| sync | success | any | proceed, silent | silent |
| sync | failure (verdict fail) | block | **abort**, `[hook blocked] skill 'x': <reason> (see _aioutput/x/…)` | downgraded → warn (logged) |
| sync | failure | warn / skip | proceed, logged only | logged only |
| sync | error / timeout | any | proceed, logged only | logged only |
| any | skipped | block → downgraded | proceed, logged only | logged only |
| async | any | any (block ignored + config warning) | proceed, silent | silent |

"Logged only" means `logs/hooks.log` + run record. Nothing is printed to the terminal.

## Hook exit-code protocol (002 addendum, amended)

| Orchestration exit | Hook behavior |
|--------------------|---------------|
| `0` | proceed |
| `10` | abort the git operation (only from the sync-block row above) |
| anything else, incl. the 610 s backstop kill | proceed; one line in `logs/hooks.log`, nothing on the terminal |

The hard backstop is `HOOK_CEILING_SECONDS=610` in `scripts/lib.sh`. The effective bound is
`sync_ceiling_seconds` (default 120), enforced by the router.
