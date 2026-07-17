# Skill Contract — v1.1

**The standalone, authoritative definition of what a skill must declare and exhibit.**
Read this before writing a skill; a compliant skill registers on the first attempt (SC-001).

---

## What is a skill?

A skill is a directory under `skills/` containing:

```text
skills/<dir>/
├── skill.json   # metadata manifest (validated at registration)
└── run          # executable entry point (any language, chmod +x)
```

It becomes dispatchable only after registration:

```sh
python3 src/skill_registry.py register skills/<dir>
```

## Required manifest fields (`skill.json`)

| Field | Type | Rule |
|-------|------|------|
| `name` | string | unique; `^[a-z0-9][a-z0-9-]{0,63}$`; not reserved (`registry`, `contract`, `skills`) |
| `version` | string | semver `X.Y.Z` |
| `description` | string | non-empty, human-readable |
| `input` | string | exactly `"hook-context@1.0"` — skills accept the standard context, nothing else |
| `output` | string | exactly `"skill-result@1.0"` |
| `behaviors` | object | `non_blocking: true` (mandatory) and `idempotent: <bool>` — declared by the author, trusted at registration |

### Optional manifest fields (v1.1)

| Field | Type | Rule |
|-------|------|------|
| `time_budget_seconds` | number | execution time budget enforced by the executor (006); `0 < n ≤ 600`; absent → system default (30 s) |

Example:

```json
{
  "name": "doc-sync",
  "version": "1.0.0",
  "description": "Regenerates docs for changed modules",
  "input": "hook-context@1.0",
  "output": "skill-result@1.0",
  "behaviors": {"non_blocking": true, "idempotent": true}
}
```

## Input your skill receives

The hook context (003 schema v1.0) as JSON on **stdin** — all eight keys always present:

```json
{"schema_version": "1.0", "event": "pre-commit", "branch": "main",
 "files": ["src/foo.py"], "commits": [], "partial": false,
 "unavailable": [], "errors": []}
```

Handle `partial: true` gracefully — decide to proceed or exit `skipped`; never crash on it.

## Output your skill must produce

`skill-result@1.0` as a single JSON line on **stdout**:

```json
{"schema_version": "1.0", "skill": "doc-sync", "status": "ok",
 "summary": "3 docs regenerated", "details": {}}
```

- `status`: `ok` | `error` | `skipped`
- Exit code `0` for `ok`/`skipped`; non-zero for `error`
- Diagnostics go to **stderr**, never stdout

## Behavioral rules

1. **Non-blocking**: never prompt, never wait on the network without a timeout — you run
   inside a git operation.
2. **Idempotent** (if declared): running twice on the same context produces the same result.
3. **Repo-relative**: treat `files` paths as relative to the repo root (your cwd).
4. **No git state mutation**: skills must not commit, push, or rewrite refs.

## Registry operations

```sh
python3 src/skill_registry.py register skills/<dir>          # validate + add (exit 1 with ALL violations if rejected)
python3 src/skill_registry.py register skills/<dir> --update # explicit re-registration (FR-006)
python3 src/skill_registry.py deregister <name>              # remove (+ warning if routes still reference it)
python3 src/skill_registry.py resolve <name>                 # print registry entry (router uses this path)
python3 src/skill_registry.py list                           # catalog
python3 src/skill_registry.py validate                       # re-check all skills against current contract (FR-008)
```

## Versioning

This contract is versioned (`1.1` — v1.1 added optional `time_budget_seconds` for the
006 executor). Adding a required field is a minor bump + `validate`
run to surface newly non-compliant skills (SC-005); removing/redefining a field is a major
bump. The registry records the contract version it was last written under.
