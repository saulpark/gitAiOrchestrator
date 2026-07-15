# Data Model: Workflow Router

**Branch**: `004-workflow-router` | **Date**: 2026-07-14

---

## Entity: RoutingConfiguration (`config/routes.json`)

| Field | Type | Rules |
|-------|------|-------|
| `version` | string | `"1.0"`; unknown versions accepted with warning |
| `routes` | object | keys: event names; values: ordered list of workflow identifier strings |

Validation: file missing → `{}` + warning; JSON parse error → `{}` + warning; `routes`
not an object → `{}` + warning; a route value that is not a list of strings → that entry
treated as `[]` + warning naming the event.

## Entity: Route

One key/value pair in `routes`: event type → ordered workflow identifiers. Order = execution
order. Duplicates allowed (invoked per occurrence).

## Entity: DispatchResult (stdout JSON)

| Field | Type | Description |
|-------|------|-------------|
| `schema_version` | string | `"1.0"` |
| `event` | string \| null | event routed (from context) |
| `results` | object[] | one per attempted workflow, in order |
| `results[].workflow` | string | configured identifier |
| `results[].outcome` | string | `invoked` \| `unresolvable` \| `failed` |
| `results[].detail` | string | human-readable note (`""` when invoked cleanly) |
| `warnings` | string[] | everything also printed to stderr |

Event-level skip (no route entry, unroutable context) → `results: []` and, for unroutable
contexts or config problems, an entry in `warnings`.

## Entity: Invoker (callable seam)

```python
invoker(identifier: str, context: dict) -> tuple[str, str]  # (outcome, detail)
```

`outcome` must be one of the three enum values. Any exception raised by an invoker is
caught by the router and converted to `("failed", str(exc))`.

### Provisional default invoker (CLI)

`skills/<identifier>/run` — executable file, receives context JSON on stdin, cwd = repo
root, 60 s guard. Exit 0 → `invoked`; non-zero → `failed (exit N)`; missing/non-executable
→ `unresolvable`. Formalized/replaced by 005/006.

## Flow

```text
002 hook → orchestrate.sh:
  python3 src/parse_context.py        (env → context JSON)
    | python3 src/route_workflows.py  (context + config/routes.json → dispatch)
        ├─ stdout: DispatchResult JSON (→ logs via orchestrate redirect if desired)
        ├─ stderr: [router warning] …  (→ developer terminal through hook)
        └─ logs/hooks.log: timestamped summary line
```
