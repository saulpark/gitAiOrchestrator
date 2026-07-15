# Quickstart: Skill Contract

**Branch**: `005-skill-contract`

## Author + register a skill (US1, SC-001)

```sh
mkdir -p skills/hello
cat > skills/hello/skill.json <<'EOF'
{
  "name": "hello",
  "version": "1.0.0",
  "description": "Prints a greeting result",
  "input": "hook-context@1.0",
  "output": "skill-result@1.0",
  "behaviors": {"non_blocking": true, "idempotent": true}
}
EOF
printf '#!/bin/sh\ncat > /dev/null\nprintf %s \x27{"schema_version": "1.0", "skill": "hello", "status": "ok", "summary": "hi", "details": {}}\x27\n' > skills/hello/run
chmod +x skills/hello/run
python3 src/skill_registry.py register skills/hello   # → registered 'hello' (contract 1.0)
python3 src/skill_registry.py list
```

## See rejection feedback (US2, SC-003)

```sh
mkdir -p skills/bad && echo '{"name": "BAD NAME"}' > skills/bad/skill.json
python3 src/skill_registry.py register skills/bad
# exit 1, one line per violation: name, version, description, input, output, behaviors, entry-point
```

## Route to a registered skill end-to-end

Add `"hello"` to `pre-commit` in `config/routes.json`, then:

```sh
git commit --allow-empty -m "test: hello skill"
tail -1 logs/hooks.log   # → route event=pre-commit invoked=1 …
```

## Deregister (FR-007)

```sh
python3 src/skill_registry.py deregister hello
# warning if config/routes.json still references 'hello'
```

## Re-validate after a contract change (FR-008)

```sh
python3 src/skill_registry.py validate
```

## Tests

```sh
.venv/bin/pytest tests/test_skill_registry.py tests/test_route_workflows.py -v
.venv/bin/ruff check src/ tests/
```
