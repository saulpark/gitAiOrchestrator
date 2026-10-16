# gitAiOrchestrator — Tutorial

gitAiOrchestrator turns git events (commit, merge, push) into automated,
Claude-Code-powered checks. Thin git hooks capture what changed, a router matches the
event against `config/routes.json`, and for each routed **skill** (a prompt you write in
markdown) Claude Code runs **read-only**, focused on the changed files but able to read
the whole repository. The framework writes its report to `_aioutput/<skill>/`, and every
run is recorded. Each skill runs **sync** (the git operation waits and may be blocked) or
**async** (detached; git never waits).

```text
git commit ─→ pre-commit hook ─→ parse context ─→ route ─→ skills (Claude, read-only) ─→ _aioutput/ + outcome
                (thin, POSIX sh)   (JSON, 003)    (004)     (005/006/007, 009)             (008)
```

## 1. Installation

### Prerequisites

| Tool | Version | Notes |
|------|---------|-------|
| git | ≥ 2.28 | required |
| Python | ≥ 3.10 | runs the pipeline (stdlib only — no packages needed) |
| [uv](https://docs.astral.sh/uv/) | any | checked by the installer; used for dev tooling |
| [Claude Code CLI](https://claude.ai/code) | ≥ 2.1.287 | runs every skill. Must be installed **and authenticated for the hooks** (see below) — the installer checks both |

### Install

```sh
git clone https://github.com/saulpark/gitAiOrchestrator.git
cd gitAiOrchestrator
python3 install.py
```

The installer validates the prerequisites, checks that Claude can run the way the hooks
run it (one tiny confined call, about a cent), points `git config core.hooksPath` at the
versioned `.githooks/` directory, and ensures the hook scripts are executable. That's it —
no daemons, no services. If anything fails, nothing is changed and the installer says
what to fix.

Offline or in CI, skip the live Claude call with `python3 install.py --skip-claude-check`.
Skills will then fail (logged in `logs/hooks.log`, never blocking git) until Claude works.

### Claude authentication for the hooks

Skills run Claude with `--restricted`, which **ignores `~/.claude/settings.json`**, including
its `env` block. This is deliberate: no settings file can widen Claude's tools. The side
effect is that if your provider is configured *only* in that file, `claude auth status`
says you are logged in while every skill fails with `Not logged in`. The fix is to set
the necessary variables as **real environment variables**, so that git, and therefore
the hooks, inherit them.

What you need depends on how you sign in. Set only the row that applies to you:

| You use | Set these environment variables |
|---------|---------------------------------|
| Claude subscription (`/login`) | nothing; the stored login works under `--restricted` |
| Anthropic API key | `ANTHROPIC_API_KEY` |
| Amazon Bedrock | `CLAUDE_CODE_USE_BEDROCK=1`, plus your AWS credentials: `AWS_PROFILE` (or `AWS_BEARER_TOKEN_BEDROCK`, or access keys). Add `AWS_REGION` only if your AWS profile has no region |
| Google Vertex AI | `CLAUDE_CODE_USE_VERTEX=1`, `CLOUD_ML_REGION`, `ANTHROPIC_VERTEX_PROJECT_ID` (credentials from `gcloud auth application-default login`) |
| Microsoft Foundry | `CLAUDE_CODE_USE_FOUNDRY=1`, `ANTHROPIC_FOUNDRY_RESOURCE`, `ANTHROPIC_FOUNDRY_API_KEY` (unless you use Entra ID), and the model pins `ANTHROPIC_DEFAULT_SONNET_MODEL` / `_OPUS_MODEL` / `_HAIKU_MODEL` |
| An LLM gateway | `ANTHROPIC_BASE_URL`, `ANTHROPIC_AUTH_TOKEN` |
| …behind a corporate proxy (any of the above) | `HTTPS_PROXY` and, if your proxy re-signs TLS, `NODE_EXTRA_CA_CERTS` |

The installer tells you exactly which of these names are set in your settings file but
missing from your environment. It prints names only, never values. Use the same values
as in `~/.claude/settings.json`.

- **Windows (PowerShell)**, once per variable, then open a new terminal or IDE:
  `[Environment]::SetEnvironmentVariable('CLAUDE_CODE_USE_BEDROCK', '1', 'User')`
- **macOS / Linux**: add `export CLAUDE_CODE_USE_BEDROCK=1` (and the others) to
  `~/.profile` or your shell's rc file, then log in again.

Prefer an AWS profile (`~/.aws/credentials`) plus `AWS_PROFILE` over putting secret keys
in environment variables, since every program you run can read those. Settings keys that
produce credentials (`apiKeyHelper`, `awsAuthRefresh`, `awsCredentialExport`) are never
run by the hooks. If you rely on one, switch to an environment-based credential.

Run the installer from a **normal terminal**, not from inside a Claude Code session. A
session passes its own variables to everything it starts, so the check could pass there
and still fail on your real commits. The installer warns when it detects this.

### On Windows

Run the commands from Git Bash, and use `python` (or `py -3`) wherever this tutorial
says `python3`: on Windows `python3` is usually the Microsoft Store stub. The hooks find
a working interpreter on their own (`python3`, then `python`, then `py -3`), and the
installer aborts if none works. Skills are prompts, not programs, so there is nothing
platform-specific about writing one.

### Verify it works

```sh
git commit --allow-empty -m "test: hook smoke test"
tail -3 logs/hooks.log
git reset --soft HEAD~1      # discard the test commit
```

The hook fired and your commit was untouched. The log shows a `route event=pre-commit …`
line. This repository ships with one skill, `file-counter`, routed **async** on
`pre-commit` (`config/routes.json`), so the line reports one dispatched skill and a
detached worker counts the repository's files in the background. That is one real Claude
run (a few minutes, a few tens of cents on a large repository). Its report lands in
`_aioutput/file-counter/`. To make the system invisible until you add your own skill,
empty `routes.pre-commit` in `config/routes.json`.

### If a skill fails

Failures never block git; they are logged. Look at the newest warning:

```sh
tail -20 logs/hooks.log
python3 src/run_records.py show --last
```

| Message | Meaning |
|---------|---------|
| `Not logged in` | the hooks cannot authenticate: set the provider variables from "Claude authentication for the hooks" above and re-run `python3 install.py` from a normal terminal |
| `unavailable` / CLI too old | `claude` is missing or older than 2.1.287: upgrade it |
| `timeout` | the skill needed more than its `time_budget_seconds` (max 600) |
| credentials expired (Bedrock/SSO) | refresh them yourself, e.g. `aws sso login`; the hooks never run `awsAuthRefresh` |

## 2. Your first skill

A skill is a directory under `skills/` with exactly two kinds of file: a `skill.json`
manifest and a `prompt.md` with the task for Claude. Extra `*.md` files are allowed (notes,
examples); **any other file — a script, a binary, anything executable — makes the skill
invalid**. Skills contain no code; the framework is the only thing that runs. The full
contract is `specs/009-aioutput-skills/contracts/skill-contract.md` (v2.0).

### Create it

```sh
mkdir -p skills/todo-check

cat > skills/todo-check/skill.json <<'EOF'
{
  "name": "todo-check",
  "version": "1.0.0",
  "description": "Fails the commit if a changed file contains TODO-BLOCK",
  "input": "hook-context@1.0",
  "time_budget_seconds": 60
}
EOF

cat > skills/todo-check/prompt.md <<'EOF'
Check each changed file for the marker `TODO-BLOCK`.

The verdict is `fail` if any changed file contains it, otherwise `pass`.
In the report, list every occurrence as `path:line`, or say that none was found.
EOF
```

You never ask Claude to write anything. The framework adds the changed files and commits
to your prompt as the run's focus (Claude may still read any file in the repository), tells Claude it only has read-only tools, and asks for a structured answer:
a `verdict` (`pass`/`fail`), a one-line `reason`, and a markdown `report`. Say in your prompt
what makes the verdict `fail` — that is the only thing a block rule ever reacts to.

### Register and route it

```sh
python3 src/skill_registry.py register skills/todo-check
python3 src/skill_registry.py list
# → todo-check 1.0.0 — Fails the commit if a changed file contains TODO-BLOCK
```

Then map it to the pre-commit event in `config/routes.json`, and choose its mode:

```json
{
  "version": "2.0",
  "routes": {
    "pre-commit": ["todo-check"],
    "post-merge": [],
    "pre-push": []
  },
  "skills": {
    "todo-check": {"mode": "sync", "on_failure": "block"}
  },
  "sync_ceiling_seconds": 120,
  "run_retention": 50,
  "output_retention": 50
}
```

Both files are re-read on every git event — no reinstall, no restart.

### Run it

```sh
printf 'x = 1  # TODO-BLOCK\n' > demo.py && git add demo.py
git commit -m "feat: demo"
```

```text
[hook blocked] skill 'todo-check': demo.py contains TODO-BLOCK (see _aioutput/todo-check/20261002T101530Z-pre-commit.md)
[hook blocked] git operation aborted by outcome rule
```

The full report is in that file, under a provenance header:

```markdown
---
skill: "todo-check"
skill_version: "1.0.0"
event: "pre-commit"
branch: "master"
mode: "sync"
verdict: "fail"
reason: "demo.py contains TODO-BLOCK"
run_id: "20261002T101530.123456Z-pre-commit"
timestamp: "2026-10-02T10:15:30Z"
files:
  - "demo.py"
---

- demo.py:1 — `x = 1  # TODO-BLOCK`
```

Remove the marker and commit again: the verdict is `pass`, the commit goes through, and
nothing at all is printed. `python3 src/run_records.py show --last` shows what ran and why.

## 3. Choosing a mode

| | `sync` | `async` (default) |
|---|---|---|
| When it runs | inside the hook; git waits | in a detached worker; the hook returns in milliseconds |
| Time bound | `min(time_budget_seconds, time left in sync_ceiling_seconds)` | its own `time_budget_seconds` |
| Can block git | yes — only on `verdict: fail`, only with `on_failure: block`, only on `pre-commit`/`pre-push` | never (a `block` rule is ignored, with a config warning) |
| Result | `_aioutput/<skill>/…` before git continues | `_aioutput/<skill>/…` a little later |
| Run record | `logs/runs/<id>.json` | `logs/runs/<id>-async.json`, with `parent_run` |

Rules of thumb:

- **Use `sync` only for gates** — checks whose `fail` must stop the commit or push. Every
  sync skill adds a Claude call to the developer's wait. All sync skills of one event
  together get `sync_ceiling_seconds` (default 120, max 600); whatever runs out of time ends
  as `timeout`, without a call.
- **Use `async` for everything else** — reviews, summaries, documentation proposals. Read
  the result in `_aioutput/` when you want it.
- **Only Claude's judgment can block.** A missing or outdated `claude` CLI, a timeout, an
  unparseable answer, or an unwritable `_aioutput/` ends the skill as `error` or `timeout`,
  which is logged and never blocks — even with `on_failure: block`.

`on_failure` values: `block` (above), `warn` (the default: logged to `logs/hooks.log` and
the run record), `skip` (recorded, nothing logged as a warning).

## 4. What Claude can and cannot do

Every skill call runs the Claude CLI with a fixed, non-configurable confinement:

```text
claude -p --output-format json --max-turns N
       --restricted --tools Read,Grep,Glob --strict-mcp-config
       --permission-prompts none --settings {"disableAllHooks": true}
       --json-schema <verdict schema>
```

- **Read-only tools only** (`Read`, `Grep`, `Glob`). No `Write`, `Edit` or `Bash`, no MCP
  servers, no permission prompts, no nested hooks. Claude cannot modify the project; the
  framework writes the only file that results from a run.
- **Your project settings do not widen this.** `--restricted` ignores the project's
  `.claude/settings.json` allow rules and does not load `CLAUDE.md`. Put everything the
  skill needs to know into `prompt.md`.
- **Whole-repository reads, change-set focus (010).** The prompt lists the changed files
  and commits as the focus of the run and tells Claude it may read any file inside the
  repository. Claude runs with the repo root as its working directory, and per the CLI
  docs `--restricted` confines its file tools to that directory. Exclusions (e.g.
  `.git/`, build output) are your prompt's job.
- **Secrets are readable.** Gitignored files (`.env`, local credentials, `logs/`) are not
  hidden from Claude. It cannot change them, but it can quote them into the report in
  `_aioutput/` (gitignored, yet plain text on disk). Tell a skill not to quote secrets if
  that matters.
- `config/bridge.json` accepts only `claude_command`, `model`, `max_turns` and
  `timeout_seconds`. The old `hooks_enabled` and `extra_args` keys are ignored with a
  warning — there is no way to pass extra CLI flags.

### Where everything goes

| What | Where | Committed? |
|---|---|---|
| Skill reports | `_aioutput/<skill>/<UTC stamp>-<event>[-N].md`, newest `output_retention` kept | no — gitignored |
| Run records | `logs/runs/<id>.json` (`<id>-async.json` for async) | no |
| Warnings, one line per routed event, one per async skill | `logs/hooks.log` | no |
| Terminal output | only `[hook blocked] …` lines | — |

### Testing a skill

**Level 1 — run it by hand, sync, no git.** The executor CLI runs any plan synchronously
and prints the summary, including the path of the result file:

```sh
echo '{"schema_version":"1.0","event":"pre-commit","branch":"demo","files":["demo.py"],
       "commits":[],"partial":false,"unavailable":[],"errors":[]}' \
  | python3 src/execute_skills.py todo-check
```

**Level 2 — the whole pipeline, still no git.** Fake the hook environment:

```sh
HOOK_EVENT=pre-commit HOOK_BRANCH=$(git rev-parse --abbrev-ref HEAD) HOOK_FILES="demo.py" \
sh scripts/orchestrate.sh
echo "exit=$?"                       # 0 = proceed, 10 = a sync block rule matched
python3 src/run_records.py show --last
```

**Level 3 — a real commit or push**, ideally to a throwaway remote
(`git init --bare /tmp/scratch-remote.git`). `git push --dry-run` also fires the pre-push
hook without moving any refs.

**Useful commands:**

```sh
python3 src/skill_registry.py list          # registered skills
python3 src/skill_registry.py validate      # re-check all skills against the contract
python3 src/run_records.py list --limit 10  # recent runs (sync and async)
ls _aioutput/*/                             # skill reports
tail -20 logs/hooks.log                     # routed events, warnings, async results
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
   … `011-installer-claude-check` — and a matching `specs/00N-<slug>/` directory. Branch name,
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
   on. Every schema carries a version (`hook-context@1.0`,
   `execution-summary@2.0`, `bridge-request/result@2.0`, `run-record@1.1`, routes `2.0`,
   skill contract `2.0`). Changes are additive; a breaking change bumps the version.
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
| Exit codes | Every pipeline component exits **0**, even on bad input. Exit **10** is the single reserved "a sync block rule matched" signal (008/009) |
| I/O | Components are CLIs that speak JSON on stdin/stdout, so each is testable and runnable in isolation. Hook-time warnings go to `logs/hooks.log`; the terminal shows only blocks |
| Composition | Small scripts, one responsibility each; logic lives in versioned files, never inline in hook config |

The design rules behind those conventions are project law in
`.specify/memory/constitution.md` (16 principles — incremental change sets only, git as the
change authority, a change-set focus for Claude (read-only, whole repo readable), spec before automation, safe by default,
structured I/O, idempotency, observable execution). Specs and plans must demonstrate
compliance before implementation starts; when a convenience conflicts with the
constitution, the constitution wins.

### Working on it yourself

```sh
git checkout -b 012-my-feature          # branch = spec dir = commit scope
mkdir -p specs/012-my-feature/contracts # spec.md, plan.md, tasks.md, contracts/ live here
uv venv .venv && uv pip install -p .venv/bin/python pytest ruff
.venv/bin/pytest tests/ -q              # red first, then implement
.venv/bin/ruff check src/
```

## 6. Component reference

Eleven features, each with its own spec directory and (mostly) a contract and test file. The runtime
pipeline is: **hooks → parser → router → executor → bridge (Claude, read-only) →
`_aioutput/` + run records**, with async skills handed to a detached worker. Feature 009
reshaped 002 and 005–008; their sections below describe the current behavior. 010 and 011
are cross-cutting changes to 007 and 001 and have no section of their own.

| # | Component | Files | Role |
|---|---|---|---|
| 001 | Installer | `install.py` | Validate prerequisites, wire up git hooks |
| 002 | Git hooks | `.githooks/*`, `scripts/*.sh` | Capture the event, delegate, never break git |
| 003 | Context parser | `src/parse_context.py` | Raw env → normalized JSON context |
| 004 | Router | `src/route_workflows.py`, `config/routes.json` | Event → plan with per-skill modes |
| 005 | Skill contract & registry | `src/skill_registry.py`, `skills/registry.json` | Validate and catalog prompt skills |
| 006 | Executor | `src/execute_skills.py`, `src/async_worker.py` | Run sync skills, dispatch async ones |
| 007 | Claude bridge | `src/claude_bridge.py`, `config/bridge.json` | Single, read-only entry point to Claude Code |
| 008 | Observability & outcomes | `src/run_records.py`, `logs/runs/` | Record every run, enforce block/warn/skip |
| 009 | Result files | `src/ai_output.py`, `_aioutput/` | Write each skill's report, with history |
| 010 | Repo-wide read context | `src/claude_bridge.py`, `src/execute_skills.py` | Claude may read the whole repo (still read-only); the change set is the focus |
| 011 | Installer Claude check | `install.py` | Abort the install unless Claude can run as the hooks run it |

### 001 — Installer (`install.py`)

Stdlib-only, run once from anywhere inside the target repo. Guards the Python version before
any other import, checks prerequisites (git, Python 3.10+, uv, and the `claude` CLI at
2.1.287 or later), creates required directories, points `git config core.hooksPath` at the
versioned `.githooks/`, and marks the hook scripts executable. No daemon, no background
process: the whole install is git configuration.

Since 011, it also checks that Claude can run the way the hooks run it. A static check
lists the provider variables that are set in `~/.claude/settings.json` but missing from the
environment, by name only. A live call uses the hooks' exact `--restricted` confinement. If
the check fails, the install aborts before changing anything and names the variables to set.
`--skip-claude-check` skips the live call. See §1, "Claude authentication for the hooks".

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
- `scripts/lib.sh` — shared helpers, sourced not executed: `_run_with_timeout`
  (`HOOK_CEILING_SECONDS=610`, a backstop above the router's sync ceiling;
  `timeout`/`gtimeout`, falling back to a POSIX watchdog subshell) and `_finish_hook`, which
  implements the exit-code protocol — **10 → abort the git operation** with
  `[hook blocked]`; any other non-zero → one line in `logs/hooks.log` and exit 0.
- `scripts/orchestrate.sh` — the entry point: `parse_context.py | route_workflows.py`.

Invariant: a broken, missing, or slow orchestration can only ever be *logged*.

### 003 — Hook context parser (`src/parse_context.py`)

Turns the hook environment into one uniform JSON document (`context-schema.md`, v1.0),
identical in shape for all three events. Absolute paths are made repo-relative and paths
escaping the repo are dropped; commit SHAs are validated (40/64 hex); duplicates removed and
sorted. Anything it cannot determine becomes an explicit **partial** context with
unavailability markers rather than a silent omission. Always exits 0.

### 004 — Workflow router (`src/route_workflows.py`, `config/routes.json`)

Reads the context on stdin, re-reads `config/routes.json` (v2.0) **fresh on every
invocation**, builds the plan for that event with each skill's mode from
`skills.<name>.mode`, and hands it to the executor. Emits a `DispatchResult` v2.0 on stdout,
appends one line per event plus one per warning to `logs/hooks.log`, and applies the 008
outcome evaluation. The terminal stays silent except for `[hook blocked]` lines. Config
loading is tolerant: a malformed or missing file degrades to an empty routing table plus a
logged warning; the v1.x `outcomes` key is still read, with a deprecation warning. Exits 0 —
except exit 10 when a sync block rule matched.

### 005 — Skill contract & registry (`src/skill_registry.py`, `skills/registry.json`)

The contract (v2.0, `specs/009-aioutput-skills/contracts/skill-contract.md`) defines a skill
as a directory with `skill.json` (name, semver, description, `input: hook-context@1.0`,
optional `time_budget_seconds` ≤ 600) and a non-empty `prompt.md`. Any file other than
`skill.json` and `*.md` — or any file with the executable bit — is a violation.
`skill_registry.py` reports **all** violations in one pass. CLI: `register` / `deregister` /
`resolve` / `list` / `validate`. The router resolves identifiers only through
`skills/registry.json`, and the executor re-validates a skill before every run.

### 006 — Skill executor (`src/execute_skills.py`, `src/async_worker.py`)

Dispatches the async part of the plan first — one job file in `logs/async/` and one detached
`async_worker.py` process, so git never waits — then runs the sync skills in order, each
under `min(budget, time left in the sync ceiling)` (default budget 60 s). Each skill is one
bridge call followed by one result file. Statuses: `success` / `failure` (verdict `fail`) /
`error` / `timeout` / `skipped` / `dispatched` / `dispatch-failed`. Failures are isolated;
the executor never raises. The worker runs its skills with full budgets, writes its own run
record and one `logs/hooks.log` line per skill, and deletes the job file.

### 007 — Claude Code bridge (`src/claude_bridge.py`, `config/bridge.json`)

The only place that knows how to call Claude. It builds a prompt **focused on the changed
files** (the whole repository is readable since 010), runs Claude in the repo root, sends
it on stdin to `claude -p` with the fixed read-only confinement (§4), and
parses the structured `{verdict, reason, report}` answer into a `bridge-result@2.0`: `ok` /
`error` / `timeout` / `unavailable` / `bad-request`. A CLI older than 2.1.287 (which lacks
the confinement flags) is `unavailable`, never run unconfined. Config: `claude_command`,
`model`, `max_turns` (20), `timeout_seconds` (120).

### 008 — Run observability & outcome enforcement (`src/run_records.py`, `logs/runs/`)

Three jobs in one module:

- **Evaluate.** Each result is mapped to an outcome against `skills.<name>.on_failure`.
  Default is **warn**; `block` applies only to a sync skill's `failure` on `pre-commit` or
  `pre-push` — anything else that asks for a block is downgraded to warn and flagged
  `block_downgraded`, with the reason. The run's final outcome is the strongest
  (`block > warn > none`).
- **Record.** Every run — including empty plans — writes `logs/runs/<id>.json`
  (`run-record@1.1`) with per-skill mode, status, verdict, output file, duration, rule,
  outcome and reason. Async workers write `<id>-async.json` with `parent_run`. Writes are
  best-effort; retention (default 50) prunes oldest first.
- **Report.** CLI `list [--limit N]` and `show <id>|--last`.

### 009 — Result files (`src/ai_output.py`, `_aioutput/`)

The framework, never Claude, writes each skill's report to
`_aioutput/<skill>/<YYYYMMDDTHHMMSSZ>-<event>[-N].md` with a JSON-valued provenance header.
Files are reserved with an exclusive create and written atomically, never overwritten, and
pruned to `output_retention` per skill. `_aioutput/` is gitignored.

### Tests (`tests/`)

One pytest file per component, written before the code they cover:
`test_install.py`, `test_parse_context.py`, `test_route_workflows.py`,
`test_skill_registry.py`, `test_execute_skills.py`, `test_async_worker.py`,
`test_claude_bridge.py`, `test_ai_output.py`, `test_run_records.py`. Claude is never called:
the bridge and the async dispatch are injected. They assert against the contracts and the
numbered acceptance criteria, not against implementation details.
