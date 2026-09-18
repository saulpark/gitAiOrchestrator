# AI-Assisted Living Documentation — Roadmap & Plan

**Status:** proposal, pending approval
**Date:** 2026-09-18
**Scope:** features 009, 010, 011
**Depends on:** 001–008 (all complete)

---

## 1. Purpose

Keep the repository's developer-facing documentation accurate and current by reacting to
git events: detect when a change set has made documentation stale, and update the affected
documentation in the working tree for the developer to review, commit, or discard.

This is the project's original stated purpose (`.specify/memory/constitution.md` §Purpose).
Features 001–008 built the machinery to do it. Nothing has used that machinery yet.

---

## 2. Progress: the existing git framework

### 2.1 What is built

Eight features, all merged to `master`, all with specs, contracts and tests.

| # | Feature | Artifacts | What it contributes to the doc agent |
|---|---------|-----------|--------------------------------------|
| 001 | Installer | `install.py` | Sets `core.hooksPath` → `.githooks/`, creates `logs/`, marks scripts executable. Prereq checks (git, python). No daemon. |
| 002 | Git hook scripts | `.githooks/{pre-commit,post-merge,pre-push}`, `scripts/{pre-commit,post-merge,pre-push,orchestrate,lib}.sh` | The three triggers. Each shim captures `HOOK_EVENT`/`HOOK_BRANCH`/`HOOK_FILES` (+`HOOK_COMMITS` on pre-push) and delegates. `lib.sh` owns the timeout and the exit-code translation. |
| 003 | Hook context parser | `src/parse_context.py`, `hook-context@1.0` | Environment → normalized context JSON. Paths repo-relative, deduped, sorted; out-of-repo paths dropped; commits validated as hex SHAs in push order; `partial`/`unavailable`/`errors` instead of exceptions. **This is the bounded change set the constitution requires.** |
| 004 | Workflow router | `src/route_workflows.py`, `config/routes.json` (v1.1) | Re-reads config on every event (no reinstall), selects the ordered plan per event, emits `DispatchResult` v1.2. Degrades any config problem to "route nothing + warning". |
| 005 | Skill contract & registry | `src/skill_registry.py`, `skills/registry.json`, skill contract v1.1 | Defines what a skill is: `skill.json` + executable `run`, `hook-context@1.0` in, `skill-result@1.0` out, `non_blocking` mandatory, optional `time_budget_seconds`. register/deregister/resolve/list/validate. |
| 006 | Skill executor | `src/execute_skills.py`, `execution-summary@1.0` | Runs the plan sequentially, per-skill time budget (default 30 s, ceiling 600 s), per-skill failure isolation, four terminal statuses (`success`/`failure`/`timeout`/`skipped`). |
| 007 | Claude Code bridge | `src/claude_bridge.py`, `config/bridge.json`, `bridge-request/result@1.0` | The only path to Claude. Builds a prompt from *the change set only* plus an explicit "do not scan the rest of the repository" constraint; runs `claude -p --output-format json --max-turns N` in the repo root so `CLAUDE.md` and `.claude/settings.json` apply; forces `disableAllHooks: true`. Returns `ok`/`bad-request`/`unavailable`/`timeout`/`error` and never raises. |
| 008 | Run observability & outcomes | `src/run_records.py`, `logs/runs/`, `run-record@1.0`, routes v1.1 `outcomes` | A record per run (context summary, plan, per-skill status/duration/rule/outcome/reason, warnings), retention pruning, `list`/`show --last` CLI. `outcomes.<skill>.on_failure: block\|warn\|skip`, default `warn`. `block` → router exit **10** → `_finish_hook` exits 1 → git aborts. `block` on `post-merge` is downgraded to `warn`. |

**Pipeline, as it actually runs today:**

```text
git event
  → .githooks/<event>                      (shim, core.hooksPath)
  → scripts/<event>.sh                     (capture HOOK_* env)
  → _run_with_timeout 5s                   (scripts/lib.sh)
      → scripts/orchestrate.sh
          → src/parse_context.py           → hook-context@1.0 (stdout)
          → src/route_workflows.py         (routes.json → plan)
              → src/execute_skills.py      (run each skill, budgeted)
                  → skills/<name>/run      → skill-result@1.0
                      → src/claude_bridge.py  (optional, bounded prompt)
              → src/run_records.py         (evaluate outcomes, write logs/runs/<id>.json)
  → _finish_hook $?                        (10 → abort git; anything else → warn, exit 0)
```

**Conventions in force:** Python 3.10+ stdlib only at runtime; POSIX `sh` (no bash-isms);
every component is a JSON-on-stdin/stdout CLI that exits 0; exit 10 is the single reserved
block signal; `pytest` + `ruff` in a throwaway `.venv`, never a runtime dependency.
Development is spec-driven via Spec Kit (`.specify/`, `speckit-*` skills) and test-first.

### 2.2 What is *not* built — the gap this roadmap closes

| Gap | Evidence | Consequence |
|---|---|---|
| **No skills exist.** | `skills/registry.json` = `{"contract_version":"1.1","skills":{}}`; `config/routes.json` routes all `[]` | Every git event today produces `dispatched=0 overall=empty`. The framework is complete and idle. |
| **The 5-second hook cap makes Claude-backed skills unrunnable.** | `_run_with_timeout` hard-codes `timeout 5`; executor default 30 s; bridge default 120 s. Documented in `TUTORIAL.md` §3.5 with the real failure: `exit=143`, `records written: 0` | The skill is SIGTERMed mid-Claude-call. No run record, block rule never consulted, git proceeds silently. **This is the single hard blocker.** |
| **Async mode is specified but not implemented.** | `002` FR-007 requires it; `specs/002-.../contracts/orchestration-interface.md` §"Asynchronous (fire-and-forget)" documents it; `lib.sh` has no such function | The escape hatch the contract promises does not exist. (Note: the contract's example uses `disown`, which is **not POSIX** — see §5.1.) |
| **No concurrency control.** | Nothing in `lib.sh`, `orchestrate.sh` or the router takes a lock | `git commit` then `git push` can fire two overlapping runs; `git pull` adds a third. Two processes editing `TUTORIAL.md` concurrently will corrupt it. |
| **No manual / on-demand entry point.** | Only `scripts/orchestrate.sh` driven by `HOOK_*` env vars | Constitution 1 permits full scans for "migration, repair, or baseline regeneration" but provides no way to request one. |
| **No documentation-target map.** | — | Nothing tells the system which docs describe which code. Without it, target selection is a model guess, which breaks constitution 5 (reproducibility) and 3 (bounded context). |
| **No `README.md`.** | `ls README*` → not found | Root documentation is `TUTORIAL.md` (631 lines) and `CLAUDE.md` only. See §4.3. |

---

## 3. Decisions taken

Confirmed with the requester on 2026-09-18.

| Decision | Choice | Constitution alignment |
|---|---|---|
| **Write mode** | Apply edits to the real docs, leave them **unstaged** in the working tree | 5 (reviewable file diffs), 6 & 10 (human boundary preserved — nothing is committed) |
| **Execution model** | **Async detached** — implement the fire-and-forget mode 002 FR-007 already specifies | 14 (observable via `logs/hooks.log` + run records); resolves the 5 s cap without adding git latency |
| **Doc targets** | Root narrative docs — `TUTORIAL.md` (and `README.md` if created). **Excluded:** `CLAUDE.md`, `specs/**`, docstrings/comments | 7 (scope rules), 8 (explicit exclusions), 4 (specs are inputs, not outputs) |
| **Triggers** | `pre-commit`, `pre-push`, `post-merge`, **and** a manual on-demand entry point | 2 (git is the change authority); manual path covers constitution 1's baseline-regeneration exception |

---

## 4. Conflicts these decisions create, and how the plan resolves them

Three of the four decisions interact badly. Each is resolved explicitly below rather than
discovered during implementation.

### 4.1 Async + `pre-commit` + unstaged edits is self-defeating

`pre-commit` is the *only* event where a doc edit can still be staged into the same commit.
Async detached execution means the hook returns immediately, git builds the commit object
from the already-written index, and the agent's writes land **after** the commit exists.
They are therefore never in it. Worse, a detached process writing tracked files while git
finalises a commit leaves the working tree diverged from `HEAD` in a way that looks like an
unexplained dirty tree.

**Resolution — split the work into two skills:**

- **`doc-drift-detector`** — deterministic, no Claude, ~50 ms. Answers *"does this change set
  touch anything the docs describe?"* using the target map. Runs **synchronously** on
  `pre-commit`, comfortably inside the 5 s cap, and can therefore legitimately `warn` or
  `block`. Its output is a message, not an edit.
- **`living-doc-agent`** — Claude-backed writer, 60–120 s. Runs **async** on `pre-push` and
  `post-merge`, and **synchronously with no cap** on the manual path.

This honours all four requested triggers and both the async decision and the
staged-edit reality. It is the hybrid model, arrived at by necessity rather than preference.
**Confirm this before implementation begins** — it is the one place the plan departs from a
literal reading of the answers given.

### 4.2 Async silently disables every `block` rule

With the hook detached, the router's exit 10 is written to a log file that nobody reads and
the hook has already exited 0. `outcomes.<skill>.on_failure: block` becomes a no-op — and,
critically, a *silent* one. That is a footgun in a safety mechanism.

**Resolution:** reuse the existing downgrade machinery. `evaluate_outcomes` already
downgrades `block` → `warn` for `post-merge` and records `block_downgraded: true` with a
reason. Add async as a second downgrade trigger with its own reason string
(`"block downgraded to warn: event 'pre-push' runs in async mode"`), and have
`skill_registry.py validate` / router config validation emit a warning when a `block` rule
is configured for an async event. Same mechanism, new cause, no new concept.

### 4.3 Async breaks a promise 008 made in writing

`specs/008-run-observability/spec.md` states:

> "Visible message" for warn and block outcomes means output to the developer's terminal at
> the time of the git operation — **not a background notification or a file they must
> separately open.**

Async is exactly the thing that sentence forbids. Per `TUTORIAL.md` §5, a plan that changes
an earlier feature's guarantees must call it out as a **deliberate contract change** and land
a documented addendum (as 008 did to 002's "hooks always exit 0" rule).

**Resolution:**

1. Land an addendum to the 008 spec/contract recording that async-mode runs report
   asynchronously, and why.
2. Preserve the *spirit* of the promise with a **deferred notification**: async run records
   are written with `reported: false`; the next *synchronous* hook invocation prints a
   one-line digest of unreported runs to stderr and flips the flag. The developer still
   learns from their terminal, one git operation later.

### 4.4 Two smaller conflicts

- **Doc targets vs. reality.** `README.md` does not exist. Either create one as a Phase 0
  task, or scope 011 to `TUTORIAL.md` alone. Recommendation: scope to `TUTORIAL.md` for 011
  and add `README.md` to the target map when it exists — the map is data, not code.
- **Recursion.** The agent edits `TUTORIAL.md`; the developer commits it; `pre-commit` fires
  on a change set consisting of `TUTORIAL.md`. Constitution 7 already answers this: only
  code/contract/schema/config/behavioural changes may trigger a doc update. A docs-only
  change set exits `skipped` before any Claude call.

---

## 5. Feature breakdown

Sequenced so that value lands before the risky work, and each feature is one
feature-sized increment matching the 001–008 cadence.

### Feature 009 — `doc-drift-detector` (first real skill)

**Why first:** it needs **no infrastructure change at all**. It is deterministic, runs in
milliseconds, fits inside the existing 5 s cap, and can block. It puts the first entry in
`skills/registry.json`, proves the whole 002→008 pipeline against a real skill, and delivers
standalone value: you learn a doc is stale at commit time.

**Scope**

- `config/doc-targets.json` (new, schema v1.0) — the deterministic code→doc map:
  ```json
  {
    "version": "1.0",
    "targets": [
      {"code": ["src/route_workflows.py", "config/routes.json"],
       "docs": ["TUTORIAL.md#004--workflow-router", "TUTORIAL.md#33-what-happens-on-git-push-component-by-component"]},
      {"code": ["src/claude_bridge.py", "config/bridge.json"],
       "docs": ["TUTORIAL.md#007--claude-code-bridge"]}
    ],
    "exclude": ["logs/**", ".venv/**", "**/__pycache__/**", "*.md"]
  }
  ```
  This map is what makes the whole system reproducible (constitution 5) and keeps Claude's
  context bounded to relevant doc sections rather than 631 lines (constitution 3).
- `skills/doc-drift-detector/{skill.json,run}` — reads `hook-context@1.0`, applies the
  exclusion list, intersects the change set with `targets[].code`, emits `skill-result@1.0`:
  `skipped` when nothing matches, `ok` with the affected doc sections in `details` when it
  does. No network, no Claude, no writes.
- Route on `pre-commit`; `outcomes` default `warn`.

**Contracts:** `specs/009-*/contracts/doc-targets.md` (map schema),
`specs/009-*/contracts/drift-report.md` (the `details` payload shape, consumed by 011).

**Key requirements to write into the spec**

- FR: MUST exit `skipped` for a change set containing no mapped code paths.
- FR: MUST exit `skipped` for a docs-only change set (recursion guard).
- FR: MUST honour `exclude` globs (constitution 8).
- FR: MUST complete within 1 s for a 500-file change set (so it never threatens the cap).
- FR: MUST handle `partial: true` context without crashing (skill contract §Input).
- FR: MUST NOT write to the working tree.
- SC: a change to `src/claude_bridge.py` names `TUTORIAL.md#007--claude-code-bridge` and
  nothing else.
- SC: an unreadable or malformed `doc-targets.json` degrades to `skipped` + warning, never
  an error (matching the router's config posture).

**Tests:** happy path (mapped code file → correct sections); docs-only skip; unmapped-code
skip; malformed map degrade; `partial` context; excluded paths ignored.

---

### Feature 010 — async orchestration mode (the unblocker)

**Scope**

#### 5.1 `scripts/lib.sh` — `_run_detached`

```sh
# Launch orchestration detached: no timeout, output to the hook log, immune to
# the caller's exit. nohup is POSIX; `disown` (used in the 002 contract example)
# is a bash builtin and absent from dash — that example must be corrected.
_run_detached() {
    nohup "$@" </dev/null >>"$(_hook_root)/logs/hooks.log" 2>&1 &
}
```

Note the correction: the 002 contract's illustrative snippet is not `#!/bin/sh`-safe. The
addendum must fix it as well as mark the mode implemented.

#### 5.2 Mode selection — `config/hooks.conf`

The shell layer decides sync vs. async *before* Python starts, so the mode cannot live in
`routes.json` without a second Python round-trip. Introduce a POSIX-sourceable fragment:

```sh
# config/hooks.conf — sourced by scripts/lib.sh. Versioned config, not inline logic (§11).
HOOK_MODE_pre_commit=sync
HOOK_MODE_pre_push=async
HOOK_MODE_post_merge=async
HOOK_SYNC_TIMEOUT=5
```

Trade-off, stated deliberately: a second config file beside `routes.json`. Justified because
the alternative is parsing JSON in POSIX `sh` or paying an extra interpreter start on every
git operation. Missing or unreadable file ⇒ default to `sync` with the current 5 s cap
(fail safe: today's behaviour).

#### 5.3 Single-flight lock

`git commit` → `git push` → `git pull` can overlap three runs; async removes the natural
serialisation. Guard with an atomic `mkdir` lock in `orchestrate.sh`:

- `mkdir logs/.orchestrate.lock` succeeds ⇒ proceed, write the pid inside, remove on exit
  (`trap`).
- Fails ⇒ log `run skipped: another orchestration is in progress (pid N)` and exit 0.
- Stale lock (pid dead, or directory older than the bridge timeout) ⇒ reclaim with a warning.

Without this, two `living-doc-agent` processes will interleave writes to `TUTORIAL.md`.

#### 5.4 Async-aware outcomes (resolves §4.2)

- `route_workflows.py --mode async` → passed through to `evaluate_outcomes`.
- `evaluate_outcomes` gains async as a second `block`→`warn` downgrade cause, with its own
  reason string; `block_downgraded` already exists in `run-record@1.0`.
- Router config validation warns when a `block` rule is configured for an event whose mode
  is `async`.

#### 5.5 Deferred notification (resolves §4.3)

- `run-record@1.0` → `1.1`: add `reported: bool`.
- `run_records.py`: `pending` (list unreported) and `mark-reported`.
- `orchestrate.sh` in **sync** mode prints a one-line digest of unreported async runs to
  stderr before dispatching, then marks them reported.

#### 5.6 Manual entry point

`src/manual_run.py` — synthesises a `hook-context@1.0` without git hooks:

```sh
python3 src/manual_run.py --event pre-push --since HEAD~3      # commit range
python3 src/manual_run.py --event pre-push --files src/foo.py  # explicit set
python3 src/manual_run.py --event pre-push --all               # baseline regeneration (§1)
```

Runs the router synchronously, no timeout, full budgets, `block` rules honoured. This is
both the on-demand trigger requested and constitution 1's sanctioned full-scan escape hatch
— `--all` is the *only* path allowed to ignore the incremental rule, and it must say so.

**Contract changes**

- `002/contracts/orchestration-interface.md` → **v1.3**: async mode implemented, POSIX
  correction, `config/hooks.conf`, lock protocol, mode-dependent exit-code semantics.
- `008/contracts/run-record.md` → **v1.1**: `reported` field, async downgrade reason.
- `008/spec.md` addendum: the terminal-visibility promise is relaxed for async events, with
  the deferred-notification mechanism as the compensating control.

**Key requirements**

- FR: async dispatch MUST add < 100 ms to the git operation.
- FR: a missing/unreadable `hooks.conf` MUST fall back to sync + 5 s (today's behaviour).
- FR: concurrent runs MUST NOT overlap; the loser exits 0 and is logged.
- FR: a `block` rule on an async event MUST be downgraded, recorded, and warned about at
  config-validation time — never silently ignored.
- FR: `--all` MUST require explicit opt-in and MUST be recorded in the run record.
- SC: a 90 s skill on `pre-push` completes and writes a run record while `git push` returns
  in under a second.
- SC: `git commit && git push` in immediate succession produces one run, not two overlapping.

**Tests:** async dispatch returns immediately and the record appears later; lock contention;
stale-lock reclaim; missing `hooks.conf` → sync fallback; async block downgrade recorded;
deferred digest printed once and only once; `manual_run.py` context synthesis from a range;
`--all` recorded.

---

### Feature 011 — `living-doc-agent` (the Claude-backed writer)

**Depends on:** 009 (target map + drift report) and 010 (async, lock, manual path).

**Scope**

`skills/living-doc-agent/{skill.json,run}`, `time_budget_seconds: 120`,
`behaviors: {non_blocking: true, idempotent: false}` — `idempotent: false` is the honest
declaration for model output, and step 5 below is what makes it *converge* anyway.

**Pipeline inside the skill**

1. **Gate** (reuse 009's logic): exclusions, docs-only guard, mapped-code intersection.
   No match ⇒ `skipped` in milliseconds, no Claude call. Never spend a model call to learn
   there was nothing to do.
2. **Bound the context** (constitution 1/3): send Claude only the changed files' diffs plus
   the *mapped doc sections* — not the whole `TUTORIAL.md`, not the repository.
3. **Ask for anchored replacements**, not free-form prose: for each mapped section, return
   either `UNCHANGED` or the full replacement body of that section.
4. **Safety check before writing** — if the target file has uncommitted modifications the
   agent did not make (`git diff --name-only` / `--cached`), do **not** edit it; fall back to
   writing `docs/pending-doc-updates.md` and report `ok` with a `deferred` detail. Clobbering
   a developer's in-progress edits is the worst thing this system could do.
5. **Write via anchored-region replacement** — copy the target aside, replace only the text
   between stable markdown heading anchors, never append. This is what makes repeated runs
   converge instead of compounding (constitution 13).
6. **Validate** (constitution 9 — mandatory, not optional):
   - every target file still exists and parses as markdown;
   - heading structure is unchanged (no headings added, removed, or renamed);
   - every relative link and file path referenced in the edited sections resolves;
   - the resulting diff is confined to the mapped sections.
7. **Roll back on any validation failure** — restore the copy, emit `error` with the failed
   check in `details`. A doc agent that leaves a corrupted `TUTORIAL.md` behind is worse than
   no doc agent.
8. **Emit `skill-result@1.0`** listing files edited, sections touched, validation results,
   and the bridge duration.

**Degradation matrix** (from the bridge's five statuses)

| Bridge status | Skill result | Rationale |
|---|---|---|
| `unavailable` (no `claude` on PATH) | `skipped` | Claude is optional tooling (007 contract) |
| `timeout` | `error` | It tried and could not finish; worth seeing |
| `error` / `bad-request` | `error` with the bridge's reason | 007's `_payload_error` already extracts the real cause |
| `ok`, answer `UNCHANGED` for all sections | `ok`, no writes | The common case, and it must be cheap |
| `ok`, replacements returned | `ok` after validation passes; `error` + rollback if not | Constitution 6/9/10 |

**Routing**

```json
{
  "version": "1.2",
  "routes": {
    "pre-commit": ["doc-drift-detector"],
    "post-merge": ["living-doc-agent"],
    "pre-push":   ["living-doc-agent"]
  },
  "outcomes": {
    "doc-drift-detector": {"on_failure": "warn"},
    "living-doc-agent":   {"on_failure": "warn"}
  },
  "run_retention": 50
}
```

`warn` for both, deliberately. `block` on an async event is downgraded anyway (§4.2), and
blocking a push because a *documentation* agent failed is the wrong trade — constitution 10
wants human oversight, not enforcement.

**Key requirements**

- FR: MUST NOT edit any file outside `config/doc-targets.json`'s `docs` entries.
- FR: MUST NOT modify a target that has unstaged changes the agent did not author.
- FR: MUST validate before considering an edit final, and MUST roll back on failure.
- FR: MUST leave edits **unstaged** — MUST NOT run `git add`, `commit`, `push`, or any
  ref-mutating command (skill contract §4).
- FR: running twice against an unchanged repository state MUST produce no second edit.
- FR: MUST NOT invoke Claude when the gate rejects the change set.
- SC: a real behavioural change to `src/execute_skills.py` produces a `TUTORIAL.md` diff
  confined to §006 and nothing else.
- SC: a docs-only push produces `skipped` with zero Claude calls.
- SC: an injected validation failure leaves `TUTORIAL.md` byte-identical to before the run.
- SC: two consecutive runs on the same state produce one edit, then none.

**Tests** (stub the `claude` CLI per `TUTORIAL.md` §3.4 Level 2 — tests never need a model):
happy path with a stubbed replacement; `UNCHANGED` no-op; docs-only skip; `unavailable` →
skipped; `timeout` → error; malformed model output → error, no write; dirty-target fallback
to proposal file; validation failure → rollback verified byte-for-byte; idempotency
(run twice, second is a no-op); anchored replacement does not disturb neighbouring sections.

---

## 6. Phase 0 — prerequisites before 009 starts

| # | Task | Why |
|---|---|---|
| 0.1 | Confirm the §4.1 two-skill split | It is the one deviation from the answers given |
| 0.2 | Decide `README.md`: create it, or scope 011 to `TUTORIAL.md` | It is currently a target that does not exist |
| 0.3 | Author the initial `config/doc-targets.json` by hand for 001–008 | It is the system's ground truth; a model must not guess it |
| 0.4 | Agree the anchor convention (markdown headings vs. HTML comment fences) | Determines how brittle 011's anchored-region editing is |

On 0.4 — headings are already stable and human-meaningful in `TUTORIAL.md`, so start there;
add explicit `<!-- doc-agent:begin:<id> -->` fences only if heading drift proves to be a
problem in practice.

---

## 7. Risks

| Risk | Severity | Mitigation |
|---|---|---|
| Model edits degrade good prose | High | Anchored regions + validation + rollback + unstaged-only. The developer's `git diff` is the last gate (constitution 10). |
| Noisy churn: an edit on every push | High | Deterministic gate (009) before any Claude call; `UNCHANGED` is the expected common answer; docs-only guard breaks the feedback loop. |
| Target map rots | Medium | It is data in `config/`, reviewed like code. 009's `skipped`-with-warning on unmapped code paths makes rot visible. |
| Async failures go unnoticed | Medium | Deferred notification (§5.5) + `logs/hooks.log` + `run_records.py list`. |
| Concurrent runs corrupt a doc | Medium | Single-flight lock (§5.3). |
| Claude cost / rate limits on every push | Medium | Gate first, `max_turns` bounded, `UNCHANGED` path cheap; bridge already surfaces `api_error_status` (e.g. 429) as `error`. |
| `nohup` unavailable or behaves oddly on a platform | Low | POSIX-specified; fall back to sync + cap, which is today's behaviour. |
| Scope creep into `specs/**` or docstrings | Low | Explicitly excluded in §3; enforced by the target map, not by convention. |

---

## 8. Constitution check

| Principle | How this plan complies |
|---|---|
| 1 Incremental first | Change set comes from `hook-context@1.0`; full scan only via `manual_run.py --all`, explicit and recorded |
| 2 Git is the change authority | All three hook events plus the commit-range manual path |
| 3 Claude is the documentation engine | Only via 007's bridge; prompt bounded to changed files + mapped doc sections |
| 4 Spec before automation | 009/010/011 each go through `speckit.specify` → `clarify` → `plan` → `tasks` before code |
| 5 Deterministic & reviewable | Target map is deterministic; edits land as ordinary unstaged file diffs |
| 6 Safe by default | Anchored regions only; dirty targets fall back to a proposal; rollback on validation failure |
| 7 Documentation scope rules | Only mapped code→doc pairs; docs-only change sets skipped |
| 8 Explicit exclusions | `exclude` globs in `doc-targets.json`; `CLAUDE.md`, `specs/**`, docstrings out of scope |
| 9 Validation required | 011's pipeline step 6 is a mandatory gate with rollback |
| 10 Human oversight | Nothing is staged, committed, or pushed by the agent, ever |
| 11 Small composable scripts | Two single-purpose skills; async logic in `lib.sh`, mode in `hooks.conf`, nothing inline in hook config |
| 12 Structured I/O | `hook-context@1.0` in, `skill-result@1.0` out, `doc-targets` v1.0, `drift-report` v1.0 |
| 13 Idempotent workflows | Anchored replacement converges despite `idempotent: false` on the manifest |
| 14 Observable execution | Run records per run; deferred notification; `logs/hooks.log` |
| 15 Constitution overrides convenience | §4.1–4.3 are conflicts resolved *toward* the constitution, not around it |
| 16 Constitution stable | No constitutional change proposed; two contract addenda instead |

---

## 9. Next actions

1. Approve or amend §4.1 (the two-skill split) and §6 Phase 0 decisions.
2. `git checkout -b 009-doc-drift-detector` and run
   `/speckit.specify` → `/speckit.clarify` → `/speckit.plan` → `/speckit.tasks` using §5's
   Feature 009 scope and requirements as the input brief.
3. Implement 009 test-first; land it; `config/routes.json` gets its first non-empty route.
4. Repeat for 010, then 011.

Deliberately **not** in scope: CI/server-side execution, doc generation for source that has
no doc target, translation or restructuring of existing docs, and any automation that
commits on the developer's behalf.
