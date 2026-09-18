# AI-Assisted Architecture Documentation — Plan

**Status:** proposal, pending approval
**Date:** 2026-09-18
**Scope:** feature 012 — `architecture-doc-agent`
**Depends on:** 001–008 (complete), 010 (async mode + manual entry point)
**Companion plan:** [`living-documentation-roadmap.md`](living-documentation-roadmap.md)

---

## 1. Purpose

Maintain a single root-level `ARCHITECTURE.md` that always reflects the **current** architectural
state of the repository:

- what architecture the project follows, if that can be determined;
- if it cannot, what architecture the existing files suggest it *should* adopt;
- if there is not enough information for either, **nothing is written at all**;
- when an architecture is established: the compliance violations and the improvement
  opportunities that exist *right now*.

The file is a snapshot, not a log. Every run regenerates it. Resolved issues disappear
because they are simply absent from the next snapshot — there is no history to prune.

---

## 2. How it reuses the existing framework

Nothing new is needed in the runtime pipeline. The agent is a skill like any other.

| Framework component | Role for this agent |
|---|---|
| `scripts/*.sh` + `parse_context.py` (002/003) | Supplies the change set — which files moved, appeared, or disappeared. Structural change is the only thing that can invalidate an architecture verdict. |
| `config/routes.json` (004) | Routes `architecture-doc-agent` on the chosen events. Re-read per event. |
| Skill contract + registry (005) | `skills/architecture-doc-agent/{skill.json,run}`, `hook-context@1.0` in, `skill-result@1.0` out. |
| `execute_skills.py` (006) | Time budget (`time_budget_seconds: 150` for a baseline run). |
| `claude_bridge.py` (007) | The only path to Claude. Receives a **structural summary**, never source files — see §5. |
| `run_records.py` (008) | Every run recorded: what it detected, what it wrote, why it did nothing. |
| `manual_run.py` (010) | The explicitly-requested baseline scan. Constitution 1's sanctioned exception. |
| `_run_detached` (010) | Async execution so a 150 s baseline never holds up a push. |

---

## 3. The hard constraint, stated up front

**Architecture is a global property. The constitution forbids global analysis.**

> **1 Incremental First** — "Full repository scans are forbidden unless explicitly requested
> for migration, repair, or baseline regeneration."
> **3 Claude Is The Documentation Engine** — "must receive bounded context derived from the
> detected change set and must not operate on the entire repository by default."

You cannot conclude "this is a layered architecture" from three changed files. This agent
therefore needs a view no other skill in the system is allowed to take. That is a real
conflict, not a technicality, and it is resolved by splitting the agent into two modes with
different rights.

### 3.1 Resolution — two modes

| | **Baseline mode** | **Incremental mode** |
|---|---|---|
| Trigger | `manual_run.py --event architecture --baseline` — **explicitly requested**, never automatic | Any routed git event |
| Scope | Full structural inventory of the repository | The change set only |
| Claude | Yes — names the architecture, derives the rules, suggests improvements | Only when the change set materially alters the structure (§6.3) |
| Writes | The whole `ARCHITECTURE.md`, including the rule set | Recomputes compliance + improvements against the **already-established** rules |
| Constitutional basis | Constitution 1's "baseline regeneration" exception, invoked by a human | Constitution 1 satisfied normally — bounded change set |

The persisted rule set is what makes this work: the expensive global judgment happens once,
under human request; every automatic run afterwards is a cheap, bounded, deterministic check
against it.

### 3.2 What "full inventory" is allowed to mean

A further distinction matters, because it is the difference between a compliant design and
a forbidden one:

- **Allowed** — a *path-and-relationship* inventory: file paths, extensions, directory
  shape, declared dependency edges, schema-version strings, executable bits. Cheap, bounded,
  derivable with the stdlib, and reproducible byte-for-byte.
- **Not allowed** — reading the contents of every file and feeding them to a model. That is
  the scan constitution 3 forbids, and it would put this repository's entire source in one
  prompt.

Claude receives the inventory *summary* — on this repository, a few kilobytes — never the
files themselves. This keeps the bridge's bounded-context guarantee intact even in
baseline mode.

---

## 4. Critical finding: the obvious signal is the wrong one

The standard way to detect architecture is to build the import graph. **On this repository
that produces a wrong answer**, and any plan that skips this will ship a broken agent.

Verified state of `src/`:

```text
route_workflows.py  ──imports──▶  execute_skills.py
                    ──imports──▶  run_records.py
parse_context.py     (no internal imports)
claude_bridge.py     (no internal imports)
skill_registry.py    (no internal imports)
```

One edge. Five of six modules are import-leaves, there is no package (`__init__.py` is
absent), and every module is stdlib-only. An import-graph analyzer concludes: *"six unrelated
scripts, no architecture."*

That is false. The real architecture is a **staged pipeline whose boundaries are process
boundaries**, and its edges are invisible to import analysis:

| Real edge | Where it lives | Evidence to detect it |
|---|---|---|
| `parse_context.py` → `route_workflows.py` | a shell pipe in `scripts/orchestrate.sh` | `\|` between two `python3 .../*.py` invocations |
| `execute_skills.py` → `skills/<name>/run` | `subprocess.run([...,"run"], input=context_json)` | subprocess call with a resolved path |
| `skills/<name>/run` → `claude_bridge.py` | `subprocess.run([sys.executable, ".../claude_bridge.py"])` | subprocess call to a sibling module |
| every boundary | `hook-context@1.0`, `skill-result@1.0`, `execution-summary@1.0`, `bridge-request/result@1.0`, `run-record@1.0` | versioned schema constants in each module |

**Therefore the analyzer must extract four edge types, not one:**

1. **Import edges** — stdlib `ast`, deterministic.
2. **Subprocess edges** — `ast` walk for `subprocess.run`/`Popen`/`os.exec*` whose argv
   contains a repo-relative path.
3. **Shell pipeline edges** — pipes and invocations in `scripts/*.sh` and `.githooks/*`.
4. **Contract edges** — shared `*@<version>` schema identifiers, which reveal that two
   components with no code relationship nonetheless share an interface.

Edge types 2–4 are what make the architecture legible. They are also generalisable: any
project built from CLIs, containers, or message queues has the same blind spot.

---

## 5. Expected baseline output for *this* repository

Stating the expected answer makes the feature testable — this is an acceptance criterion, not
documentation.

The agent should identify a **staged pipeline (Unix filter) architecture with versioned data
contracts**, carrying two secondary patterns:

- a **plugin architecture** for skills (`skills/<name>/` + `registry.json` + a fixed
  `run` entry point and I/O contract);
- an **adapter** isolating an external tool (`claude_bridge.py` is the only component that
  knows the `claude` CLI exists).

…and the cross-cutting rules that follow from it: every component is a CLI speaking JSON on
stdin/stdout; every component exits 0 except the reserved 10; runtime is stdlib-only; the
shell layer carries no business logic; tests mirror modules 1:1 via `sys.path` bootstrap.

If the agent's baseline run on this repository reports "no discernible architecture", the
analyzer is wrong (§4) and the feature is not done.

---

## 6. The three verdicts

The requirement "if the information is insufficient then do nothing" needs a concrete
threshold, because "insufficient" must never be a judgment call the model makes loosely — and
it must never destroy a good existing file.

### 6.1 `established` — an architecture is detectable

Write the full file: identified style, components, boundaries, rules, **compliance
violations**, **improvement opportunities**.

### 6.2 `suggested` — no architecture detectable, but the files imply one

Write the file with a clearly-labelled *"Proposed architecture — not yet adopted"* section.

**Compliance checking MUST NOT run in this mode.** Validating a codebase against an
architecture it never agreed to would flag the entire repository as non-compliant — noise
that would get the agent switched off in a day. Improvements are permitted; violations are
not, because there is nothing to violate yet.

### 6.3 `insufficient` — do nothing

Exit `skipped`, write nothing, **and do not modify or delete an existing
`ARCHITECTURE.md`**. This is the single most important safety rule in the feature: a
transient bad run must never blank a good file.

Deterministic entry conditions, all evaluated before any Claude call:

- fewer than 5 source files, **or**
- fewer than 2 distinct top-level source directories, **or**
- zero resolvable edges of any of the four types in §4, **or**
- Claude returns no verdict, a malformed verdict, or an explicit low-confidence signal, **or**
- the bridge returns `unavailable` / `timeout` / `error`.

### 6.4 Re-baseline required

A fifth, narrower outcome. When incremental runs observe that the structure has drifted far
from the recorded baseline — new top-level source directory, or more than ~30 % of components
unknown to the recorded inventory — the agent does **not** silently validate against a stale
model. It keeps the existing file, adds a single prominent *"Re-baseline recommended"* notice,
and names the command to run. Validating 2027's code against 2026's rules would produce
confident nonsense.

---

## 7. `ARCHITECTURE.md` design

### 7.1 Location and ownership

Root of the repository, `ARCHITECTURE.md`. **Machine-owned.** Two consequences that must be
handled, not assumed:

1. It must be added to `config/doc-targets.json`'s exclusions so the living-doc agent
   (feature 011) never edits it. Two agents writing one file is a corruption bug waiting to
   happen.
2. Hand edits will be overwritten. The file must say so in its own header, and the header
   must name the command that regenerates it.

### 7.2 Snapshot semantics

Regenerated in full on every run that produces a verdict. No issue history, no changelog, no
"resolved on" entries — a fixed violation vanishes because the next snapshot does not contain
it. This is simpler *and* more idempotent than the anchored-region editing feature 011 needs,
precisely because no human prose is at risk.

One consequence worth accepting deliberately: `git log ARCHITECTURE.md` becomes the issue
history. That is sufficient, and it is free.

### 7.3 Structure

```markdown
# Architecture

<!-- Generated by skills/architecture-doc-agent. Manual edits are overwritten.
     Regenerate: python3 src/manual_run.py --event architecture --baseline -->

**Status:** established · **Baseline:** 2026-09-18 (a1b2c3d) · **Last checked:** 2026-09-19 (e4f5g6h)

## 1. Architecture in use
Staged pipeline (Unix filter) with versioned data contracts. Secondary: plugin
architecture for skills; adapter isolating the Claude CLI.

## 2. Components and boundaries
| Component | Role | Boundary type | Contract |
|---|---|---|---|

## 3. Rules in force
| # | Rule | Derived from | Checked |
|---|---|---|---|
| R1 | Components communicate as JSON over stdin/stdout, not by import | baseline | automatic |
| R2 | Runtime code imports stdlib only | baseline | automatic |
| R3 | Shell layer contains no business logic | baseline | manual |

## 4. Compliance issues (current)
| Severity | Rule | Location | Issue |
|---|---|---|---|
_None._

## 5. Improvement opportunities (current)
| Priority | Area | Suggestion | Rationale |
|---|---|---|---|

## 6. Component map
```text
(inventory tree + detected edges)
```

<!-- architecture-state:begin -->
```json
{"schema_version":"1.0","status":"established","style":"staged-pipeline",
 "baseline_commit":"a1b2c3d","inventory_fingerprint":"sha256:…",
 "components":[…],"rules":[{"id":"R1","check":"no-cross-component-import",…}]}
```
<!-- architecture-state:end -->
```

### 7.4 Why the state block exists

The fenced `architecture-state` block at the bottom holds the machine-readable model: the
detected style, the component inventory, its fingerprint, and the **rule set with its
executable check identifiers**.

It exists so that incremental runs can enforce rules without re-deriving them, which means
without a Claude call. It lives inside `ARCHITECTURE.md` rather than in a second file so that
the requirement "one new file at the root" holds literally, and so a fresh clone carries the
model with it. (State in `logs/` would not survive a clone — `logs/` is gitignored.)

If the block is missing or unparseable — a human edited it, or a merge mangled it — the agent
treats the state as absent and reports *"re-baseline required"*. It does not guess.

---

## 8. Deterministic vs. Claude: the split

Getting this boundary right is what makes the agent trustworthy and cheap. Claude is used for
judgment. Everything checkable is checked in code.

| Work | How | Why |
|---|---|---|
| Structural inventory (paths, extensions, tree) | stdlib `os`/`pathlib` | Cheap, exact, reproducible |
| Import edges | stdlib `ast` | Exact; no regex guessing |
| Subprocess + pipeline edges | stdlib `ast` + line scan of `scripts/*.sh` | §4 — the load-bearing edges |
| Contract edges | scan for `*@<version>` identifiers | Reveals interface coupling with no code coupling |
| Inventory fingerprint | `sha256` of the normalised inventory | Decides whether a Claude call is needed at all |
| **Naming the architecture** | **Claude, via 007** | Genuine judgment; no heuristic is honest here |
| **Deriving rules on baseline** | **Claude, via 007** | Judgment — but output is constrained to a fixed set of executable check ids |
| **Improvement suggestions** | **Claude, via 007** | Judgment |
| **Enforcing rules every run** | **deterministic checks in Python** | Constitution 5: same state ⇒ same violations, every time |

Two direct consequences:

- **Violations are reproducible.** Compliance output does not vary between runs on identical
  input, because a model never produces it.
- **Most runs cost nothing.** If the inventory fingerprint is unchanged, there is no Claude
  call: re-run the deterministic checks, rewrite the file, done in milliseconds.

Claude's rule output is constrained to a closed vocabulary of check identifiers
(`no-cross-component-import`, `stdlib-only`, `contract-version-required`, `no-upward-dependency`,
`entrypoint-required`, …). A rule the checker cannot execute is recorded as
`"checked": "manual"` and never silently treated as enforced.

---

## 9. Feature 012 scope

Three user stories, in the P1/P2/P3 form your specs already use, deliverable independently.

### P1 — Baseline detection and file generation 🎯 MVP

A developer runs the baseline command and gets an accurate `ARCHITECTURE.md`, or a clear
explanation of why none was written.

- `src/architecture_scan.py` — the deterministic analyzer: inventory + four edge types +
  fingerprint. Emits `architecture-inventory@1.0`. Standalone CLI, testable with no git.
- `skills/architecture-doc-agent/{skill.json,run}` — baseline path: scan → bridge → verdict →
  render → validate → write.
- `src/architecture_doc.py` — render and parse `ARCHITECTURE.md`, including the state block.
- Wire `--event architecture --baseline` into `manual_run.py` (010).

### P2 — Deterministic compliance checking on git events

Every routed git event re-checks the change set against the recorded rules and refreshes
sections 4 and 5 of the file. No Claude call when the fingerprint is unchanged.

- `src/architecture_rules.py` — the closed set of executable checks.
- Incremental path in the skill; re-baseline detection (§6.4).
- Route on `post-merge` and `pre-push` (async). **Not** `pre-commit` — architecture drift is
  not a per-commit concern and it would add noise to the most frequent operation.

### P3 — Improvement opportunities

Claude-generated suggestions in section 5, refreshed only when the fingerprint changes.
Separable because P1+P2 are useful without it.

### Contracts

- `specs/012-*/contracts/architecture-inventory.md` — analyzer output, v1.0.
- `specs/012-*/contracts/architecture-state.md` — the embedded state block, v1.0.
- `specs/012-*/contracts/architecture-rules.md` — the closed check vocabulary, v1.0.

### Functional requirements

- **FR-001** MUST NOT create or modify `ARCHITECTURE.md` when the verdict is `insufficient`.
- **FR-002** MUST NOT delete or blank an existing `ARCHITECTURE.md` on any failure path.
- **FR-003** MUST NOT run compliance checks when the status is `suggested` (§6.2).
- **FR-004** MUST send Claude the inventory summary only, never file contents (constitution 3).
- **FR-005** MUST perform a full-repository inventory only when explicitly requested.
- **FR-006** MUST skip a docs-only change set, including one that touches only
  `ARCHITECTURE.md` (recursion guard).
- **FR-007** MUST NOT stage, commit, push, or mutate any git ref (skill contract §4).
- **FR-008** MUST produce byte-identical output for identical repository state and identical
  recorded state (constitution 13).
- **FR-009** MUST skip the Claude call when the inventory fingerprint is unchanged.
- **FR-010** MUST treat a missing or unparseable state block as "re-baseline required", not
  as an absence of architecture.
- **FR-011** MUST record every run's verdict and reason in the 008 run record, including
  `skipped`.
- **FR-012** MUST validate the rendered file before replacing the existing one, and roll back
  on failure (constitution 9).
- **FR-013** MUST detect the four edge types in §4; import edges alone are insufficient.
- **FR-014** MUST label any rule it cannot execute as `checked: manual`.

### Success criteria

- **SC-001** A baseline run on this repository reports a staged pipeline / Unix filter
  architecture with versioned data contracts, and lists `claude_bridge.py` as an adapter and
  `skills/` as a plugin boundary.
- **SC-002** The same baseline run on unchanged state, twice, produces byte-identical files
  apart from the "last checked" stamp.
- **SC-003** A new module importing across a boundary that R1 forbids appears in section 4
  within one git event, without a Claude call.
- **SC-004** On an empty repository, and with `claude` absent from `PATH`, no file is created.
- **SC-005** With an existing valid file and a forced bridge failure, the file is byte-identical
  before and after the run.
- **SC-006** A fixed violation is absent from the next snapshot, with no "resolved" entry
  anywhere in the file.
- **SC-007** An incremental run with an unchanged fingerprint completes in under 2 s and makes
  zero Claude calls.
- **SC-008** The analyzer, run on `src/` alone, reports the single real import edge and at
  least three subprocess/pipeline edges.

### Tests

Analyzer: import edge extraction; subprocess edge extraction; shell pipeline extraction;
contract-identifier extraction; fingerprint stability under file reordering.
Verdict: established / suggested / insufficient for each threshold in §6.3; empty repo; single-file repo.
Safety: bridge `unavailable` → no write; bridge `timeout` → existing file untouched byte-for-byte;
malformed Claude verdict → no write; validation failure → rollback.
State: round-trip of the state block; missing block → re-baseline; corrupted block → re-baseline;
fingerprint drift > 30 % → re-baseline notice.
Idempotency: two consecutive runs → identical output. Recursion: change set of only
`ARCHITECTURE.md` → `skipped`.
Claude is stubbed throughout, per `TUTORIAL.md` §3.4 Level 2.

---

## 10. Interaction with features 009–011

| Interaction | Requirement |
|---|---|
| Feature 011 (living-doc agent) edits root docs | `ARCHITECTURE.md` MUST be in `doc-targets.json`'s exclusion list. Machine-owned files have exactly one writer. |
| Feature 009's `doc-targets.json` | Unrelated map; 012 keeps its own model in the state block. No shared config. |
| Feature 010's single-flight lock | Already serialises runs, so 011 and 012 cannot write concurrently. 012 depends on that lock existing. |
| Both agents route on `pre-push` | 006 executes sequentially, so ordering is deterministic. Put `architecture-doc-agent` last — it is the more expensive and the less urgent. |
| Both are `on_failure: warn` | An architecture *document* failing must never block a push. |

---

## 11. Risks

| Risk | Severity | Mitigation |
|---|---|---|
| A wrong architecture verdict gets enshrined as enforced rules | **High** | Baseline is human-requested and human-reviewed before the file is committed; rules are visible in section 3 with their origin; `suggested` mode never enforces |
| Analyzer misses the real boundaries and reports "no architecture" | **High** | §4 — four edge types, and SC-001/SC-008 fail the feature if it happens on this repo |
| Compliance noise gets the agent switched off | High | Deterministic checks only, closed vocabulary, no enforcement in `suggested` mode, `pre-commit` excluded |
| A bad run blanks a good `ARCHITECTURE.md` | High | FR-001/002, validate-then-replace, rollback, and SC-005 pins it |
| Rules go stale as the project evolves | Medium | Fingerprint drift → re-baseline notice (§6.4) rather than confident stale answers |
| Baseline prompt grows past a sane size on a large repo | Medium | Summary, not contents; aggregate per directory above a threshold; the inventory is a few KB here |
| Full inventory is read as a constitution 1 violation | Medium | §3.1/3.2 — explicitly requested, path-level only, documented in the plan's constitution check |
| Human edits lost to regeneration | Low | Header states ownership; `git diff` catches it; architectural *prose* belongs in `specs/`, not here |

---

## 12. Constitution check

| Principle | Compliance |
|---|---|
| 1 Incremental first | Full inventory only in human-requested baseline mode; every automatic run is change-set bounded |
| 2 Git is the change authority | Structural change detected from the hook context; baseline pinned to a commit sha |
| 3 Claude bounded | Inventory *summary* only — never file contents, never the repository |
| 4 Spec before automation | 012 goes through `speckit.specify` → `clarify` → `plan` → `tasks` before code |
| 5 Deterministic & reviewable | Violations computed in code, not by a model; output is a reviewable file diff |
| 6 Safe by default | Insufficient ⇒ write nothing; never blank an existing file; `suggested` never enforces |
| 7 Documentation scope | Writes exactly one file, `ARCHITECTURE.md`, and nothing else |
| 8 Explicit exclusions | Inventory honours the same exclusion globs as 009 (`logs/**`, `.venv/**`, `__pycache__/**`) |
| 9 Validation required | FR-012: validate rendered output, state-block round-trip, referenced paths exist, else roll back |
| 10 Human oversight | Nothing staged or committed; baseline requires a human command; rules are human-readable in section 3 |
| 11 Small composable scripts | Analyzer, renderer, rule checker, and skill are four separate testable units |
| 12 Structured I/O | Three new versioned contracts; state block is JSON |
| 13 Idempotent | FR-008 + SC-002/SC-006: full regeneration with no accumulation |
| 14 Observable | Verdict and reason in every 008 run record, including `skipped` |
| 15 Constitution overrides convenience | §3 resolves the global-analysis conflict *within* the constitution's own exception, rather than quietly ignoring principle 1 |
| 16 Constitution stable | No constitutional change needed; no contract addenda required |

---

## 13. Decisions needed before implementation

1. **Events.** Plan proposes `post-merge` + `pre-push`, excluding `pre-commit`. Confirm.
2. **Baseline review gate.** Should the first baseline require the developer to commit the file
   before P2 begins enforcing its rules? Recommended: yes — an unreviewed rule set should not
   generate violations.
3. **Re-baseline drift threshold.** ~30 % unknown components is a starting guess, not a
   derived number. Adjust after the first real run.
4. **Rule vocabulary.** The closed check set in §8 needs agreeing; adding a check later is an
   additive contract change, so starting small is cheap.
5. **`suggested` mode** — worth building at all, or start with `established` and `insufficient`
   only? On a repo that already has a clear architecture, `suggested` may be dead code.

---

## 14. Next actions

1. Resolve §13.
2. Land feature 010 (async + `manual_run.py`) — 012's baseline path depends on it.
3. `git checkout -b 012-architecture-doc-agent`, then `/speckit.specify` using §9 as the brief.
4. Build P1 test-first, run one real baseline, **review the generated rules by hand** before
   committing the file. Then P2, then P3.

Deliberately **not** in scope: enforcing architecture by blocking git operations; generating
diagrams; multi-language analysis beyond Python and POSIX sh; refactoring code to fit the
architecture; and architectural decision records (ADRs), which are human judgment and belong
in `specs/`.
