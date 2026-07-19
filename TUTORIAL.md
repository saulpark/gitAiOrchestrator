# gitAiOrchestrator — Tutorial

gitAiOrchestrator turns git events (commit, merge, push) into automated,
Claude-Code-powered workflows. Thin git hooks capture what changed, a router matches the
event against `config/routes.json`, and an executor runs your registered **skills** —
small executables that receive the change context as JSON and can call Claude Code
through a shared bridge. Every run is recorded and can block, warn, or stay silent
depending on rules you configure.

```text
git commit ─→ pre-commit hook ─→ parse context ─→ route ─→ execute skills ─→ outcome
                (thin, POSIX sh)   (JSON, 003)    (004)     (005/006/007)     (008)
```

## 1. Installation

### Prerequisites

| Tool | Version | Notes |
|------|---------|-------|
| git | ≥ 2.28 | required |
| Python | ≥ 3.10 | runs the pipeline (stdlib only — no packages needed) |
| [uv](https://docs.astral.sh/uv/) | any | checked by the installer; used for dev tooling |
| [Claude Code CLI](https://claude.ai/code) | any | optional — only needed by skills that call Claude; everything else works without it |

### Install

```sh
git clone https://github.com/saulpark/gitAiOrchestrator.git
cd gitAiOrchestrator
python3 install.py
```

The installer validates the prerequisites, points `git config core.hooksPath` at the
versioned `.githooks/` directory, and ensures the hook scripts are executable. That's it —
no daemons, no services.

### Verify it works

```sh
git commit --allow-empty -m "test: hook smoke test"
tail -1 logs/hooks.log
# → [2026-…] route event=pre-commit dispatched=0 overall=empty outcome=none warnings=0
git reset --soft HEAD~1      # discard the test commit
```

The hook fired, the router found no configured skills, and your commit was untouched.
By default nothing is routed, so the system is invisible until you add a skill.

## 2. Small example: your first skill

A skill is a directory under `skills/` with two files: a `skill.json` manifest and an
executable `run` that reads the change context (JSON) on stdin and prints a result.
The full contract is in `specs/005-skill-contract/contracts/skill-contract.md`.

### Create it

```sh
mkdir -p skills/file-counter

cat > skills/file-counter/skill.json <<'EOF'
{
  "name": "file-counter",
  "version": "1.0.0",
  "description": "Reports how many files are in the commit",
  "input": "hook-context@1.0",
  "output": "skill-result@1.0",
  "behaviors": {"non_blocking": true, "idempotent": true}
}
EOF

cat > skills/file-counter/run <<'EOF'
#!/bin/sh
COUNT=$(python3 -c 'import json,sys; print(len(json.load(sys.stdin)["files"]))')
printf '{"schema_version": "1.0", "skill": "file-counter", "status": "ok", "summary": "%s file(s) in this change", "details": {}}' "$COUNT"
EOF
chmod +x skills/file-counter/run
```

### Register and route it

```sh
python3 src/skill_registry.py register skills/file-counter
# → registered 'file-counter' (contract 1.1)
```

Then map it to the pre-commit event in `config/routes.json`:

```json
{
  "version": "1.1",
  "routes": {
    "pre-commit": ["file-counter"],
    "post-merge": [],
    "pre-push": []
  },
  "outcomes": {},
  "run_retention": 50
}
```

### Run it

```sh
echo hello > demo.txt && git add demo.txt
git commit -m "feat: demo"
python3 src/run_records.py show --last
```

```text
run      20260719T…Z-pre-commit
event    pre-commit  branch master  at 2026-07-19T…Z
context  files=1 commits=0 partial=False
outcome  NONE

- file-counter: success (48ms) -> none  [rule: default]
    skill succeeded
    detail: 1 file(s) in this change
```

`python3 src/run_records.py list` shows the history of recent runs.

## 3. Where to go next

**Call Claude Code from a skill.** Pipe a request through the shared bridge — no
Claude-specific code needed in your skill:

```sh
CTX=$(cat)   # inside your skill's run script
printf '{"schema_version":"1.0","context":%s,"task":"Summarize this change set in one line."}' "$CTX" \
  | python3 "$(git rev-parse --show-toplevel)/src/claude_bridge.py"
```

The bridge runs `claude` headless with a prompt bounded to the changed files, inherits
your project's `.claude/settings.json` and `CLAUDE.md`, and returns a structured result
(`ok` / `error` / `timeout` / `unavailable`). See
`specs/007-claude-code-bridge/contracts/bridge-interface.md`.

**Enforce outcomes.** Make a failing skill block the commit instead of just warning:

```json
"outcomes": {"file-counter": {"on_failure": "block"}}
```

`block` aborts the git operation with a clear message, `warn` (the default) proceeds
with a visible warning, `skip` stays silent but still records the failure. Rules take
effect on the next commit — no reinstall.

**Useful commands:**

```sh
python3 src/skill_registry.py list          # registered skills
python3 src/skill_registry.py validate      # re-check all skills against the contract
python3 src/run_records.py list --limit 10  # recent runs
tail -20 logs/hooks.log                     # one line per routed event
```

**Contracts** (each feature's exact schemas): `specs/00N-*/contracts/`.

**Run the test suite** (dev):

```sh
uv venv .venv && uv pip install -p .venv/bin/python pytest ruff
.venv/bin/pytest tests/ -q && .venv/bin/ruff check src/
```
