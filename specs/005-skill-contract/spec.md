# Feature Specification: Skill Contract

**Feature Branch**: `005-skill-contract`
**Created**: 2026-04-09
**Status**: Draft
**Input**: User description: "Defines what a skill is, how it is registered, and what contract
it must satisfy to participate in automated workflows."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Register a Skill and Make It Discoverable (Priority: P1)

A developer creates a new skill that follows the defined contract, registers it with the
system, and the workflow router can immediately discover and invoke it by name — no changes
to hook scripts, routing configuration, or other system components required.

**Why this priority**: Skills are the unit of automation in this system. Until the contract
and registration mechanism are defined, no skill can be written in a way that reliably
integrates with the router. This is the foundational plug-in model.

**Independent Test**: Author a minimal skill that satisfies the contract. Register it.
Configure the router to dispatch to it by name for a specific event. Trigger the event and
verify the skill is invoked with the hook context as input and produces a result the system
can process.

**Acceptance Scenarios**:

1. **Given** a skill definition that satisfies all contract requirements,
   **When** the skill is registered,
   **Then** the skill appears in the registry under its declared name and is immediately
   available for dispatch by the workflow router.

2. **Given** a registered skill is mapped to an event in the routing configuration,
   **When** that event fires,
   **Then** the router resolves the skill by name from the registry and invokes it with the
   parsed hook context.

3. **Given** a registered skill completes execution,
   **When** it returns its result,
   **Then** the result conforms to the output contract and is consumable by the orchestration
   layer without additional transformation.

---

### User Story 2 - Invalid Skill Registration Is Rejected with Specific Feedback (Priority: P2)

When a developer registers a skill that does not satisfy the contract — missing required
metadata, wrong input/output shape, or absent required behaviors — the registration is
rejected and the developer receives a specific list of which contract requirements failed.

**Why this priority**: Without enforcement, contract violations accumulate silently until
runtime failures occur during live git operations. Catching violations at registration time
protects all downstream consumers.

**Independent Test**: Attempt to register a skill with each required contract field missing
or malformed, one at a time. Verify each attempt is rejected with a message that identifies
the specific violated requirement by name.

**Acceptance Scenarios**:

1. **Given** a skill definition is missing a required contract field,
   **When** registration is attempted,
   **Then** the registration is rejected and the error message identifies the missing field
   by name.

2. **Given** a skill definition has all required fields but declares an incompatible input
   or output shape,
   **When** registration is attempted,
   **Then** the registration is rejected with an explanation of the contract mismatch.

3. **Given** a registration is rejected,
   **When** the developer corrects the identified issues and re-registers,
   **Then** the corrected skill is accepted and added to the registry.

---

### User Story 3 - Contract Is Inspectable Without Registering a Skill (Priority: P3)

A developer who wants to write a new skill can inspect the skill contract definition to
understand exactly what their skill must accept, produce, and do — before writing any code.
The contract is a standalone, human-readable artifact.

**Why this priority**: If the contract can only be understood by attempting registration and
reading error messages, it creates a poor authoring experience and increases the chance of
contract misunderstanding. A discoverable contract spec accelerates correct skill authoring.

**Independent Test**: Without registering anything, query or read the skill contract
definition. Verify it describes all required fields, acceptable input shapes, required output
fields, and mandatory behavioral constraints in a form a developer can act on directly.

**Acceptance Scenarios**:

1. **Given** the system is installed,
   **When** a developer inspects the skill contract definition,
   **Then** they can read a complete description of: required metadata fields, the input
   structure a skill must accept, the output structure it must produce, and any behavioral
   rules it must follow.

2. **Given** the contract definition is updated (e.g., a new required field is added),
   **When** a previously registered skill no longer satisfies the new contract,
   **Then** the system identifies the non-compliant skill and surfaces the compliance gap.

---

### Edge Cases

- What happens when two skills are registered with the same name?
- What happens when a skill is registered that has a name matching a built-in or reserved
  identifier?
- What happens when a registered skill is later removed — does the registry reflect the
  removal, and how are router configurations that reference it affected?
- What happens when the contract itself is updated — are existing registered skills
  re-validated, or only on next registration?
- What happens when a skill's output does not match the declared output shape at runtime?

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The system MUST define a skill contract that specifies: required metadata
  fields (at minimum a unique name and a version), the input structure a skill must accept,
  the output structure it must produce, and any behavioral requirements (e.g., non-blocking,
  idempotent).
- **FR-002**: The system MUST provide a registration mechanism through which a skill
  definition is validated against the contract and added to the registry if compliant.
- **FR-003**: Registration MUST be rejected if any required contract field is absent,
  malformed, or incompatible, with an error message identifying each violated requirement
  by name.
- **FR-004**: The registry MUST be queryable by name so the workflow router can resolve a
  skill identifier to an executable unit.
- **FR-005**: The skill contract definition MUST be a standalone, human-readable artifact
  that a developer can consult before writing a skill.
- **FR-006**: The system MUST prevent duplicate registration under the same skill name;
  re-registration of an existing name MUST either update the entry with explicit intent or
  be rejected.
- **FR-007**: The system MUST support deregistration — removing a skill from the registry
  — and MUST surface a warning when the removed skill is referenced in the routing
  configuration.
- **FR-008**: The system MUST validate registered skills against the current contract
  whenever the contract version changes, and report any skills that no longer comply.

### Key Entities

- **Skill**: A named, versioned, registered executable unit that accepts a hook context as
  input and produces a structured result as output, satisfying all contract requirements.
- **Skill Contract**: The authoritative definition of what every skill must declare and
  exhibit — covering metadata requirements, input shape, output shape, and behavioral rules.
  The contract is versioned and is the single source of truth for skill compliance.
- **Skill Registry**: The catalog of all registered, contract-compliant skills. The workflow
  router uses the registry to resolve skill names to executable units at dispatch time.
- **Registration Result**: The outcome of a registration attempt — success (skill added to
  registry) or failure (list of specific contract violations that prevented registration).
- **Contract Version**: A version identifier for the skill contract itself. A contract
  version change triggers re-validation of all registered skills.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A developer following the skill contract definition can author and register a
  compliant skill on the first attempt, without needing to attempt registration to discover
  requirements.
- **SC-002**: 100% of registration attempts with contract violations are rejected — no
  non-compliant skill enters the registry.
- **SC-003**: Each registration rejection message identifies every violated requirement by
  name — a developer receives complete feedback in a single rejection, not incrementally.
- **SC-004**: The workflow router successfully resolves 100% of skill names present in the
  registry — no registered skill is unreachable by name.
- **SC-005**: A contract version update that introduces a new required field is detectable
  across all registered skills within one registry scan, with non-compliant skills reported
  by name.

## Assumptions

- Skills are the primary extensibility unit of the system — any new automated behavior is
  added by authoring and registering a skill, not by modifying existing system components.
- The skill contract is defined once and evolves with versioning. Breaking contract changes
  (removing or redefining required fields) require a major contract version increment.
- The registry is local to the repository installation. Skills registered in one repository
  are not shared across repositories unless explicitly copied or distributed.
- A skill's input is always a hook context as defined by `003-hook-context-parser`. Skills
  do not define their own arbitrary input shapes; they receive the standard context.
- A skill's output shape is defined by the contract and is the same for all skills —
  varying only in the content of result fields, not in field presence.
- The invocation of a skill (actually running it) is handled by a separate invocation layer;
  this spec covers only definition, registration, and discoverability.
- "Behavioral requirements" in the contract (e.g., non-blocking, idempotent) are declared
  by the skill author and trusted at registration time; runtime enforcement is out of scope
  for this feature.
