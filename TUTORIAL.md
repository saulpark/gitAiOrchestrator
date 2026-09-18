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

## 3. Worked example: a documentation updater on push

The first skill was deliberately trivial. This one is the real shape of the system: it
runs on `pre-push`, sends the pushed change set to Claude through the bridge, and writes
proposed documentation updates into the working tree for review. Everything below was run
end to end; the sample outputs are real.

### 3.1 The skill

```sh
mkdir -p skills/doc-updater

cat > skills/doc-updater/skill.json <<'EOF'
{
  "name": "doc-updater",
  "version": "1.0.0",
  "description": "Proposes documentation updates for the pushed change set",
  "input": "hook-context@1.0",
  "output": "skill-result@1.0",
  "behaviors": {"non_blocking": true, "idempotent": false},
  "time_budget_seconds": 90
}
EOF
```

`idempotent: false` is the honest declaration here — the output comes from a model, so two
runs on the same change set are not guaranteed to match. `time_budget_seconds: 90` gives
the executor room for a Claude call (but see §3.5 — the hook has its own, much shorter cap).

```sh
cat > skills/doc-updater/run <<'EOF'
#!/usr/bin/env python3
"""doc-updater — asks Claude which docs the pushed change set makes stale."""
import json
import os
import subprocess
import sys

PROPOSALS = "docs/pending-doc-updates.md"
CODE_SUFFIXES = (".py", ".sh", ".js", ".ts", ".go", ".rs", ".java")


def emit(status, summary, details=None, exit_code=0):
    json.dump({"schema_version": "1.0", "skill": "doc-updater", "status": status,
               "summary": summary, "details": details or {}}, sys.stdout)
    sys.exit(exit_code)


context = json.load(sys.stdin)

# Constitution 7/8: only code changes can make documentation stale.
code = [f for f in context["files"] if f.endswith(CODE_SUFFIXES)]
if not code:
    emit("skipped", "no code files in this change set")

request = {
    "schema_version": "1.0",
    "context": dict(context, files=code),
    "task": ("For each changed file, name the documentation that now describes "
             "outdated behavior and state in one line what needs to change. "
             "Answer 'NONE' if the docs are still accurate. Do not edit files."),
    "options": {"max_turns": 2},
}
root = subprocess.run(["git", "rev-parse", "--show-toplevel"],
                      capture_output=True, text=True).stdout.strip()
proc = subprocess.run([sys.executable, os.path.join(root, "src/claude_bridge.py")],
                      input=json.dumps(request), capture_output=True, text=True)
result = json.loads(proc.stdout)

if result["status"] == "unavailable":
    # Degrade rather than fail: Claude is optional tooling (bridge contract).
    emit("skipped", "claude CLI unavailable — documentation not checked")
if result["status"] != "ok":
    print(f"[doc-updater] bridge {result['status']}: {result['error']}", file=sys.stderr)
    emit("error", f"bridge {result['status']}", {"error": result["error"]}, exit_code=1)

answer = result["output_text"].strip()
if answer.upper().startswith("NONE"):
    emit("ok", f"docs still accurate for {len(code)} changed file(s)")

# Constitution 6/10: propose for review, never overwrite documentation silently.
os.makedirs(os.path.dirname(PROPOSALS), exist_ok=True)
with open(PROPOSALS, "w", encoding="utf-8") as fh:
    fh.write(f"# Pending documentation updates\n\n"
             f"Branch `{context['branch']}` — {len(code)} changed file(s)\n\n{answer}\n")
emit("ok", f"proposals written to {PROPOSALS}", {"files": code})
EOF
chmod +x skills/doc-updater/run
```

Three decisions worth copying into your own skills:

- **Narrow the change set before spending a Claude call.** Only code files can invalidate
  docs; a push of `.md` files exits `skipped` in milliseconds and never invokes Claude.
- **Decide what an unavailable Claude means.** The bridge reports `unavailable` when the
  CLI is missing — this skill degrades to `skipped`; a stricter one returns `error` and is
  routed with `on_failure: block`.
- **Propose, don't overwrite.** The result is a review file, not an in-place doc rewrite.

### 3.2 Configure it

```sh
python3 src/skill_registry.py register skills/doc-updater
# → registered 'doc-updater' (contract 1.1)
python3 src/skill_registry.py list
# → doc-updater 1.0.0 — Proposes documentation updates for the pushed change set
```

Then route it on `pre-push` in `config/routes.json`:

```json
{
  "version": "1.1",
  "routes": {
    "pre-commit": [],
    "post-merge": [],
    "pre-push": ["doc-updater"]
  },
  "outcomes": {"doc-updater": {"on_failure": "warn"}},
  "run_retention": 50
}
```

`warn` lets a failing check through with a visible message; `block` refuses the push
(§3.4). Both files are re-read on every event — no reinstall, no restart.

### 3.3 What happens on `git push`, component by component

| # | Component | What it does |
|---|-----------|--------------|
| 1 | `git` → `.githooks/pre-push` | `core.hooksPath` makes git run the shim, which `exec`s `scripts/pre-push.sh`. Git passes the remote on argv and one `<local ref> <local sha> <remote ref> <remote sha>` line per pushed ref on **stdin** |
| 2 | [`scripts/pre-push.sh`](scripts/pre-push.sh) | Resolves the pushed range (`git rev-list remote_sha..local_sha`, or `--not --remotes` for a new branch), collects files with `git diff-tree`, exports `HOOK_EVENT/BRANCH/FILES/COMMITS`, then runs orchestration under a **5-second** watchdog |
| 3 | [`scripts/orchestrate.sh`](scripts/orchestrate.sh) | `parse_context.py \| route_workflows.py` — the whole pipeline is this one pipe |
| 4 | [`src/parse_context.py`](src/parse_context.py) | Environment → context JSON (paths repo-relative, deduped, sorted; commits validated, push order kept) |
| 5 | [`src/route_workflows.py`](src/route_workflows.py) | Re-reads `routes.json`, selects `routes["pre-push"] → ["doc-updater"]`, hands the plan to the executor |
| 6 | [`src/execute_skills.py`](src/execute_skills.py) | Resolves the name through `skills/registry.json`, reads the 90 s budget from `skill.json`, runs `skills/doc-updater/run` with the context on stdin |
| 7 | `skills/doc-updater/run` | Filters to code files, builds a BridgeRequest, writes `docs/pending-doc-updates.md`, prints `skill-result@1.0` |
| 8 | [`src/claude_bridge.py`](src/claude_bridge.py) | Prompt bounded to *those* files and commits + "do not scan the rest of the repository"; runs `claude -p --output-format json --max-turns 2 --settings {"disableAllHooks":true}` in the repo root, so your `CLAUDE.md` applies and no nested hooks fire |
| 9 | [`src/run_records.py`](src/run_records.py) | Applies the outcome rule, writes `logs/runs/<id>.json`, prunes to `run_retention` |
| 10 | `route_workflows` → `_finish_hook` | Exit 0 → push proceeds; exit 10 → `[hook blocked]` and the push is aborted |

Step 4 produces exactly this:

```json
{"schema_version": "1.0", "event": "pre-push", "branch": "008-run-observability",
 "files": ["src/route_workflows.py", "src/run_records.py"],
 "commits": ["348a98f…aa", "9768e1b…bb"],
 "partial": false, "unavailable": [], "errors": []}
```

and step 9 leaves this behind:

```text
run      20260904T101855.838243Z-pre-push
event    pre-push  branch demo-push-flow  at 2026-09-04T10:18:55Z
context  files=1 commits=1 partial=False
outcome  NONE

- doc-updater: success (57ms) -> none  [rule: {"on_failure": "warn"}]
    skill succeeded
    detail: proposals written to docs/pending-doc-updates.md
```

### 3.4 Testing it

Work outwards — each level adds one component, so a failure tells you where it lives.

**Level 1 — the skill alone.** No git, no hooks, no Claude:

```sh
echo '{"schema_version":"1.0","event":"pre-push","branch":"demo","files":["README.md"],
       "commits":[],"partial":false,"unavailable":[],"errors":[]}' | skills/doc-updater/run
# → {"schema_version": "1.0", "skill": "doc-updater", "status": "skipped",
#    "summary": "no code files in this change set", "details": {}}
```

**Level 2 — stub the `claude` CLI.** Tests never need a model. Point `claude_command` at a
script that prints what the real CLI would:

```sh
mkdir -p /tmp/fakebin
cat > /tmp/fakebin/claude <<'EOF'
#!/bin/sh
printf '{"result": "src/run_records.py: TUTORIAL.md still documents the old retention default."}\n'
EOF
chmod +x /tmp/fakebin/claude

cp config/bridge.json config/bridge.json.bak
python3 - <<'EOF'
import json
cfg = json.load(open("config/bridge.json"))
cfg["claude_command"] = "/tmp/fakebin/claude"
json.dump(cfg, open("config/bridge.json", "w"), indent=2)
EOF

echo '{"schema_version":"1.0","event":"pre-push","branch":"demo","files":["src/run_records.py"],
       "commits":[],"partial":false,"unavailable":[],"errors":[]}' | skills/doc-updater/run
cat docs/pending-doc-updates.md
```

Point it at a missing binary to exercise the degrade path, or at a script that `exit 1`s to
exercise the failure path. Restore with `mv config/bridge.json.bak config/bridge.json`.

**Level 3 — the whole pipeline, still no git.** Fake the hook environment and run
orchestration directly:

```sh
HOOK_EVENT=pre-push HOOK_BRANCH=$(git rev-parse --abbrev-ref HEAD) \
HOOK_FILES="src/run_records.py
src/route_workflows.py" \
HOOK_COMMITS="348a98f0000000000000000000000000000000aa" \
sh scripts/orchestrate.sh
echo "exit=$?"                       # 0 = proceed, 10 = a block rule matched
python3 src/run_records.py show --last
```

**Level 4 — a real push, to a throwaway remote.** Never test hooks against your real
remote:

```sh
git init --bare -q /tmp/scratch-remote.git
git remote add scratch /tmp/scratch-remote.git
git checkout -b hook-test && echo "def demo(): return 1" > src/demo_touch.py
git add src/demo_touch.py && git commit -m "demo: touch a code file" src/demo_touch.py
git push scratch hook-test
python3 src/run_records.py show --last
```

Cleanup: `git checkout -; git branch -D hook-test; git remote remove scratch; rm -rf /tmp/scratch-remote.git src/demo_touch.py`.

> `git push --dry-run` also fires the hook and writes a run record — a useful way to
> re-trigger the pipeline without moving any refs.

**Level 5 — prove the block path.** Set `"on_failure": "block"` and make the bridge fail
(a stub `claude` that exits 1):

```text
[hook blocked] skill 'doc-updater': exit 1: [doc-updater] bridge error: claude exited 1: session limit reached
[hook blocked] git operation aborted by outcome rule
error: failed to push some refs to '/tmp/scratch-remote.git'
```

```text
outcome  BLOCK

- doc-updater: failure (91ms) -> block  [rule: {"on_failure": "block"}]
    rule outcomes.doc-updater.on_failure=block matched status 'failure'
```

The push exits 1 and nothing is transferred.

### 3.5 Two things that will bite this skill

**The hook's 5-second watchdog outranks every other budget.** `_run_with_timeout` in
[`scripts/lib.sh`](scripts/lib.sh) caps orchestration at 5 s, while the executor default is
30 s, this manifest asks for 90 s, and `config/bridge.json` allows 120 s. A real Claude call
loses that race:

```text
orchestration exit=143      # SIGTERM from the watchdog
records written: 0          # the record is written after execution, so there is none
[hook warning] orchestration failed (exit 143)
```

The hook then exits 0 and **the push proceeds** — with no record, and with the block rule
never consulted, because the skill never finished. A Claude-backed skill therefore needs
that cap raised in `scripts/lib.sh` (and the executor/bridge timeouts kept below the new
value), or its work moved off the hook's critical path.

**On `pre-push` the commits already exist.** Files the skill writes land as *unstaged*
working-tree changes; they are not part of the push. That is fine for a proposal file, but
if you want the docs themselves to travel with the change, route the skill on `pre-commit`,
where its output can still be staged into the commit. Related: `git rev-list --not --remotes`
means pushing a branch whose commits another remote already has yields an *empty* change
set — expected, and visible as `files=0 commits=0` in the run record.

## 4. Where to go next

**Call Claude Code from a skill.** Section 3 does this the long way; the short version is
one pipe — no Claude-specific code in your skill:

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

## 5. How this project is developed

Development is **spec-driven** (GitHub Spec Kit, `.specify/`) and **test-first**. Nothing
is written directly into `src/` — every feature walks the same pipeline, one numbered
feature at a time.

### The loop, per feature

```text
constitution ─→ specify ─→ clarify ─→ plan ─→ tasks ─→ implement (TDD) ─→ docs sync
  (project law)  spec.md   Q&A into   plan.md  tasks.md  test → fail →     CLAUDE.md +
                           the spec   + data-  (checklist  code → pass      contract
                                      model +   of steps)   → commit        addenda
                                      contracts
```

1. **Branch first.** Each feature gets a sequentially numbered branch — `001-installer-setup`
   … `008-run-observability` — and a matching `specs/00N-<slug>/` directory. Branch name,
   spec directory, and commit scope always agree.
2. **Spec (`spec.md`).** Written in user-story form with priorities (P1/P2/…), acceptance
   scenarios in Given/When/Then, functional requirements (`FR-00N`), and measurable success
   criteria (`SC-00N`). No implementation detail — it describes behavior only. Those IDs are
   then cited by the plan, the tasks, the tests, and the code comments, so any line of code
   traces back to a requirement.
3. **Plan (`plan.md`).** Chooses the technical approach and records a **Constitution Check**
   table: every relevant principle from `.specify/memory/constitution.md` is asserted PASS
   with a note, or the plan is revised. A plan that changes an earlier feature's guarantees
   (008 made hooks able to exit non-zero, which 002 had forbidden) must call that out as a
   *deliberate contract change* and land a documented addendum.
4. **Contracts (`specs/00N-*/contracts/*.md`).** Before code: the exact schemas and CLI
   surfaces the feature exposes — the stable interface other features are allowed to depend
   on. Every schema carries a version (`hook-context@1.0`, `skill-result@1.0`,
   `execution-summary@1.0`, `bridge-request/result@1.0`, `run-record@1.0`, routes `1.1`,
   skill contract `1.1`). Changes are additive; a breaking change bumps the version.
5. **Tasks (`tasks.md`).** The plan cut into numbered tasks, each naming the files it
   touches and the interfaces it produces. Every task is the same five-step checklist:
   **① write failing tests → ② verify they fail → ③ implement → ④ verify they pass →
   ⑤ commit** with a pre-written message. Ticked boxes in `tasks.md` are the progress record.
6. **Implement (TDD, strictly).** Tests are written from the acceptance scenarios and success
   criteria, and are run red before any implementation exists. Implementation is the minimum
   that turns them green.
7. **Docs sync.** Each feature closes with a `docs(00N):` commit that updates `CLAUDE.md`
   (Active Technologies + Recent Changes) and any contract addenda, so the next session starts
   with accurate context.

### Conventions that hold everywhere

| Convention | Rule |
|---|---|
| Commits | Conventional Commits, scoped by feature number: `feat(006): skill executor engine…`, `docs(008): contract addenda…` |
| Language | Python 3.10+ **stdlib only** at runtime; POSIX `sh` (`#!/bin/sh`, no bash-isms) for hooks |
| Dev tooling | `pytest` + `ruff` in a throwaway `.venv` — never a runtime dependency |
| Exit codes | Every pipeline component exits **0**, even on bad input. Exit **10** is the single reserved "a block rule matched" signal (008) |
| I/O | Components are CLIs that speak JSON on stdin/stdout and warnings on stderr, so each is testable and runnable in isolation |
| Composition | Small scripts, one responsibility each; logic lives in versioned files, never inline in hook config |

The design rules behind those conventions are project law in
`.specify/memory/constitution.md` (16 principles — incremental change sets only, git as the
change authority, bounded Claude context, spec before automation, safe by default,
structured I/O, idempotency, observable execution). Specs and plans must demonstrate
compliance before implementation starts; when a convenience conflicts with the
constitution, the constitution wins.

### Working on it yourself

```sh
git checkout -b 009-my-feature          # branch = spec dir = commit scope
mkdir -p specs/009-my-feature/contracts # spec.md, plan.md, tasks.md, contracts/ live here
uv venv .venv && uv pip install -p .venv/bin/python pytest ruff
.venv/bin/pytest tests/ -q              # red first, then implement
.venv/bin/ruff check src/
```

## 6. Component reference

Eight features, each self-contained, each with its own spec directory, contract, and test
file. The runtime pipeline is: **hooks → parser → router → executor → skills (→ bridge) →
run records**.

| # | Component | Files | Role |
|---|---|---|---|
| 001 | Installer | `install.py` | Validate prerequisites, wire up git hooks |
| 002 | Git hooks | `.githooks/*`, `scripts/*.sh` | Capture the event, delegate, never break git |
| 003 | Context parser | `src/parse_context.py` | Raw env → normalized JSON context |
| 004 | Router | `src/route_workflows.py`, `config/routes.json` | Event → execution plan |
| 005 | Skill contract & registry | `src/skill_registry.py`, `skills/registry.json` | Validate and catalog skills |
| 006 | Executor | `src/execute_skills.py` | Run skills, isolated and time-bounded |
| 007 | Claude bridge | `src/claude_bridge.py`, `config/bridge.json` | Single bounded entry point to Claude Code |
| 008 | Observability & outcomes | `src/run_records.py`, `logs/runs/` | Record every run, enforce block/warn/skip |

### 001 — Installer (`install.py`)

Stdlib-only, run once from anywhere inside the target repo. Guards the Python version before
any other import, checks prerequisites (git, Python 3.10+, uv, optionally the `claude` CLI),
creates required directories, points `git config core.hooksPath` at the versioned
`.githooks/`, and marks the hook scripts executable. No daemon, no background process — the
whole install is git configuration.

### 002 — Git hook scripts (`.githooks/`, `scripts/`)

Two layers, deliberately: `.githooks/<event>` is a two-line shim that `exec`s
`scripts/<event>.sh`, so the versioned logic can change without re-installing.

- `scripts/pre-commit.sh` — exports `HOOK_EVENT`, `HOOK_BRANCH`, `HOOK_FILES`
  (`git diff --cached --name-only --diff-filter=ACM`); skips merge commits, which `post-merge`
  covers.
- `scripts/post-merge.sh` — files from `ORIG_HEAD..HEAD`.
- `scripts/pre-push.sh` — reads git's ref lines on stdin, resolves the pushed revision range
  (handling the all-zeros new-branch case), and exports both `HOOK_COMMITS` and the union of
  files across those commits.
- `scripts/lib.sh` — shared helpers, sourced not executed: `_run_with_timeout` (5 s;
  `timeout`/`gtimeout`, falling back to a POSIX watchdog subshell) and `_finish_hook`, which
  implements the exit-code protocol — **10 → abort the git operation** with
  `[hook blocked]`; any other non-zero → `[hook warning]` and exit 0.
- `scripts/orchestrate.sh` — the 8-line entry point: `parse_context.py | route_workflows.py`.

Invariant: a broken, missing, or slow orchestration can only ever *warn*.

### 003 — Hook context parser (`src/parse_context.py`)

Turns the hook environment into one uniform JSON document (`context-schema.md`, v1.0),
identical in shape for all three events. Absolute paths are made repo-relative and paths
escaping the repo are dropped; commit SHAs are validated (40/64 hex); duplicates removed and
sorted. Anything it cannot determine becomes an explicit **partial** context with
unavailability markers rather than a silent omission. Always exits 0.

### 004 — Workflow router (`src/route_workflows.py`, `config/routes.json`)

Reads the context on stdin, re-reads `config/routes.json` **fresh on every invocation** (so
editing routes takes effect on the next commit, no reinstall), builds the execution plan for
that event, and hands it to the executor. Emits a `DispatchResult` v1.2 on stdout embedding
the ExecutionSummary, appends one line per event to `logs/hooks.log`, and applies the 008
outcome evaluation. Config loading is tolerant: a malformed or missing file degrades to an
empty routing table plus a warning. Exits 0 — except exit 10 when a block rule matched.

### 005 — Skill contract & registry (`src/skill_registry.py`, `skills/registry.json`)

The contract (`specs/005-skill-contract/contracts/skill-contract.md`, v1.1) defines what a
skill is: a directory with `skill.json` (name, semver, description, `input:
hook-context@1.0`, `output: skill-result@1.0`, behaviors, optional `time_budget_seconds`) and
an executable `run`. `skill_registry.py` validates manifests — name pattern, reserved names,
semver, required schema versions, budget ceiling of 600 s — and reports **all** violations in
one pass rather than the first. CLI: `register` / `deregister` / `resolve` / `list` /
`validate`. The router resolves identifiers only through `skills/registry.json`.

### 006 — Skill executor (`src/execute_skills.py`)

Runs the ordered plan. Each skill receives the unmodified context JSON on stdin, in its own
subprocess, under a time budget (default 30 s, per-skill override up to 600 s). Failures are
isolated — one skill crashing, timing out, or being unresolvable never stops the rest. Every
skill lands in one of four statuses: `success` / `failure` / `timeout` / `skipped`, with a
duration and a diagnostic detail. Produces an `execution-summary@1.0` and always exits 0.

### 007 — Claude Code bridge (`src/claude_bridge.py`, `config/bridge.json`)

The only place that knows how to call Claude. A skill pipes a `BridgeRequest`
(`{schema_version, context, task}`); the bridge builds a prompt **bounded to the changed
files** — with an explicit instruction not to enumerate the rest of the repository
(constitution principle 3) — runs `claude -p --output-format json` headless in the current
directory so the project's own `.claude/settings.json` and `CLAUDE.md` apply, and returns a
`BridgeResult`: `ok` / `error` / `timeout` / `unavailable`. Config: `claude_command`,
`max_turns` (4), `timeout_seconds` (120), `hooks_enabled` (false — prevents recursive hook
triggering), `extra_args`. Always exits 0; the calling skill decides its own outcome.

### 008 — Run observability & outcome enforcement (`src/run_records.py`, `logs/runs/`)

Three jobs in one module:

- **Evaluate.** Each skill result is mapped to an outcome against
  `routes.json → outcomes.<skill>.on_failure`. Default is **warn** (safe by default); `block`
  is opt-in per skill; an invalid rule degrades to warn with a note. The run's final outcome
  is the strongest of them (`block > warn > none`). Only `pre-commit` and `pre-push` can
  block — a block on `post-merge` is downgraded (the merge already happened) and flagged
  `block_downgraded`.
- **Record.** Every run — including empty plans — writes `logs/runs/<timestamp>-<event>.json`
  (`run-record@1.0`) with event, branch, timestamp, per-skill status/duration/rule/outcome/
  reason, and the final outcome. Writes are best-effort and gitignored: an unwritable
  directory returns `None` rather than raising, so observability can never affect the git
  operation. Retention (default 50) prunes oldest first.
- **Report.** CLI `list [--limit N]` (one line per run, newest first) and `show <id>|--last`
  (full render with reasons).

### Tests (`tests/`)

One pytest file per component, ~1,400 lines total, written before the code they cover:
`test_parse_context.py`, `test_route_workflows.py`, `test_skill_registry.py`,
`test_execute_skills.py`, `test_claude_bridge.py`, `test_run_records.py`. They assert against
the contracts and the numbered acceptance criteria, not against implementation details — so
a component can be rewritten as long as its contract holds.
