# Research: Declarative AI Skills with Sandboxed `_aioutput/` Results

**Branch**: `009-aioutput-skills` | **Date**: 2026-10-02

## R1 — How Claude is confined

**Decision**: Every bridge invocation adds the following, and nothing configurable can
remove them:

```text
--restricted --tools Read,Grep,Glob --strict-mcp-config
--permission-prompts none --settings {"disableAllHooks": true}
--json-schema <verdict schema>
```

**Rationale** (from `claude --help`, CLI 2.1.287):

- `--restricted` removes Bash, PowerShell, REPL, the other code-running tools and
  WebFetch. It ignores the user/project/local settings files and confines file tools to
  the working directory.
- `--tools` is the allowlist of built-in tools that exist in the session. A tool that
  isn't listed cannot be called, whatever the permission rules say.
- `--strict-mcp-config` with no `--mcp-config` means no MCP servers, so no write-capable
  MCP tools.
- `--permission-prompts none` auto-denies anything that would prompt; nobody is there to
  answer in a hook.

The layers are independent: the tool allowlist alone already removes every write path.

**Alternatives rejected**:

- *Give Claude `Write` restricted by a permission rule to `_aioutput/**`.* Correctness then
  hinges on rule-path syntax and on how settings sources merge, and still needs a
  before/after diff as a backstop. The user chose "framework writes it" (2026-10-02).
- *An OS sandbox (container, separate user).* Strongest, but not portable across Windows,
  macOS and Linux with stdlib only.

**Residual risk, stated plainly**: this relies on the Claude CLI honoring its own flags.
Managed (enterprise) settings still apply under `--restricted`. They cannot add tools that
`--tools` excluded, but that is verified, not assumed: **T0 spike** + SC-001 adversarial
E2E.

**To verify in T0** (live, before coding):

- (a) The session's tool list under these flags really is only Read/Grep/Glob.
- (b) A prompt asking to write/edit/run gets no tool and changes nothing.
- (c) Whether `CLAUDE.md` is still loaded under `--restricted`. Not required either way;
  record the answer.
- (d) That passing the JSON schema as an argv element works on Windows (`claude.exe`
  directly, not via a `.cmd` shim).

## R2 — Structured verdict

**Decision**: `--json-schema` with:

```json
{"type": "object",
 "properties": {
   "verdict": {"type": "string", "enum": ["pass", "fail"]},
   "reason":  {"type": "string"},
   "report":  {"type": "string"}},
 "required": ["verdict", "reason", "report"]}
```

The bridge reads it from the `--output-format json` payload. The exact field name is to be
confirmed in T0 (expected: `structured_output`). If it is absent, the fallback is to parse
`result` as JSON.

**Rationale**: the CLI validates the shape itself, so there is no fragile
"last line says VERDICT:" convention. A missing or invalid object maps to status `error`,
which never blocks.

## R3 — Detached async dispatch

**Decision**: the router writes a job file `logs/async/<run-id>.json` (context + async plan
+ config snapshot), then starts `[sys.executable, src/async_worker.py, <job>]` with:

- **POSIX**: `start_new_session=True`, stdin/stdout/stderr → `/dev/null`, with the worker
  logging to `logs/hooks.log` itself.
- **Windows**: `creationflags=DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP |
  CREATE_NO_WINDOW`, with the same stdio.

The router does not wait. One worker per run runs its async skills sequentially.

**Rationale**:

- A job file avoids holding a stdin pipe across a detached boundary, which is unreliable on
  Windows.
- `sys.executable` reuses the interpreter `orchestrate.sh` already probed, so the Store
  stub never comes into play.
- Sequential execution within a worker avoids N simultaneous Claude sessions per commit.
- An earlier manual experiment on this machine showed a background Claude process outliving
  the hook (the executor returned in ~1 s, and Claude finished at 13–17 s). T0 re-verifies
  this with the real `_run_with_timeout` watchdog, which on Git Bash kills by PID, not by
  process group.

**Alternatives rejected**:

- *Shell-level `nohup … &` (roadmap 010 `_run_detached`)*: the shell cannot know which
  skills are async without starting Python first.
- *One worker per skill*: more parallelism, but unbounded concurrent Claude sessions.

## R4 — No single-flight lock

**Decision**: no lock (unlike roadmap 010 §5.3).

**Rationale**: the lock existed to stop two Claude processes interleaving edits to the same
project file. Claude now edits nothing, and every result goes to a fresh, uniquely named
file written atomically, so concurrent runs cannot corrupt each other.

## R5 — Sync time ceiling

**Decision**:

- `scripts/lib.sh` keeps a hard backstop, `HOOK_CEILING_SECONDS=610`: the 600 s maximum
  sync ceiling plus a 10 s margin.
- The real bound is enforced in Python. `routes.json` `sync_ceiling_seconds` (default 120,
  1–600) caps the sum of sync execution. Each sync skill gets
  `min(its budget, remaining ceiling)`, and skills with no time left are `timeout` without
  starting.

**Rationale**: the shell cannot read JSON without a second interpreter start on every git
operation. Python sees both the manifest budgets and the ceiling.

**Trade-off, stated**: a hang *outside* skill execution (e.g. a stuck `git` call in
`parse_context.py`) is now bounded at 610 s instead of 5 s. That is accepted: those paths
are local git plumbing, while the alternative (a fixed 5 s) makes sync Claude skills
impossible.

## R6 — Outcome semantics change (008)

**Decision**: block/warn/skip rules apply only to status `failure`, which now means
"Claude ran and returned verdict `fail`". The new status `error` (Claude unavailable,
crashed, invalid structured output) and `timeout` are always `warn`, logged and never
blocking. `skipped` keeps the `on_failure` rule but cannot be `block`; it is downgraded
with a reason.

**Rationale**: constitution 6. Before, a block-ruled skill that timed out blocked the
commit, so an Anthropic outage could stop every commit in the repo. Blocking must express
a judgment about the change, never infrastructure health.

## R7 — Terminal silence

**Decision**: the router prints only `[hook blocked] …` lines to stderr. `[router
warning]` lines move to `logs/hooks.log`. `orchestrate.sh` already discards stdout.

**Rationale**: the user asked for skills to "not report anything back". The single
exception is the block, which the developer must understand to proceed. The "visible
warn" of 008 FR-007 is relaxed; the record + log satisfy constitution 14.

## R8 — History files vs. constitution 13 (idempotence)

**Decision**: one new file per run, plus retention. This is a justified deviation (see
plan → Complexity Tracking).

**Rationale**: the user chose history. The files are gitignored outputs, not repository
changes, so they never compound in commits. Retention bounds them on disk.

## T0 spike results (2026-10-02, Windows 11, Git Bash, claude 2.1.287)

| Check | Result |
|-------|--------|
| (a) tool list under the confinement flags | exactly `Glob, Grep, Read` + the CLI's internal `StructuredOutput` ✅ |
| (b) adversarial prompt (append to README, create file, `git commit`, delete) | all four impossible; `git status` clean, README unchanged, no new commit — **despite** a project `.claude/settings.json` allowing `Bash`/`Write`/`Edit` (ignored by `--restricted`) ✅ |
| (c) structured-output field | `structured_output` (object); `result` carries the same JSON as a string; `subtype: success` |
| (d) CLAUDE.md under `--restricted` | **not loaded** — prompts must be self-contained (documented in the skill contract) |
| (e) schema argv on Windows | works with `claude.exe` invoked directly |
| (f) detached child from inside `_run_with_timeout` | dispatch 9 ms; hook returned immediately; child finished 8 s later ✅ |

Extra finding: the CLI emits UTF-8; Python's locale default on Windows (cp1252) produces
mojibake. The bridge MUST decode subprocess output as UTF-8 explicitly.
