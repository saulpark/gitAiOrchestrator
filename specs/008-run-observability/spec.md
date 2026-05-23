# Feature Specification: Run Observability and Outcome Enforcement

**Feature Branch**: `008-run-observability`
**Created**: 2026-04-09
**Status**: Draft
**Input**: User description: "Ensures automation is observable, debuggable, and capable of
enforcing block/warn/skip outcomes appropriately."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Developer Sees What Ran and What Happened (Priority: P1)

After a git event triggers automation, the developer has immediate access to a clear,
human-readable record of what skills ran, what each returned, and what the overall outcome
was — without needing to dig through raw logs or rerun the automation.

**Why this priority**: Automation that runs silently without visible results is
indistinguishable from automation that didn't run at all. Visibility is the baseline
requirement for developer trust in the system. If developers cannot see what happened, they
cannot verify the system is working and cannot catch cases where documentation was silently
not updated.

**Independent Test**: Trigger a git event that runs a multi-skill plan. Immediately after
the event, inspect the run record. Verify it shows: which event triggered the run, which
skills ran, each skill's status (success/failure/timeout/skipped), and the final outcome
applied (block/warn/skip).

**Acceptance Scenarios**:

1. **Given** a git event triggers an automation run,
   **When** the run completes,
   **Then** a run record is available that shows: event type, timestamp, skills that were
   invoked, status of each skill, and the outcome applied to the git operation.

2. **Given** the run record is available,
   **When** a developer reads it,
   **Then** they can determine in under one minute whether the automation succeeded, which
   skills ran, and what outcome was enforced — without needing any external tools or
   documentation.

3. **Given** multiple automation runs have occurred,
   **When** a developer inspects the run history,
   **Then** they can see a list of past runs ordered by time, with a one-line summary for
   each showing event, outcome, and whether any skills failed.

---

### User Story 2 - Developer Can Diagnose Why an Outcome Was Produced (Priority: P2)

When automation produces an unexpected or surprising result — a warning the developer didn't
anticipate, a skill that was skipped instead of running, or a block that stopped a commit —
the developer can find enough detail in the run record to understand the root cause without
asking for help or re-running the automation.

**Why this priority**: Observable but not debuggable automation shifts the burden of
investigation to the developer. When the system makes a decision (e.g., blocking a commit),
it must justify that decision in terms the developer can act on. Without diagnostic detail,
developers will distrust and disable automation.

**Independent Test**: Configure a skill to return a specific result that triggers a
non-default outcome. Trigger the associated git event. Inspect the diagnostic detail in the
run record. Verify it contains: the skill's input context, its output, the outcome rule that
matched, and the reason the outcome was applied.

**Acceptance Scenarios**:

1. **Given** a skill produces a result that triggers a warn or block outcome,
   **When** a developer reads the run record,
   **Then** the record contains the specific skill output that triggered the outcome and
   the outcome rule that matched it.

2. **Given** a skill was skipped (not invoked),
   **When** a developer inspects the run record,
   **Then** the record explains why it was skipped — e.g., skill not found in registry,
   context was partial, or an earlier skill failure triggered a skip policy.

3. **Given** an automation run produced an unexpected outcome,
   **When** a developer reviews the diagnostic detail,
   **Then** they can identify the exact decision point — which skill output, which rule,
   which outcome — and know what to change to alter the behavior.

---

### User Story 3 - Outcomes Are Enforced According to Skill Results and Configuration (Priority: P3)

The system applies the configured outcome (block the git operation, show a warning, or
proceed silently) based on what skills returned and how outcome rules are configured. The
developer controls which outcomes apply to which skills and under what conditions.

**Why this priority**: Without outcome enforcement, automation is purely informational.
The block/warn/skip model is what gives the system leverage — it can stop a commit if
documentation is inconsistent, or warn without blocking when confidence is lower. Making
outcomes configurable ensures the system is tuned to each team's risk tolerance.

**Independent Test**: Configure three skills with different outcome rules: skill A configured
to block on failure, skill B to warn on failure, skill C to skip silently. Cause each to
fail independently. Verify skill A's failure blocks the git operation, skill B's failure
shows a warning without blocking, and skill C's failure proceeds silently with a log entry.

**Acceptance Scenarios**:

1. **Given** a skill is configured with a block outcome rule and returns a failure,
   **When** the outcome is evaluated,
   **Then** the git operation is aborted and the developer receives a clear message
   identifying the skill and the reason for the block.

2. **Given** a skill is configured with a warn outcome rule and returns a failure,
   **When** the outcome is evaluated,
   **Then** the git operation proceeds and the developer receives a visible warning
   message identifying the skill result and what it means.

3. **Given** a skill is configured with a skip outcome rule (or has no outcome rule),
   **When** the skill returns any result,
   **Then** the git operation proceeds without any message to the developer, but the
   result is recorded in the run log.

4. **Given** outcome rules are updated in configuration,
   **When** the next automation run occurs,
   **Then** the updated rules are applied — no reinstallation required.

---

### Edge Cases

- What happens when a run produces no skills executed (empty plan or all skipped)?
- What happens when a block outcome is triggered but the git operation has already completed
  (e.g., for post-merge events that run after the merge)?
- What happens when two skills in the same run both trigger block outcomes?
- What happens when a skill produces a result that matches no configured outcome rule and
  no default is set?
- How many past run records are retained before older ones are discarded?

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The system MUST produce a run record for every automation run, including runs
  where all skills were skipped or the plan was empty.
- **FR-002**: Each run record MUST include: trigger event type and timestamp, list of skills
  invoked with status and duration, outcome applied, and the outcome rule that matched (if
  any).
- **FR-003**: The system MUST retain a history of recent run records accessible to the
  developer without requiring a separate tool — the run history MUST be queryable from the
  repository.
- **FR-004**: The run record MUST include diagnostic detail sufficient to identify the exact
  skill output and outcome rule responsible for any non-skip outcome.
- **FR-005**: The system MUST evaluate an outcome rule for each skill result after execution
  and apply the configured outcome: block (abort the git operation), warn (emit a visible
  message and proceed), or skip (proceed silently, record only).
- **FR-006**: A block outcome MUST cause the git operation to abort with a non-zero exit
  code and a clear human-readable message identifying the blocking skill and reason.
- **FR-007**: A warn outcome MUST emit a visible message to the developer without aborting
  the git operation.
- **FR-008**: Outcome rules MUST be configurable per skill in the routing configuration and
  MUST take effect on the next automation run without reinstallation.
- **FR-009**: When no outcome rule is configured for a skill, the default outcome MUST be
  warn (not block), to preserve the "safe by default" constitution principle.
- **FR-010**: The system MUST log all run activity — including skipped outcomes — at a
  detail level sufficient for post-run diagnosis.

### Key Entities

- **Run Record**: The complete record of a single automation run — event trigger, timestamp,
  list of skill invocations with results, and outcome decisions. Stored and queryable.
- **Outcome**: The system's response to a completed skill result. One of: block (abort git
  operation with message), warn (emit visible message, proceed), or skip (proceed silently,
  log only).
- **Outcome Rule**: A configured mapping that determines which outcome applies to a skill
  under what conditions (e.g., "apply block when skill X returns a failure result").
- **Run History**: The ordered collection of recent run records retained in the repository
  for developer inspection.
- **Diagnostic Detail**: The per-skill entry in the run record containing enough information
  to reproduce and diagnose the result — input context summary, output summary, matched
  outcome rule, and applied outcome.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A developer can determine what happened in the most recent automation run —
  which skills ran, their statuses, and the outcome applied — within one minute of the run
  completing, using only the run record.
- **SC-002**: 100% of automation runs produce a run record, including empty plans, fully
  skipped runs, and runs interrupted by errors.
- **SC-003**: A developer can identify the exact skill output and outcome rule responsible
  for any block or warn outcome by reading the diagnostic detail in the run record, without
  running additional commands.
- **SC-004**: Outcome enforcement is correct in 100% of tested cases — block always aborts,
  warn always proceeds with message, skip always proceeds silently.
- **SC-005**: Changing an outcome rule in configuration takes effect on the next automation
  run with no reinstallation — verified by a configuration change followed by a triggered
  run.

## Assumptions

- The default outcome when no rule is configured is warn (not block). This preserves the
  constitution's "safe by default" principle — the system does not block git operations
  without explicit configuration.
- Block outcomes are only meaningful for pre-commit and pre-push hook events, where the git
  operation has not yet completed. For post-merge events, block outcomes are downgraded to
  warn automatically, since the merge has already occurred.
- Run records are stored as files in a designated directory within the repository. The
  retention limit (how many records are kept) is a configuration setting with a default of
  50 most recent runs.
- Outcome rules are defined in the routing configuration alongside workflow/skill mappings.
  A separate outcome rules file is out of scope for this feature.
- The run record is written after all skills in the plan have completed. Partial records
  (for interrupted runs) are written on a best-effort basis.
- "Visible message" for warn and block outcomes means output to the developer's terminal
  at the time of the git operation — not a background notification or a file they must
  separately open.
- Diagnostic detail includes a summary of the context and skill output, not the full
  raw contents. Full raw output is available in the run log file if needed.
