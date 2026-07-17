# Data Model: Skill Contract

**Branch**: `005-skill-contract` | **Date**: 2026-07-16

## Entity: SkillManifest (`skills/<dir>/skill.json`)

See [contracts/skill-contract.md](./contracts/skill-contract.md) — six required fields
(name, version, description, input, output, behaviors) + executable `run` beside it.

## Entity: SkillRegistry (`skills/registry.json`)

| Field | Type | Rules |
|-------|------|-------|
| `contract_version` | string | contract version the registry was last written under |
| `skills` | object | name → entry |
| `skills.<name>.dir` | string | directory under `skills/` |
| `skills.<name>.version` | string | manifest version at registration |
| `skills.<name>.description` | string | copied from manifest |

Missing/corrupt registry file: read as empty catalog with warning (mirrors 004 config
handling); writes always produce the full valid shape.

## Entity: RegistrationResult

| Outcome | Exit | Payload |
|---------|------|---------|
| accepted | 0 | `registered '<name>' (contract 1.0)` |
| rejected | 1 | one line per violation: `violation: <rule-name> — <explanation>` (complete list, SC-003) |

Violation rule names: `missing-manifest`, `name`, `name-reserved`, `version`,
`description`, `input`, `output`, `behaviors`, `entry-point`, `duplicate-name`.

## Entity: ValidationReport (`validate` command)

Per registered skill: `ok` or list of violated rule names; plus registry-level
`contract-version-drift` notice when stored ≠ current. Exit 1 if any skill non-compliant.

## Resolution flow (router, replaces 004 provisional)

```text
route_workflows.make_skills_invoker(skills_dir)
  → load <skills_dir>/registry.json
  → identifier in registry?  no → unresolvable ("not registered")
  → <skills_dir>/<dir>/run executable?  no → unresolvable ("entry point missing")
  → run with context JSON on stdin → invoked / failed (exit code)
```
