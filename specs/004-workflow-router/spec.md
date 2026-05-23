# Feature Specification: Workflow Router

**Feature Branch**: `004-workflow-router`
**Created**: 2026-04-09
**Status**: Draft
**Input**: User description: "Selects workflows and skills dynamically from configuration
instead of embedding routing logic inside hook scripts."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Config-Driven Workflow Dispatch (Priority: P1)

When a git event fires and the context has been parsed, the router reads the project's
routing configuration and invokes the workflows or skills mapped to that event type. No
routing logic lives in the hook scripts — they only call the router.

**Why this priority**: This is the core value of the feature. Without config-driven dispatch,
changing which workflows run requires editing hook scripts — a fragile, error-prone process.
The router is what makes the system reconfigurable without code changes.

**Independent Test**: Create a routing configuration that maps pre-commit to workflow A and
post-merge to workflow B. Fire each event and verify workflow A runs for pre-commit, workflow
B runs for post-merge, and neither workflow runs for the other event.

**Acceptance Scenarios**:

1. **Given** a routing configuration maps a specific event type to one or more workflows,
   **When** the router receives a context for that event type,
   **Then** it invokes each mapped workflow in the configured order with the parsed context
   as input.

2. **Given** a routing configuration maps an event to multiple workflows,
   **When** the router processes that event,
   **Then** all mapped workflows are invoked, and the result of each is reported independently.

3. **Given** a routing configuration exists with no logic embedded in hook scripts,
   **When** a new workflow needs to be added to an existing event,
   **Then** only the configuration file is updated — no hook script is modified.

---

### User Story 2 - Developer Reconfigures Workflows via Configuration File (Priority: P2)

A developer can change which workflows run on which git events by editing a single
configuration file in the repository. The change takes effect on the next git operation
without any reinstallation or hook modification.

**Why this priority**: The ability to reconfigure without touching code is the principal
maintainability benefit. If configuration changes require reinstallation or script edits,
the routing system is no better than hardcoded hooks.

**Independent Test**: Modify the routing configuration to add a new workflow mapping for an
event type. Trigger that event. Verify the new workflow runs without any other files being
changed and without re-running the installer.

**Acceptance Scenarios**:

1. **Given** the router is installed and a routing configuration is in place,
   **When** a developer edits the configuration to add, remove, or change a workflow mapping,
   **Then** the next git operation reflects the updated routing — no installer re-run, no
   hook file edits required.

2. **Given** a developer removes a workflow mapping from the configuration,
   **When** the previously-mapped event fires,
   **Then** no workflow is invoked for that event and the git operation proceeds normally.

---

### User Story 3 - Graceful Handling of Unconfigured Events and Missing Workflows (Priority: P3)

When the router encounters an event type with no configuration entry, or a configured
workflow identifier that cannot be resolved, it skips execution or logs a clear warning
rather than aborting the git operation.

**Why this priority**: Partial configuration and workflow availability changes are normal
during setup and maintenance. The system must degrade gracefully so developers are never
blocked by a missing or misconfigured workflow.

**Independent Test**: Configure the router with a mapping that references a non-existent
workflow. Trigger the associated event. Verify the git operation completes and the developer
receives a visible warning about the unresolvable workflow — no abort, no silent failure.

**Acceptance Scenarios**:

1. **Given** a git event fires with no matching entry in the routing configuration,
   **When** the router processes the event,
   **Then** it skips dispatch, logs that no workflows are configured for that event, and
   the git operation continues.

2. **Given** a routing configuration references a workflow or skill that cannot be found,
   **When** the router attempts to dispatch it,
   **Then** it emits a visible warning with the unresolvable workflow identifier and
   continues without aborting the git operation.

---

### Edge Cases

- What happens when the routing configuration file is missing entirely?
- What happens when the configuration file exists but is empty or contains no route entries?
- What happens when the configuration file is malformed (syntax errors)?
- What happens when two routes match the same event type — are both invoked, or only the first?
- What happens when a workflow invocation fails midway through — do subsequent mapped
  workflows still run?

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The router MUST read workflow mappings from a versioned configuration file in
  the repository, not from hook scripts or hardcoded logic.
- **FR-002**: The router MUST support mapping any supported event type (pre-commit,
  post-merge, pre-push) to one or more workflow or skill identifiers.
- **FR-003**: The router MUST invoke all workflows mapped to a triggered event type, passing
  the parsed hook context as input to each.
- **FR-004**: The router MUST NOT abort the triggering git operation when a configured
  workflow is unavailable or fails to execute.
- **FR-005**: The router MUST emit a visible warning when a configured workflow cannot be
  resolved or fails, identifying the workflow by its configured name.
- **FR-006**: The router MUST skip dispatch silently (with a log entry) when an event fires
  with no matching configuration entry.
- **FR-007**: The router MUST reload the configuration on each invocation — configuration
  changes MUST take effect on the next git operation without reinstallation.
- **FR-008**: The router MUST handle a missing or malformed configuration file without
  aborting the git operation, treating it as an empty configuration with a logged warning.
- **FR-009**: The router MUST be testable in isolation — given a context and a configuration,
  it MUST be invocable directly to verify dispatch behavior without triggering a real git
  operation.

### Key Entities

- **Routing Configuration**: A versioned file in the repository that defines the mapping
  from event types to workflow or skill identifiers. This is the sole source of routing
  truth.
- **Route**: A single entry in the routing configuration — an event type mapped to one or
  more workflow identifiers, with an optional execution order.
- **Workflow Identifier**: A name or reference used in the configuration to designate a
  specific workflow or skill to invoke. Resolution of identifiers to executable units is
  handled by the invocation layer.
- **Dispatch Result**: The outcome of a router invocation — a list of workflows attempted,
  their individual outcomes (invoked, skipped, unresolvable, failed), and any warnings
  produced.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Adding, removing, or changing a workflow mapping requires editing only the
  routing configuration file — zero hook script modifications needed — verified by a
  configuration-only change that alters dispatch behavior.
- **SC-002**: 100% of event types with matching configuration entries result in the mapped
  workflows being invoked, with no silently dropped dispatches.
- **SC-003**: 100% of dispatch failures (unresolvable workflow, execution error) produce a
  visible warning to the developer — no failure is silent.
- **SC-004**: A git operation is never aborted solely because of a routing failure — the
  exit behavior of the git operation is always determined by the git operation itself, not
  by the router.
- **SC-005**: The router processes a routing configuration and selects workflows in under
  100 milliseconds, adding no perceptible latency to the developer's git workflow.

## Assumptions

- The routing configuration is a file that lives in the repository and is versioned alongside
  the code it governs. Its exact format (YAML, TOML, JSON) is an implementation detail for
  planning.
- Each route maps exactly one event type to one or more workflow identifiers. Wildcard or
  pattern-based event matching is out of scope for this feature.
- When multiple workflows are mapped to the same event, they are invoked sequentially in
  configuration order by default. Parallel invocation is out of scope for this feature.
- If a workflow fails, subsequent workflows mapped to the same event still run — failures
  are isolated per workflow, not per event.
- "Workflow" and "skill" are used interchangeably in this spec to mean an executable unit
  the router can invoke by identifier. The distinction between workflow types is an
  implementation detail.
- The router depends on the hook context structure defined in `003-hook-context-parser` as
  its input contract.
- The router does not itself execute workflows — it selects them and hands off to an
  invocation layer. The invocation layer is out of scope for this feature.
