# Data Model: Hook Context Parser

**Branch**: `003-hook-context-parser` | **Date**: 2026-07-14

---

## Entity: HookContext (JSON output)

Emitted as a single-line JSON object on stdout. **All eight keys are present in every
output** — same names, same types, same presence rules for all three hook types (FR-003).

| Field | Type | Nullable | Description |
|-------|------|----------|-------------|
| `schema_version` | string | no | `"1.0"`; major bump = breaking change |
| `event` | string \| null | yes | `pre-commit` \| `post-merge` \| `pre-push`; `null` when unavailable |
| `branch` | string \| null | yes | Branch name; `"HEAD"` in detached state (valid, not partial); `null` when unavailable |
| `files` | string[] | no | Repo-relative paths, deduped, sorted; `[]` when empty or unavailable |
| `commits` | string[] | no | Full SHAs (rev-list order); populated only for pre-push; `[]` otherwise |
| `partial` | boolean | no | `true` iff `unavailable` is non-empty |
| `unavailable` | string[] | no | Field names that could not be populated |
| `errors` | string[] | no | Human-readable parse notes (missing vars, dropped paths/commits) |

**Validation rules**:
- `event` must be one of the three values; anything else → `null` + `unavailable` + error note
- `branch` empty/unset → `null` + `unavailable`; `"HEAD"` passes through as-is
- `files`: unset `HOOK_FILES` → unavailable; set-but-empty → valid `[]` (empty change set)
- `commits`: tokens must match `[0-9a-f]{40}` or `[0-9a-f]{64}`; invalid tokens dropped with error note; unset `HOOK_COMMITS` is an unavailability only when `event == "pre-push"`

---

## Entity: RawHookInput (environment variables)

| Variable | Set by | Format |
|----------|--------|--------|
| `HOOK_EVENT` | all 002 hooks | one of the three event names |
| `HOOK_BRANCH` | all 002 hooks | branch name; `HEAD` if detached |
| `HOOK_FILES` | all 002 hooks | newline-delimited paths; may be empty |
| `HOOK_COMMITS` | pre-push only (new in 003) | newline-delimited full SHAs |

---

## Entity: ParseResult

The parser has exactly two outcome shapes, both exit 0:

| Outcome | `partial` | Trigger |
|---------|-----------|---------|
| Complete context | `false` | all fields populated |
| Partial context | `true` | any unset/invalid required input; includes fallback context on internal exception (all four data fields unavailable, exception message in `errors`) |

There is no error exit — SC-005.

---

## Flow

```text
002 hook script                    003 parser                       004 router (future)
sets HOOK_EVENT, HOOK_BRANCH,  →   python3 src/parse_context.py  →  reads JSON on stdout
HOOK_FILES [, HOOK_COMMITS]        env → HookContext JSON, exit 0
```
