# Feature Specification: Claude Code Bridge

**Feature Branch**: `007-claude-code-bridge`
**Created**: 2026-04-09
**Status**: Draft
**Input**: User description: "Bridges local Git-triggered automation with Claude Code skills,
settings, and optional hook-based enhancements."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Skill Invokes Claude Code From Automation (Priority: P1)

When a registered skill executes as part of a git-triggered automation run, it can invoke
Claude Code to perform analysis or generate documentation. The bridge provides the
connection so that any skill can call Claude Code with the right context without implementing
its own Claude Code integration.

**Why this priority**: Claude Code is the documentation engine for this system (per
constitution principle 3). Without a bridge that any skill can use, each skill would need
to independently solve the problem of invoking Claude Code — creating duplication, drift,
and inconsistency.

**Independent Test**: Author a skill that uses the bridge to invoke Claude Code with a
bounded context derived from a hook event. Verify Claude Code is called with the correct
input, returns a result, and the bridge passes that result back to the skill without
transformation.

**Acceptance Scenarios**:

1. **Given** a skill is executing and needs Claude Code to process a bounded context,
   **When** the skill invokes the bridge,
   **Then** the bridge calls Claude Code with the supplied context and returns Claude Code's
   output to the skill.

2. **Given** Claude Code is unavailable or returns an error,
   **When** the bridge attempts the invocation,
   **Then** it returns a structured error to the skill rather than crashing — the skill
   decides whether to fail, retry, or skip.

3. **Given** the bridge is invoked with a context derived from the hook parser,
   **When** Claude Code processes it,
   **Then** the context passed is bounded to the change set — not the entire repository.

---

### User Story 2 - Bridge Reads Existing Claude Code Settings Without Duplication (Priority: P2)

The bridge reads the project's existing Claude Code configuration (settings and project
guidance files) so that automation respects the established Claude Code setup. Developers
do not need to maintain a separate configuration for the automation system.

**Why this priority**: If the bridge ignores Claude Code settings, automated invocations
may contradict the project's established Claude Code behavior — producing inconsistent
outputs. Reading existing settings ensures automation and interactive Claude Code use behave
consistently.

**Independent Test**: Configure a project guidance file that constrains Claude Code's
behavior (e.g., scope limitations or output format preferences). Invoke the bridge from a
skill. Verify the bridge-initiated Claude Code call respects those settings, producing
output consistent with interactive Claude Code use on the same project.

**Acceptance Scenarios**:

1. **Given** the project has an existing Claude Code configuration in place,
   **When** the bridge invokes Claude Code,
   **Then** the configuration is applied to the automated invocation — the same constraints
   and guidance govern both interactive and automated Claude Code calls.

2. **Given** the project's Claude Code configuration changes,
   **When** the next automated invocation occurs via the bridge,
   **Then** the updated configuration is used — no bridge reinstallation or manual sync
   required.

---

### User Story 3 - Claude Code Hook Enhancements Are Opt-In (Priority: P3)

Developers who use Claude Code's hook system can optionally connect those hooks into the
automation pipeline through the bridge. Enabling or disabling this integration requires
only a configuration change — the core automation system works correctly whether the
enhancement is on or off.

**Why this priority**: Not all projects use Claude Code hooks, and requiring them would
create unnecessary setup friction. Making this additive ensures the bridge degrades
gracefully and remains useful in the simplest project setups.

**Independent Test**: Enable Claude Code hook enhancement in the bridge configuration.
Trigger an automation run and verify the configured hook fires in addition to the core
skill invocation. Then disable the enhancement and verify the same automation run completes
correctly without the hook, with no errors.

**Acceptance Scenarios**:

1. **Given** Claude Code hook enhancement is disabled in bridge configuration,
   **When** the bridge invokes Claude Code,
   **Then** no Claude Code hooks are triggered and the invocation behaves as a standard
   bounded-context call.

2. **Given** Claude Code hook enhancement is enabled,
   **When** the bridge invokes Claude Code,
   **Then** the configured hooks are triggered as part of the invocation, and their outputs
   are included in the result returned to the skill.

3. **Given** Claude Code hook enhancement is toggled (on or off),
   **When** the change is made in configuration,
   **Then** the next automation run reflects the new setting without reinstallation.

---

### Edge Cases

- What happens when Claude Code is not installed in the environment where automation runs?
- What happens when the bridge is invoked with an empty or partial context from the parser?
- What happens when a Claude Code invocation exceeds the time budget defined by the executor?
- What happens when the project guidance file is missing or contains conflicting instructions?
- What happens when multiple skills in the same execution plan each invoke the bridge
  concurrently (even though parallel execution is out of scope for `006-skill-executor`)?

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The bridge MUST provide a single, shared invocation interface that any
  registered skill can use to call Claude Code with a bounded context.
- **FR-002**: The bridge MUST pass only the bounded context derived from the hook event to
  Claude Code — not the full repository contents.
- **FR-003**: The bridge MUST return Claude Code's structured output to the calling skill,
  or a structured error if the invocation fails.
- **FR-004**: The bridge MUST read the project's existing Claude Code settings and apply
  them to every automated invocation — no duplicate configuration file required.
- **FR-005**: The bridge MUST detect when Claude Code is not available in the environment
  and return a clear, structured "unavailable" result to the calling skill rather than
  crashing.
- **FR-006**: Claude Code hook integration MUST be opt-in and controlled by a bridge
  configuration setting. When disabled, no Claude Code hooks are triggered by automated
  invocations.
- **FR-007**: Enabling or disabling Claude Code hook integration MUST require only a
  configuration change — no reinstallation, no hook script edits.
- **FR-008**: The bridge MUST be testable in isolation — given a context and a mock Claude
  Code response, it MUST be invocable directly to verify input/output behavior without
  running a real Claude Code process.

### Key Entities

- **Bridge**: The shared component that skills use to invoke Claude Code. It encapsulates
  context preparation, settings loading, invocation, and result normalization.
- **Bounded Invocation Context**: The subset of repository and event information passed to
  Claude Code — derived from the hook context, never the full repository state.
- **Claude Code Settings**: The project's existing Claude Code configuration (settings files
  and project guidance files). The bridge reads these at invocation time.
- **Bridge Configuration**: The bridge's own settings, stored in the repository alongside
  the routing configuration. Controls opt-in features such as Claude Code hook integration.
- **Invocation Result**: The structured output returned by the bridge to the calling skill —
  either a success result containing Claude Code's output, or a failure result with an error
  description and error type (invocation error, timeout, unavailable).

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A skill author can invoke Claude Code from a registered skill using the bridge
  interface without implementing any Claude Code-specific logic in the skill itself.
- **SC-002**: 100% of automated Claude Code invocations via the bridge apply the project's
  existing Claude Code settings — no divergence between interactive and automated behavior.
- **SC-003**: When Claude Code is unavailable, 100% of bridge invocations return a
  structured "unavailable" result — zero crashes or unhandled errors propagate to the caller.
- **SC-004**: Toggling Claude Code hook enhancement on or off takes effect on the next
  automation run with no reinstallation — verified by a single configuration change.
- **SC-005**: The bounded context passed to Claude Code contains only change-set-relevant
  information — verified by confirming no full-repository scans are triggered through the
  bridge under normal operating conditions.

## Assumptions

- Claude Code is installed as a CLI tool available in the environment where automation runs.
  When not installed, the bridge returns a structured "unavailable" result.
- "Bounded context" means the subset of information derived from the hook context (changed
  file paths, event type, branch) — not a full repository snapshot. Constructing this
  bounded context is the bridge's responsibility, using the hook context as its source.
- "Claude Code settings" refers to the project-level configuration files that Claude Code
  reads when running in a project directory. The bridge reads these from their standard
  locations without requiring a separate copy.
- "Claude Code hook integration" refers to Claude Code's own hook system (hooks configured
  in Claude Code settings that fire before/after certain Claude Code operations), not the
  git hooks managed by `002-git-hook-scripts`.
- The bridge does not cache Claude Code responses between invocations. Each invocation
  produces a fresh result.
- The bridge is a component used by skills, not a standalone feature visible to end users
  directly. Its quality is measured by how reliably it serves the skills that depend on it.
- Multiple concurrent bridge invocations (if they arise despite sequential execution in
  `006-skill-executor`) are handled safely — the bridge does not maintain shared mutable
  state between invocations.
