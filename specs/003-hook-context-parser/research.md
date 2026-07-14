# Research: Hook Context Parser

**Branch**: `003-hook-context-parser` | **Date**: 2026-07-14

---

## Decision: Implementation Language

**Decision**: Python 3.10+, stdlib only (`json`, `os`, `re`, `sys`)
**Rationale**: Project already requires Python 3.10+ (001 installer). JSON serialization,
path manipulation, and regex validation are all stdlib. POSIX sh cannot emit JSON safely
(002 research already rejected it for structured output).
**Alternatives considered**:
- POSIX sh — rejected: no safe JSON generation without jq dependency
- jq-based pipeline — rejected: external dependency violates project constraint

---

## Decision: Input Source — Environment Variables Only

**Decision**: Parser reads `HOOK_EVENT`, `HOOK_BRANCH`, `HOOK_FILES`, `HOOK_COMMITS` from
the environment. It never executes git commands.
**Rationale**: 002 hooks are the single capture point for raw git data (spec US2: parser
normalizes, downstream never re-queries). Keeping the parser git-free makes it a pure
function of its environment: trivially unit-testable, fast (SC-003), and runnable in any
directory (FR-007).
**Alternatives considered**:
- Parser shells out to git for missing fields — rejected: duplicates 002's capture logic,
  makes tests require a git repo, adds latency
- JSON on stdin — rejected: hooks are POSIX sh and cannot produce JSON safely

---

## Decision: Commits for pre-push — Extend Hook Contract with `HOOK_COMMITS`

**Decision**: Add optional `HOOK_COMMITS` (newline-delimited full SHAs) to the 002 hook
contract; `scripts/pre-push.sh` captures it with the same `git rev-list` it already runs
for new refs.
**Rationale**: Spec acceptance scenarios US1-3 and US2-3 require pre-push contexts to
include "the set of commits being pushed". 002's contract only carries files. Capturing
in the hook (not the parser) keeps the capture/normalize split clean. The pre-push loop
unifies both ref cases through `git rev-list` (`<local> --not --remotes` for new refs,
`<remote>..<local>` for updates) and derives files per commit via `git diff-tree`, so
commits come for free.
**Consequence**: "files" for an updated ref becomes the union of files touched by each
pushed commit (previously the net diff). This is more faithful to "files changed in
commits being pushed" (spec assumption) — a file changed then reverted within the range
is still included.
**Alternatives considered**:
- Parser derives commits via git — rejected: see input-source decision
- Leave commits out — rejected: fails US1-3/US2-3 acceptance

---

## Decision: Output Format

**Decision**: Single-line JSON object on stdout; `schema_version: "1.0"` field; all eight
fields present in every output regardless of event type or partiality.
**Rationale**: FR-003 requires an identical schema across hook types — fixed key set is
the strongest form. Versioning satisfies the spec assumption that schema changes are
breaking. Single-line output is pipe-friendly for orchestrate.sh (004).
**Alternatives considered**:
- Pretty-printed JSON — rejected: multi-line complicates log-line handling in 004
- Omit empty/unavailable fields — rejected: forces downstream presence checks (violates SC-001)

---

## Decision: Partial Context Semantics

**Decision**: Distinguish *unset* from *empty*:
- env var **unset** → field value `null` (or `[]`), field name appended to `unavailable[]`,
  message appended to `errors[]`, `partial: true`
- `HOOK_FILES` set but **empty** → `files: []`, **not** partial (spec: empty change set is
  a valid non-error result)
- `HOOK_COMMITS` unset is only an unavailability for `event == "pre-push"` (other events
  legitimately never set it)
- unknown `HOOK_EVENT` value → `event: null` + unavailable + error note
**Rationale**: US3 requires explicit markers on missing fields; the empty-changeset
assumption requires empty ≠ missing.
**Alternatives considered**:
- Treat empty as missing — rejected: contradicts spec assumption on empty change sets
- Fail on unknown event — rejected: SC-005 (never abort the git operation)

---

## Decision: Path Normalization

**Decision**: Split `HOOK_FILES` on newlines; strip whitespace; drop blanks; absolute
paths converted with `os.path.relpath(p, repo_root)` where `repo_root = os.getcwd()`
(git runs hooks at the repo top level); paths resolving outside the repo are dropped with
an error note; `os.path.normpath` applied; result deduped and sorted.
**Rationale**: Spec assumption: output paths are repo-relative. Sorting + dedup makes
output deterministic (constitution §5).
**Alternatives considered**:
- `git rev-parse --show-toplevel` for root — rejected: parser must not run git
- Preserve input order — rejected: nondeterministic across git versions; sorted is stable

---

## Decision: Commit ID Validation

**Decision**: Accept 40-hex (SHA-1) or 64-hex (SHA-256 repos) lowercase tokens; anything
else is dropped with an error note; order preserved (newest-first as produced by
`rev-list`), deduped.
**Rationale**: Cheap validation catches corrupt input without rejecting future SHA-256
repositories. Order preservation keeps rev-list's newest-first semantics for downstream.

---

## Decision: Failure Containment

**Decision**: `main()` wraps parsing in `try/except Exception`; on any internal failure it
emits a fallback all-unavailable partial context with the exception message in `errors[]`
and still exits 0.
**Rationale**: SC-005 — 100% of error cases must produce a partial context or logged parse
error; the parser can never be the reason a git operation aborts.
