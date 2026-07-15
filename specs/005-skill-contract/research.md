# Research: Skill Contract

**Branch**: `005-skill-contract` | **Date**: 2026-07-16

---

## Decision: Manifest File — `skills/<dir>/skill.json`

**Decision**: Each skill directory contains `skill.json` (metadata) + `run` (executable
entry point). Registration reads the manifest, validates, and records the directory in the
registry.
**Rationale**: JSON keeps the single-serialization rule (002/003/004). A manifest separate
from the executable lets validation happen without executing anything (SC-002 safety).
**Alternatives considered**:
- Metadata as comments in `run` — rejected: unparseable across languages, fragile
- Python entry points — rejected: skills may be any executable (sh, python, binary)

---

## Decision: Contract v1.0 Validation Rules

| # | Rule (violation name) | Requirement |
|---|----------------------|-------------|
| 1 | `missing-manifest` | `skill.json` exists and is valid JSON |
| 2 | `name` | required; string matching `^[a-z0-9][a-z0-9-]{0,63}$` |
| 3 | `name-reserved` | name not in reserved set `{registry, contract, skills}` |
| 4 | `version` | required; semver `X.Y.Z` |
| 5 | `description` | required; non-empty string |
| 6 | `input` | required; must be exactly `"hook-context@1.0"` (003 schema) |
| 7 | `output` | required; must be exactly `"skill-result@1.0"` |
| 8 | `behaviors` | required object; `non_blocking` and `idempotent` present as booleans; `non_blocking` must be `true` |
| 9 | `entry-point` | executable file `run` exists in the skill directory |

All rules are checked in one pass; a rejection lists every violated rule by name (SC-003).
**Rationale**: Rules 6–7 enforce the spec assumptions that all skills accept the standard
context and produce the standard result shape — an "incompatible input/output shape" (US2-2)
is a declared mismatch, caught at registration.

---

## Decision: Registry Layout — `skills/registry.json`

```json
{
  "contract_version": "1.0",
  "skills": {
    "doc-sync": {"dir": "doc-sync", "version": "1.0.0", "description": "…"}
  }
}
```

**Decision**: Committed file; key = skill name; `dir` relative to `skills/`. Router resolves
name → `skills/<dir>/run`.
**Rationale**: Local to the repository (spec assumption), versioned alongside the config that
references it (constitution §2/§5). Storing `contract_version` enables FR-008 drift detection.
**Alternatives considered**:
- Directory scan as implicit registry — rejected: no validation gate, violates SC-002
- SQLite — rejected: binary blob in git, overkill

---

## Decision: Duplicate & Deregistration Semantics

- `register` with an existing name → **rejected** (`duplicate-name`) unless `--update` is
  passed (explicit intent per FR-006)
- `deregister <name>` removes the entry; if `config/routes.json` still references the name,
  a warning lists the affected events (FR-007) — the route entry is left in place (the
  router already degrades to `unresolvable` warnings at dispatch)

---

## Decision: Contract Evolution (FR-008)

**Decision**: `validate` re-checks every registered skill against the current rules and
compares the registry's stored `contract_version` with the tool's `CONTRACT_VERSION`,
reporting non-compliant skills by name; exit 1 if any (CI-friendly). `register`/`--update`
always stamp the current contract version.
**Rationale**: One registry scan satisfies SC-005. Re-validation on contract change is
pull-based (run `validate`) rather than a daemon — deterministic and scriptable.

---

## Decision: Router Resolution via Registry (replaces 004 provisional invoker)

**Decision**: `make_skills_invoker(skills_dir)` now loads `<skills_dir>/registry.json`;
identifier resolvable iff present in the registry **and** `skills/<dir>/run` is executable.
Unregistered identifiers are `unresolvable` even if a directory exists.
**Rationale**: FR-004/SC-004 make the registry the single resolution source; a directory
dropped into `skills/` without registration must not be silently executable (SC-002 spirit).
**Consequence**: the 004 quickstart demo flow gains one step: `register` the demo skill.

---

## Decision: Skill Output Contract — `skill-result@1.0`

```json
{"schema_version": "1.0", "skill": "doc-sync", "status": "ok", "summary": "…", "details": {}}
```

`status` ∈ `{ok, error, skipped}`. Documented in the contract artifact; **runtime**
enforcement is 006's scope (spec: behavioral requirements trusted at registration time).
