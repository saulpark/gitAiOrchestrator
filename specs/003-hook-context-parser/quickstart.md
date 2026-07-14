# Quickstart: Hook Context Parser

**Branch**: `003-hook-context-parser`

## Run the parser manually (FR-007)

From the repository root:

```sh
HOOK_EVENT=pre-commit \
HOOK_BRANCH=$(git rev-parse --abbrev-ref HEAD) \
HOOK_FILES=$(git diff --cached --name-only --diff-filter=ACM) \
python3 src/parse_context.py
```

Expected: one line of JSON with `"partial": false` and your staged files sorted in
`"files"`.

## Simulate a partial context

```sh
HOOK_EVENT=pre-commit python3 src/parse_context.py
```

Expected: `"partial": true`, `"unavailable": ["branch", "files"]`, exit code 0.

```sh
echo $?   # → 0
```

## Run the tests

```sh
pytest tests/test_parse_context.py -v
ruff check src/
```

## Verify schema uniformity across hook types (SC-004)

```sh
for e in pre-commit post-merge pre-push; do
  HOOK_EVENT=$e HOOK_BRANCH=main HOOK_FILES="a.py" HOOK_COMMITS="" \
    python3 src/parse_context.py | python3 -c 'import json,sys; print(sorted(json.load(sys.stdin)))'
done
```

Expected: three identical key lists.
