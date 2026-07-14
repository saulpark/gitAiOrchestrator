# Contract: Hook Context Schema

**Branch**: `003-hook-context-parser` | **Date**: 2026-07-14
**Schema version**: `1.0` (major bump = breaking change; downstream features pin against this)

This contract defines the parser's CLI and its JSON output — the shape every downstream
feature (004 router onward) consumes. It extends the 002 orchestration interface with one
new optional environment variable, `HOOK_COMMITS`.

---

## Invocation

```sh
HOOK_EVENT="pre-commit" \
HOOK_BRANCH="main" \
HOOK_FILES="src/foo.py
src/bar.py" \
python3 "$(git rev-parse --show-toplevel)/src/parse_context.py"
```

- Working directory MUST be the repository root (git guarantees this for hooks; manual
  callers must `cd` first) — absolute paths are relativized against cwd.
- Exit code is **always 0**, including on malformed input and internal errors.
- Output: exactly one line of JSON on stdout. Nothing on stderr in normal operation.

## Input Environment Variables

| Variable | Required | Format |
|----------|----------|--------|
| `HOOK_EVENT` | yes* | `pre-commit` \| `post-merge` \| `pre-push` |
| `HOOK_BRANCH` | yes* | branch name; `HEAD` for detached state |
| `HOOK_FILES` | yes* | newline-delimited paths; empty string = empty change set (valid) |
| `HOOK_COMMITS` | pre-push only | newline-delimited full SHAs (40- or 64-hex), rev-list order |

*"Required" means its absence produces a **partial context** (never a failure).

## Output Schema

```json
{
  "schema_version": "1.0",
  "event": "pre-push",
  "branch": "003-hook-context-parser",
  "files": ["src/bar.py", "src/foo.py"],
  "commits": ["0f00ba4d3c1622db1b91b3fbf2ba9165ba32ee54"],
  "partial": false,
  "unavailable": [],
  "errors": []
}
```

All eight keys are always present. `files` is deduped and sorted; `commits` preserves
rev-list order (newest first). See [data-model.md](../data-model.md) for field rules.

### Partial context example (missing branch)

```json
{
  "schema_version": "1.0",
  "event": "pre-commit",
  "branch": null,
  "files": ["a.py"],
  "commits": [],
  "partial": true,
  "unavailable": ["branch"],
  "errors": ["HOOK_BRANCH missing or empty"]
}
```

## Hook Contract Addendum (002 interface v1.1)

`scripts/pre-push.sh` additionally exports `HOOK_COMMITS` — the `git rev-list` of the
pushed range (`<remote_sha>..<local_sha>`, or `<local_sha> --not --remotes` for new
refs), accumulated across all pushed refs. pre-commit and post-merge do not set it.

## Non-Goals

- What downstream does with the context (004+)
- Persistence of contexts between runs (explicitly out of scope per spec)
- Hook types beyond the three supported events
