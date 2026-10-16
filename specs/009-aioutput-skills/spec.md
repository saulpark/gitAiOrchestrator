# Feature Specification: Declarative AI Skills with Sandboxed `_aioutput/` Results

**Feature Branch**: `009-aioutput-skills`
**Created**: 2026-10-02
**Status**: Draft
**Input**: User description: "the new way of work should call the skills and not report
anything back instead claude should be able to write a file with the results under a folder
called _aioutput on the root of the project. claude should not be able to modify anything
else on the project"

**Clarifications (2026-10-02)**:

- Per skill, execution is **sync or async**. Only sync skills may block the git operation.
- A skill is **declarative**: a manifest plus a prompt, with no executable code.
- Output keeps a **history**: `_aioutput/<skill>/<timestamp>-<event>.md`, one file per run.
- A sync skill blocks via a **structured verdict returned by Claude** (pass/fail + reason).
- The sync hook delay is governed by the **declared time budgets**, up to a bounded ceiling.
  It is no longer the fixed 5 s.
- `_aioutput/` is **gitignored**.
- **The framework writes the file. Claude gets read-only tools.** Claude returns its report
  as structured output; the orchestrator, not Claude, writes it to `_aioutput/`. With no
  write tool, Claude cannot modify the project.
- This is documented as **new feature 009**. The roadmap proposals 009–012 shift to 010–013.

## Supersedes

This feature replaces part of the behavior of shipped features:

| Feature | What changes |
|---------|--------------|
| 002 git hooks | The fixed 5 s hook cap becomes a bounded ceiling that sync budgets can use (FR-012) |
| 005 skill contract | v1.1 → **v2.0** (major). `run` executables and `skill-result@1.0` are removed, and an executable in a skill dir is now a violation |
| 006 executor | No more skill subprocesses. Sync skills go through the bridge in-process; async skills are dispatched detached |
| 007 bridge | Claude always runs read-only (`--restricted`, a read-only tool allowlist, structured output). The `hooks_enabled` and `extra_args` escape hatches are removed, and the project settings no longer apply |
| 008 observability | Blocking is driven only by a `fail` verdict. Infrastructure errors never block. Terminal output is limited to block messages |

The Windows `skill_command` shebang handling (branch `fix-windows-support`) becomes dead code
and is removed. Without skill executables there is nothing to launch.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Skill Results Land in `_aioutput/`, Not in My Terminal (Priority: P1)

A developer commits or pushes. The routed skills run, and each skill's result is a markdown
file under `_aioutput/<skill>/`. The git command prints nothing about the skills unless one
of them blocks.

**Why this priority**: This is the core behavior change requested. Results are durable
files you can review at leisure, not transient terminal text.

**Independent Test**: Register one async skill on pre-commit and commit. The commit
completes with no skill output on the terminal. Within the skill's budget, a new file
`_aioutput/<skill>/<timestamp>-pre-commit.md` appears, containing Claude's report and a
header naming the skill, event, branch, verdict and run id.

**Acceptance Scenarios**:

1. **Given** an async skill routed to pre-commit, **When** the developer commits,
   **Then** the commit returns without waiting for Claude, prints nothing about the skill,
   and the result file appears later.
2. **Given** two consecutive runs of the same skill, **When** both complete,
   **Then** two distinct files exist under `_aioutput/<skill>/`, and neither overwrites the
   other.
3. **Given** `_aioutput/` does not exist, **When** a skill completes,
   **Then** the framework creates it. `git status` still shows nothing from it, because
   it is gitignored.

---

### User Story 2 - Claude Cannot Modify the Project (Priority: P1)

Whatever a skill's prompt says, the Claude session it starts cannot create, modify or
delete any file in the project, and cannot run commands. The only file a run produces is
the result file the framework writes under `_aioutput/<skill>/`.

**Why this priority**: This is the explicit security requirement. It must be a mechanical
guarantee, not a polite request in a prompt.

**Independent Test**: Register a skill whose prompt instructs Claude to edit `README.md`,
create `evil.txt`, and run `git commit` via a shell. Run it. Afterwards `git status` and
the file hashes outside `_aioutput/` are unchanged. The result file records that Claude
could not perform those actions.

**Acceptance Scenarios**:

1. **Given** a prompt requesting file edits, **When** the skill runs,
   **Then** no project file outside `_aioutput/` changes.
2. **Given** a prompt requesting shell commands, **When** the skill runs,
   **Then** no command executes. The shell tools are not available to the session at all.
3. **Given** project or user Claude settings that allow `Bash` or `Write`,
   **When** a skill runs, **Then** those settings do not apply to the session.
4. **Given** a skill directory containing an executable (`run`, `*.sh`, `*.py`),
   **When** it is registered or validated, **Then** registration is rejected. Executable
   skill code would bypass the guarantee.

---

### User Story 3 - A Sync Skill Can Stop a Bad Commit (Priority: P2)

An operator marks a skill as sync and `on_failure: block` for pre-commit. When Claude's
verdict is `fail`, the commit aborts with one line naming the skill, the reason, and the
result file to read. When the verdict is `pass`, the commit proceeds silently.

**Why this priority**: This is the one case where something must reach the terminal.
Without it, sync mode has no purpose.

**Independent Test**: Use a sync skill with a block rule whose prompt yields `fail` for a
staged file containing `TODO-BLOCK`. Committing that file aborts with
`[hook blocked] skill '<name>': <reason> (see _aioutput/<name>/<file>.md)`. Committing a
clean file succeeds with no output.

**Acceptance Scenarios**:

1. **Given** a sync, block-ruled skill with verdict `fail` on pre-commit or pre-push,
   **Then** the git operation aborts and the result file is still written.
2. **Given** the same skill and Claude unavailable, timed out, or returning no valid
   verdict, **Then** the operation is **not** blocked. The error is logged and recorded.
   Only an explicit `fail` blocks (safe by default).
3. **Given** an async skill configured with `on_failure: block`, **Then** the config is
   accepted with a warning that async skills cannot block, and the operation never blocks.
4. **Given** a sync, block-ruled skill on post-merge, **Then** the block is downgraded
   (existing 008 rule), because the merge has already happened.

---

### User Story 4 - Diagnose a Run That Produced No File (Priority: P3)

A developer expects a result file that isn't there. `logs/hooks.log` and the run records
(`run_records.py show --last`) show the skill's mode, its status, and why no file was
written (for example: Claude unavailable, budget exceeded, unregistered skill).

**Why this priority**: Constitution principle 14. "Not reporting back" on the terminal must
not make failures invisible.

**Independent Test**: Make the `claude` CLI unavailable and commit with an async skill
routed. No file appears. The async run record states `unavailable` with the reason.

### Edge Cases

- **Two runs in the same second**: the file name gets a `-2`, `-3`… suffix. Nothing is
  overwritten.
- **Async run still in flight when the next git operation starts**: both proceed
  independently. Each writes its own file, and neither touches project files, so no lock is
  needed.
- **Working tree changes before an async skill reads it**: Claude sees the current tree,
  not a snapshot. This is a documented limitation, and the header records the triggering
  commit/branch.
- **`_aioutput/` exists as a file, or is unwritable**: the result is not written. The
  failure goes to the record and the log, and the git operation is unaffected.
- **Sync skills whose budgets exceed the sync ceiling**: later skills get only the
  remaining time. Those that cannot start are recorded as `timeout` with "sync ceiling
  exhausted".
- **Empty prompt file / missing prompt**: this is a registration violation. At run time
  the skill is `skipped`.
- **Claude returns a report but the structured verdict is missing or invalid**: the file is
  still written with `verdict: invalid`, and the status is `error` (never blocks).
- **Unbounded history growth**: per-skill retention prunes the oldest files beyond the
  limit.

## Requirements *(mandatory)*

### Trigger, input and targets (constitution 4)

- **Trigger source**: the existing git hooks (pre-commit, pre-push, post-merge), via the
  router.
- **Input context**: hook-context@1.0, unchanged.
- **Output target**: `_aioutput/<skill>/` only. **No documentation file in the project is
  modified** by this feature.
- **Exclusions**: `_aioutput/` is gitignored, so it never enters a hook context. The
  existing exclusions are unchanged.

### Functional Requirements

**Skills**

- **FR-001**: A skill MUST consist of `skill.json` + `prompt.md` (contract v2.0) and MUST
  NOT contain executable code. Any executable file in the skill directory MUST be a
  registration/validation violation.
- **FR-002**: Execution mode MUST be configurable per skill as `sync` or `async`, in the
  routing configuration. The default is `async`.

**Claude confinement**

- **FR-003**: Every Claude invocation MUST run with only read-only tools available (`Read`,
  `Grep`, `Glob`). No write, edit, shell, code-execution, web or MCP tools may be available.
- **FR-004**: Every Claude invocation MUST ignore user, project and local Claude settings
  files and MUST disable Claude hooks. Nothing configured outside the framework may widen
  the tool set.
- **FR-005**: Bridge configuration MUST NOT offer any way to pass arbitrary CLI arguments
  or re-enable tools. Only an allowlisted set of options is accepted (e.g. `model`,
  `max_turns`, `timeout_seconds`).
- **FR-006**: Claude MUST return its result as structured output with the shape
  `{verdict, reason, report}`.

**Output**

- **FR-007**: The framework, not Claude, MUST write each completed run's result to
  `_aioutput/<skill>/<UTC timestamp>-<event>.md` at the repo root. The write MUST be
  atomic and MUST never overwrite an existing file.
- **FR-008**: Each result file MUST start with a header recording: the skill and its
  version, event, branch, mode, verdict, reason, run id, timestamp, and the list of files
  in scope.
- **FR-009**: The number of result files kept per skill MUST be bounded by a configurable
  retention (default 50). The oldest files are pruned first.
- **FR-010**: `_aioutput/` MUST be gitignored.

**Sync / async**

- **FR-011**: An async skill MUST be dispatched as a detached process that survives the git
  command's exit. Dispatch MUST add under 200 ms to the git operation.
- **FR-012**: Sync skills MUST run before the git operation proceeds. Each is bounded by
  its time budget, and all sync skills of one run together are bounded by a configurable
  sync ceiling (default 120 s, max 600 s).
- **FR-013**: Only a sync skill whose verdict is `fail` and whose rule is
  `on_failure: block`, on pre-commit or pre-push, MAY block the git operation. Errors,
  timeouts and unavailability MUST NOT block.
- **FR-014**: Terminal output during a git operation MUST be limited to block messages.
  A block message names the skill, the reason and the result file. Warnings and errors go
  to `logs/hooks.log` and the run records only.

**Observability**

- **FR-015**: Every run MUST still produce a run record (008). Each async execution MUST
  produce its own record linked to the dispatching run, including failures before any file
  was written.

### Key Entities

- **Declarative Skill**: a manifest plus a prompt. Data only; it runs nothing itself.
- **Skill Mode**: `sync` (the git operation waits, and the skill may block) or `async`
  (detached, never blocks).
- **Verdict**: Claude's structured answer, `pass` | `fail` plus a reason. It is what a sync
  skill blocks on.
- **Result File**: one markdown file per completed skill run under `_aioutput/<skill>/`,
  written by the framework.
- **Sync Ceiling**: the upper bound on how long one git operation can wait for its sync
  skills.

## Success Criteria *(mandatory)*

- **SC-001**: In 100% of tested adversarial prompts (edit a file, create a file, delete a
  file, run a shell command, commit), no project file outside `_aioutput/` changes.
  Checked by a content hash before and after.
- **SC-002**: With only async skills routed, `git commit` returns within 1 s of what it
  takes without the framework, and every async skill's file or failure record appears
  within its budget.
- **SC-003**: A sync, block-ruled skill with verdict `fail` aborts 100% of pre-commit and
  pre-push operations. With Claude unavailable, it aborts 0%.
- **SC-004**: With no skill blocking, a git operation prints zero lines about the skills.
- **SC-005**: For any run, a developer can tell from `run_records.py show` and
  `logs/hooks.log` alone why a result file is missing.

## Assumptions

- Mode and block rules live in `config/routes.json` (operator policy), not in the skill
  manifest (authoring). One place decides "what runs, how, and with what consequence".
- The default mode is `async`: it never delays git and never blocks, which is the safest
  default.
- The default time budget per skill is 60 s (Claude round-trips measured at 13–17 s for a
  trivial task). The manifest `time_budget_seconds` overrides it, up to 600 s.
- The prompt-level "examine only the listed files" constraint (007) remains. `--restricted`
  additionally confines Claude's read tools to the working directory. Reading the
  repository is allowed; *modifying* it is not.
- No registry migration is needed: `skills/registry.json` is currently empty.
- **Roadmap impact**: the roadmap's doc-drift-detector (a Python skill), living-doc-agent
  and architecture-doc-agent (Claude editing project docs) are incompatible with this
  feature as written. They must be re-scoped to write proposals to `_aioutput/` before
  being specified.
