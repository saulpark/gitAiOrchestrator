# Contract: Routing Configuration & Router CLI

**Branch**: `004-workflow-router` | **Date**: 2026-07-14
**Schema versions**: config `1.0`, DispatchResult `1.0`

---

## Routing Configuration: `config/routes.json`

The sole source of routing truth (FR-001). Versioned in the repository. Edited directly by
developers; takes effect on the next git operation — the router re-reads it every
invocation (FR-007), no reinstall.

```json
{
  "version": "1.0",
  "routes": {
    "pre-commit": ["doc-sync", "changelog"],
    "post-merge": [],
    "pre-push": []
  }
}
```

- Event keys: `pre-commit`, `post-merge`, `pre-push` (others ignored with warning)
- Values: ordered lists of workflow identifiers; execution is sequential in list order
- Missing file / malformed JSON → treated as empty config, `[router warning]` emitted,
  git operation unaffected (FR-008)

> **Schema v1.1 (2026-07-19, feature 008)**: optional top-level `outcomes`
> (skill → `{"on_failure": "block"|"warn"|"skip"}`) and `run_retention` (int, default 50).
> See [008 run-record contract](../../008-run-observability/contracts/run-record.md).

## Router CLI

```sh
python3 src/parse_context.py | python3 src/route_workflows.py \
    --config config/routes.json --log logs/hooks.log [--skills-dir skills]
```

- stdin: context JSON (003 schema v1.0)
- stdout: DispatchResult JSON (single line)
- stderr: `[router warning] …` lines — surface through hooks to the developer (SC-003)
- exit code: **always 0** (SC-004)
- `--config` default `config/routes.json`; `--log` optional; `--skills-dir` default `skills`

## Outcome semantics

| Outcome | Meaning | Warning? |
|---------|---------|----------|
| `invoked` | workflow ran, exit 0 | no |
| `failed` | workflow ran, non-zero exit / invoker exception | yes |
| `unresolvable` | identifier could not be resolved to an executable unit | yes |
| *(no results)* | event unconfigured/empty route → logged skip (FR-006); unroutable context → warning | see left |

## Invocation Interface (superseded — see 005/006)

> **v1.1 addendum (2026-07-18, feature 006)**: resolution goes through the 005 registry
> and execution through the 006 executor. DispatchResult is now **v1.1**: adds top-level
> `overall` and embedded `execution` (ExecutionSummary), per-result `status` and
> `duration_ms`. See
> [006 execution-summary contract](../../006-skill-executor/contracts/execution-summary.md).

## Non-Goals

- Workflow execution semantics, retries, per-skill timeouts (006)
- Skill packaging/contract (005)
- Wildcard/pattern event matching, parallel dispatch (out of scope per spec)
