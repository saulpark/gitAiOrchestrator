# Research: Workflow Router

**Branch**: `004-workflow-router` | **Date**: 2026-07-14

---

## Decision: Configuration Format — JSON

**Decision**: `config/routes.json`, parsed with stdlib `json`.
**Rationale**: Project constraint is stdlib-only runtime. YAML requires PyYAML; TOML
writing is awkward and `tomllib` is read-only 3.11+ (project floor is 3.10). JSON is
already the context interchange format (003), keeping one serialization across the system.
**Alternatives considered**:
- YAML — rejected: third-party dependency
- TOML — rejected: 3.11+ stdlib only, mixed-version risk on 3.10 floor
- Shell-sourced env file — rejected: cannot express lists per event safely

---

## Decision: Config Schema

**Decision**:

```json
{
  "version": "1.0",
  "routes": {
    "pre-commit": ["workflow-a"],
    "post-merge": [],
    "pre-push": []
  }
}
```

Unknown top-level keys ignored (forward compatibility). Route values must be lists of
strings; a non-list value invalidates only that event's entry (warning), not the file.
**Rationale**: Flat event→list mapping matches the spec's Route entity exactly; ordering
in the list is execution order (spec assumption: sequential, configured order).

---

## Decision: Router I/O Protocol

**Decision**: Context JSON on stdin (exactly what `parse_context.py` emits), DispatchResult
JSON on stdout, human warnings on stderr prefixed `[router warning]`, exit 0 always.
**Rationale**: Pipe-composable with 003 (`parse_context.py | route_workflows.py`), which is
how `orchestrate.sh` wires it. stderr passes through the 002 hooks to the developer's
terminal (SC-003 visibility); stdout is structured for logs/tooling.
**Alternatives considered**:
- Context via env re-read — rejected: parser already normalized it; re-parsing duplicates 003
- Warnings on stdout — rejected: would corrupt the DispatchResult JSON stream

---

## Decision: Invoker Abstraction (FR-009)

**Decision**: Core function `route(context, config, invoker) -> dict` where
`invoker(identifier, context) -> tuple[str, str]` returns `(outcome, detail)` with outcome
in `{"invoked", "unresolvable", "failed"}`. Tests inject fakes; the CLI wires the default.
**Rationale**: The spec explicitly splits selection (this feature) from execution (005/006).
A callable seam makes dispatch behavior testable without git, without processes.

---

## Decision: Provisional Default Invoker

**Decision**: Identifier `<id>` resolves to `skills/<id>/run`; if that file exists and is
executable it runs with the context JSON on stdin (60 s guard, `subprocess.run`), exit 0 →
`invoked`, non-zero → `failed`; missing/non-executable → `unresolvable`.
**Rationale**: Gives US1's independent test a real end-to-end path today. 005 defines the
skill contract and 006 the executor; this default is explicitly replaceable and marked
provisional in the contract doc.
**Alternatives considered**:
- Always-unresolvable stub — rejected: US1 acceptance needs workflows to actually run
- Full executor with per-skill timeouts/retries — rejected: that is feature 006's scope

---

## Decision: Failure & Edge Semantics

**Decision**:
- Workflow failure or invoker exception → outcome `failed` + warning; **subsequent
  workflows still run** (spec assumption: per-workflow isolation)
- Event with no route entry (or empty list) → no dispatch, log entry, no warning (FR-006)
- Context with `event: null`/unknown event → no dispatch, warning (cannot route a partial
  context's event)
- Missing config file → empty config + warning (FR-008)
- Malformed JSON / wrong shape → empty config + warning naming the parse error (FR-008)
- Duplicate identifiers in one route → invoked once per occurrence, in order (configured
  order is truth; dedup would surprise)

---

## Decision: Logging

**Decision**: The router appends one summary line per invocation to `logs/hooks.log`
(`--log` flag): timestamp, event, counts per outcome. The 002 stub's log line moves here —
`orchestrate.sh` no longer logs directly.
**Rationale**: Keeps orchestrate.sh thin (constitution §11) and puts the log write where
the information lives. Log write failures are swallowed (logging must never break routing).
