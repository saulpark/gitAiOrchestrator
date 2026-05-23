# Feature Specification: Skill Executor

**Feature Branch**: `006-skill-executor`
**Created**: 2026-04-09
**Status**: Draft
**Input**: User description: "Executes configured skills in a controlled order with clear
runtime behavior and bounded scope."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Skills Execute in Order and Results Are Collected (Priority: P1)

When the workflow router dispatches a set of skills for a given event, the executor runs
each skill in the configured sequence, passes the hook context to each, and collects the
individual results into a summary that the orchestration layer can use.

**Why this priority**: Execution is what transforms the system from a routing mechanism into
one that actually performs work. Without a well-defined executor, skills are registered and
routed but never run.

**Independent Test**: Configure three skills in a specific order for an event. Trigger the
event. Verify all three skills were invoked in the declared order, each received the hook
context, and the execution summary contains a result entry for each skill.

**Acceptance Scenarios**:

1. **Given** the router dispatches an ordered list of skills for an event,
   **When** the executor receives the dispatch,
   **Then** it runs each skill in the declared order, passing the parsed hook context as
   input to each, and collects the result from each invocation.

2. **Given** all skills in the execution plan complete successfully,
   **When** the executor finishes,
   **Then** the execution summary reports a success status for each skill and an overall
   success for the plan.

3. **Given** the execution plan contains a single skill,
   **When** it completes,
   **Then** the summary contains one result entry and an overall status that reflects that
   single outcome.

---

### User Story 2 - Skill Failure or Timeout Is Isolated — Subsequent Skills Still Run (Priority: P2)

When a skill in the execution sequence fails or exceeds its allotted time budget, the
executor records the failure, moves on, and runs all remaining skills in the plan. A single
failure does not abort the entire execution.

**Why this priority**: Skills may fail for reasons unrelated to one another (network issue,
bad output, timeout). Aborting the entire plan on one failure would suppress potentially
important work done by later skills, and would introduce unpredictable behavior in the
developer's git workflow.

**Independent Test**: Configure a skill that intentionally fails or exceeds its time budget
as the first skill in a plan with two additional skills. Trigger the event. Verify the
executor records the first skill's failure and still executes the remaining two.

**Acceptance Scenarios**:

1. **Given** a skill in the execution plan exits with an error,
   **When** the executor processes that result,
   **Then** it records the failure, continues to the next skill in the plan, and the overall
   execution summary reflects a partial failure rather than an abort.

2. **Given** a skill in the execution plan exceeds its time budget,
   **When** the timeout is reached,
   **Then** the executor terminates that skill's execution, records a timeout result for it,
   and proceeds to the next skill without waiting further.

3. **Given** every skill in the plan fails,
   **When** the executor finishes,
   **Then** the summary reports failure for each skill and an overall failed status — but
   the git operation that triggered the plan is not aborted by the executor.

---

### User Story 3 - Execution Is Observable Through a Clear Summary (Priority: P3)

After execution completes, a developer or operator can inspect a structured execution
summary that shows which skills ran, what each returned, how long each took, and whether the
overall plan succeeded or failed.

**Why this priority**: Without observability, diagnosing why documentation was or wasn't
updated is guesswork. The summary is the primary debugging and audit artifact for the
automation system.

**Independent Test**: Trigger an event that runs a plan with a mix of successful and failed
skills. Inspect the execution summary. Verify it contains, for each skill: name, status
(success/failure/timeout/skipped), result or error description, and duration.

**Acceptance Scenarios**:

1. **Given** an execution plan has completed (fully or partially),
   **When** a developer inspects the execution summary,
   **Then** they can see for each skill: its name, its outcome (success, failure, timeout,
   or skipped), the duration of its execution, and a human-readable description of any
   error or result.

2. **Given** the execution summary is produced,
   **When** reviewed,
   **Then** it contains an overall status that accurately reflects whether all skills
   succeeded, some failed, or all failed.

3. **Given** the summary is available after execution,
   **When** the orchestration layer reads it,
   **Then** it can determine which skills produced outputs worth acting on and which require
   attention — without re-running any skill.

---

### Edge Cases

- What happens when the execution plan is empty (no skills dispatched)?
- What happens when the hook context passed to a skill is a partial context (from
  `003-hook-context-parser`)?
- What happens when a skill produces output that does not conform to the declared output
  shape — is it treated as a failure?
- What happens when the executor itself encounters a system-level error (e.g., out of
  memory, process crash)?
- What happens when a skill is listed multiple times in the same execution plan?

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The executor MUST accept an ordered list of skill identifiers (an execution
  plan) and the hook context, and invoke each skill in the declared order.
- **FR-002**: The executor MUST pass the hook context as input to each skill, unmodified
  from the form produced by `003-hook-context-parser`.
- **FR-003**: The executor MUST continue executing remaining skills in the plan when any
  individual skill fails, exits with an error, or times out.
- **FR-004**: The executor MUST enforce a per-skill time budget and terminate any skill that
  exceeds it, recording a timeout result for that skill.
- **FR-005**: The executor MUST produce an execution summary after the plan completes,
  containing for each skill: name, status (success/failure/timeout/skipped), duration, and
  error or result description.
- **FR-006**: The execution summary MUST include an overall plan status: success (all
  skills succeeded), partial failure (some failed), or failure (all failed).
- **FR-007**: The executor MUST NOT exit with a code that would abort the triggering git
  operation, regardless of how many skills failed.
- **FR-008**: The executor MUST handle an empty execution plan gracefully, producing a
  summary that reflects zero skills were run.
- **FR-009**: The executor MUST be invocable in isolation given a plan and a context, to
  support testing without triggering a real git operation.

### Key Entities

- **Execution Plan**: The ordered list of skill identifiers, derived from the routing
  configuration for a given event. The executor works from this list top to bottom.
- **Skill Invocation**: A single call to a registered skill with the hook context as input
  and a result (or error/timeout) as output.
- **Execution Result**: The outcome of a single skill invocation — one of: success (with
  output), failure (with error description), timeout, or skipped (e.g., skill not found).
- **Execution Summary**: The complete record of an execution plan run — all individual
  results plus an overall status and total duration.
- **Time Budget**: The maximum wall-clock time allocated to a single skill invocation before
  the executor terminates it. The budget is defined per skill in the skill contract or
  overridden in the routing configuration.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: All skills in an execution plan are invoked in the declared order, verified by
  comparing execution summary order with plan order — 100% of plans produce results in
  declared sequence.
- **SC-002**: A single skill failure never prevents subsequent skills from running — verified
  by a plan where skill 1 fails and skills 2 and 3 still produce results.
- **SC-003**: 100% of execution plans produce an execution summary, including plans with
  zero skills, all failures, and all timeouts.
- **SC-004**: A git operation is never aborted solely because of an executor failure — the
  git operation's own exit behavior is unaffected by skill execution outcomes.
- **SC-005**: The execution summary is available within 500 milliseconds of the last skill
  completing, without additional developer action.

## Assumptions

- The executor receives an already-resolved execution plan (list of skill identifiers) from
  the workflow router. Skill resolution from identifiers to executable units is handled by
  the skill registry (`005-skill-contract`); the executor does not perform its own lookup.
- The per-skill time budget has a system default (assumed to be 30 seconds unless overridden)
  that applies when no skill-specific or route-specific budget is configured.
- Skills run sequentially by default. Parallel execution is out of scope for this feature.
- The execution summary is an in-session artifact used by the orchestration layer and
  displayed to the developer. It is not stored persistently beyond the current git operation
  session.
- The executor does not modify the hook context between skill invocations — each skill
  receives the same original context.
- Output produced by one skill is not automatically passed as input to the next skill in the
  plan. Inter-skill data passing is out of scope for this feature.
- A "skipped" status is recorded when a skill identifier in the plan cannot be resolved in
  the registry at execution time (complement to the warning emitted by the router in
  `004-workflow-router`).
