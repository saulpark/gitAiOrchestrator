# Research: Run Observability and Outcome Enforcement

**Branch**: `008-run-observability` | **Date**: 2026-07-19

---

## Decision: Block Signal — reserved exit code 10

**Decision**: The router exits **10** iff the final outcome is block (pre-commit/pre-push
only). `scripts/lib.sh` gains `_finish_hook`: exit 10 → `[hook blocked]` to stderr and
`exit 1` (aborts the git operation); any other non-zero → `[hook warning]` and `exit 0`;
zero → `exit 0`. orchestrate.sh needs no change (its exit is the router's).
**Rationale**: A reserved code cleanly separates "the automation *decided* to block"
(FR-006) from "the automation *broke*" (which must never block — constitution §6). Exit
143 from the hook's 5 s timeout stays on the warn path, so a hung run can never block.
**Alternatives considered**:
- Sentinel file — rejected: racy, needs cleanup, invisible in the exit-code chain
- Any non-zero blocks — rejected: turns every crash into a blocked commit

---

## Decision: Outcome Rules in `config/routes.json` (schema v1.1)

```json
{
  "version": "1.1",
  "routes": {"pre-commit": ["doc-sync"]},
  "outcomes": {"doc-sync": {"on_failure": "block"}},
  "run_retention": 50
}
```

**Decision**: Optional top-level `outcomes` (skill → rule) and `run_retention` (int,
default 50). Rule shape: `{"on_failure": "block" | "warn" | "skip"}` — applies to every
non-success status (`failure`, `timeout`, `skipped`). No rule or invalid rule → default
**warn** with a note (FR-009). Success → outcome `none` (silent, recorded).
**Rationale**: Spec assumption places rules in the routing configuration; `on_failure`
covering all non-success statuses keeps the model one-knob simple — teams reach for
per-status granularity only when they need it (future minor bump).

---

## Decision: Outcome Aggregation & Downgrade

- Final outcome = strongest across skills: `block` > `warn` > `none` (`skip`-ruled
  results contribute nothing visible; everything is recorded)
- Two blocks → final block, **all** blocking skills named in the message (edge case)
- `post-merge` + block → downgraded to warn, `block_downgraded: true` recorded with a note
  (the merge already completed — spec assumption)
- Empty plan / all-skipped → outcome `none`, record still written (FR-001/SC-002)

---

## Decision: Run Record Store — `logs/runs/*.json`

**Decision**: One JSON file per run: `logs/runs/<UTC %Y%m%dT%H%M%S.%fZ>-<event>.json`
(lexically sortable = chronologically sortable). Written best-effort after execution;
write failures never affect the git operation. Retention: after each write, prune oldest
beyond `run_retention` (default 50). `logs/` is already gitignored — records are local
per-clone artifacts, matching "run history queryable from the repository" without
polluting version control.
**Alternatives considered**:
- Append-only JSONL — rejected: retention pruning and `show <id>` are simpler with files
- Committing records — rejected: automation commits fighting user commits

---

## Decision: History CLI — `python3 src/run_records.py list|show`

**Decision**: `list [--limit N]` prints newest-first one-line summaries
(`<id>  <event>  <final>  ok=N fail=N` — US1-3); `show <id>` and `show --last` render a
human-readable report: event, timestamp, branch, per-skill table (status, duration, rule,
outcome, detail), final outcome + reason (SC-001/SC-003). JSON of any record is the file
itself — no extra tooling (FR-003).

---

## Decision: Router Output — DispatchResult v1.2 (additive)

Adds `final_outcome`, `outcomes` (per-skill evaluation incl. matched rule + reason),
`run_record` (path or null). Warn messages now flow through outcome evaluation: only
warn-outcome results print `[router warning]`; skip-ruled results are silent (log/record
only — FR-005). Block prints `[hook blocked] skill '<name>': <reason>` to stderr before
the exit-10 return.
