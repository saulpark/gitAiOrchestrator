# Feature Specification: Hook Context Parser

**Feature Branch**: `003-hook-context-parser`
**Created**: 2026-04-09
**Status**: Draft
**Input**: User description: "Converts raw Git hook inputs into a structured internal context
that downstream features can consume consistently."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Consistent Context Across Hook Types (Priority: P1)

A downstream feature (such as documentation generation or change analysis) receives a
predictable, uniform context structure regardless of which git event triggered the flow.
It does not need to know whether the trigger was a commit, a merge, or a push — the
structure it receives is always the same shape.

**Why this priority**: If each hook type produces a different data shape, every downstream
feature must handle multiple formats. A consistent context is the foundational contract that
enables all downstream features to be written once and work everywhere.

**Independent Test**: Trigger the parser with inputs representative of each hook type
(pre-commit, post-merge, pre-push). Verify the output structure has the same field names,
types, and presence rules in all three cases, even where values differ.

**Acceptance Scenarios**:

1. **Given** a pre-commit event fires with a set of staged changes,
   **When** the parser processes the raw hook input,
   **Then** it produces a context object with a defined event type, current branch, and
   list of affected paths.

2. **Given** a post-merge event fires after a branch is merged,
   **When** the parser processes the raw hook input,
   **Then** it produces a context object with the same structure as a pre-commit context,
   populated with the files changed by the merge.

3. **Given** a pre-push event fires before commits are sent to a remote,
   **When** the parser processes the raw hook input,
   **Then** it produces a context object with the same structure, including the set of
   commits being pushed and their associated changed paths.

4. **Given** the parser has produced a context from any hook type,
   **When** a downstream feature reads that context,
   **Then** it can access event type, branch name, and changed file paths without
   conditional logic based on event type.

---

### User Story 2 - Sufficient Context for Downstream Processing (Priority: P2)

The structured context produced by the parser contains all the information a downstream
documentation or analysis feature needs to determine what work to do — without requiring
that feature to re-query git or re-read the repository state.

**Why this priority**: If downstream features must make additional queries to reconstruct
information the parser could have provided, the system becomes fragile and slower. The
parser is the single point where raw git data is captured and normalized.

**Independent Test**: Given a context produced by the parser for each hook type, verify
that a downstream feature can independently determine: what changed, on which branch, in
response to which event — using only the context object, without running any git commands.

**Acceptance Scenarios**:

1. **Given** a context produced from a pre-commit event,
   **When** a downstream documentation feature reads it,
   **Then** it can identify all file paths that were staged for the commit without needing
   to query git directly.

2. **Given** a context produced from a post-merge event,
   **When** a downstream feature reads it,
   **Then** it can identify the full set of files changed by the merge, including files
   from all merged commits.

3. **Given** a context produced from a pre-push event,
   **When** a downstream feature reads it,
   **Then** it can identify all commits and affected file paths being pushed, scoped to
   changes not yet on the remote.

---

### User Story 3 - Graceful Handling of Incomplete Input (Priority: P3)

When a hook provides incomplete, unexpected, or missing input (e.g., empty stdin, missing
environment variables), the parser produces a partial context with explicit markers on
missing fields rather than failing or producing a corrupt context.

**Why this priority**: Hook inputs can vary across git versions, platforms, and edge cases
(e.g., empty commits, detached HEAD). Crashing on unexpected input would break git
operations silently or unexpectedly.

**Independent Test**: Invoke the parser with intentionally incomplete hook inputs (missing
environment variables, empty stdin, unexpected format). Verify it returns a partial context
that clearly identifies which fields could not be populated, without throwing an error or
exiting non-zero.

**Acceptance Scenarios**:

1. **Given** a hook fires with missing or empty required input fields,
   **When** the parser attempts to build the context,
   **Then** it returns a partial context with affected fields marked as unavailable and a
   summary of what could not be parsed.

2. **Given** the parser returns a partial context,
   **When** a downstream feature reads it,
   **Then** it can detect which fields are unavailable and decide whether to proceed,
   skip, or request a fallback — without crashing.

---

### Edge Cases

- What happens when a commit contains no file changes (e.g., an empty commit with `--allow-empty`)?
- What happens when a merge results in no net file changes (fast-forward or already up-to-date)?
- What happens when a push contains dozens of commits spanning hundreds of files?
- What happens when git hook environment variables are not set (non-standard git environments)?
- How is context handled when the repository is in a detached HEAD state?

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The parser MUST accept raw inputs from pre-commit, post-merge, and pre-push
  hook environments and produce a context object in all three cases.
- **FR-002**: The context object MUST include at minimum: event type, current branch name,
  and a list of affected file paths.
- **FR-003**: The context schema MUST be identical across all supported hook types — same
  field names, same types, same presence rules.
- **FR-004**: The parser MUST populate affected file paths with the complete set of files
  changed by the event, scoped to the current operation (staged files for pre-commit, merged
  files for post-merge, pushed commits' files for pre-push).
- **FR-005**: The parser MUST handle missing or empty inputs without exiting with an error
  code that would abort the triggering git operation.
- **FR-006**: When input is incomplete, the parser MUST produce a partial context that
  identifies which fields are unavailable, rather than omitting the context entirely.
- **FR-007**: The parser MUST be invocable as a standalone step, independently of the hook
  scripts, to support testing and manual invocation.
- **FR-008**: The parser MUST complete within a time budget that does not meaningfully add
  latency to the triggering git operation.

### Key Entities

- **Raw Hook Input**: The unprocessed data provided to a hook by git — varies by hook type
  and includes a combination of environment variables, standard input, and command-line
  arguments.
- **Hook Context**: The normalized, structured output produced by the parser — a consistent
  representation of event type, branch, and affected file paths regardless of which hook
  triggered the flow.
- **Context Field**: A named, typed slot in the Hook Context. Fields have defined presence
  rules (required vs. optional) and a declared unavailability state for partial contexts.
- **Parse Result**: The outcome of a parse operation — either a complete context, a partial
  context with unavailability markers, or a parse error with a human-readable explanation.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A downstream feature written against the context schema works correctly when
  given output from any of the three supported hook types, with no hook-type-specific
  conditional logic required.
- **SC-002**: 100% of files changed by a git event are included in the affected paths field
  for complete input — no changes are silently dropped.
- **SC-003**: Context parsing completes in under 1 second for events affecting up to 1,000
  changed files.
- **SC-004**: All three hook types produce contexts containing the same set of base fields,
  verified by automated comparison.
- **SC-005**: Incomplete or malformed hook input never causes the parser to exit with a
  code that aborts the triggering git operation — 100% of error cases produce a partial
  context or a logged parse error.

## Assumptions

- The three supported hook types are pre-commit, post-merge, and pre-push, matching the
  hook scripts defined in `002-git-hook-scripts`. Additional hook types are out of scope.
- The context schema is defined as part of this feature and serves as the contract all
  downstream features depend on. Schema changes are a breaking change and require
  versioning.
- The parser is a standalone component invoked by hook scripts — it does not run inside
  the hook scripts themselves.
- "Affected file paths" means repository-relative paths. Absolute paths and working
  directory paths are normalized to relative paths in the output.
- For pre-push events, "affected files" means files changed in commits being pushed that
  are not yet on the remote — not all files in the pushed commits' history.
- The context is an in-memory or serialized structure passed to downstream features in
  the same process or pipeline invocation; it is not stored persistently between runs.
- Detecting an empty change set (no files changed) is a valid, non-error result and
  produces a context with an empty affected paths list.
