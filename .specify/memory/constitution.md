# Project Constitution

## Purpose
This project exists to keep technical documentation aligned with source code changes through event-driven, incremental automation using Git hooks, Claude Code hooks, and Spec Kit governed workflows.

## Core Principles

### 1. Incremental First
Documentation updates must be based on the smallest valid change set, using Git diffs, changed paths, commit ranges, or patch context.
Full repository scans are forbidden unless explicitly requested for migration, repair, or baseline regeneration.

### 2. Git Is The Change Authority
Git events are the canonical trigger for detecting repository changes.
Push events must determine what changed before any documentation agent runs.

### 3. Claude Is The Documentation Engine
Claude Code may analyze changed files, generate or update documentation, validate consistency, and propose edits.
Claude Code must receive bounded context derived from the detected change set and must not operate on the entire repository by default.

### 4. Spec Before Automation
Any new automation flow must be defined through Spec Kit artifacts before implementation.
Each spec must define trigger source, input context, affected documentation targets, exclusion rules, success criteria, and failure handling.

### 5. Deterministic And Reviewable Outputs
Automated documentation changes must be reproducible from the same repository state and inputs.
Generated changes must be written as normal file diffs that can be reviewed, committed, reverted, or rejected by a developer.

### 6. Safe By Default
Automation must never silently overwrite unrelated documentation.
When confidence is low, the system must propose changes for review instead of applying destructive edits automatically.

### 7. Documentation Scope Rules
Only documentation affected by code, contract, schema, workflow, configuration, or behavioral changes may be updated.
Unrelated files must not be rewritten for style-only drift unless explicitly requested.

### 8. Explicit Exclusions
Generated folders, vendored code, lockfiles, build artifacts, caches, binaries, and temporary files must be excluded from documentation analysis unless a spec explicitly overrides this.

### 9. Validation Required
Every documentation update workflow must include validation.
Validation must check at minimum: target files exist, links or references remain valid when applicable, and generated docs map to the detected change scope.

### 10. Human Oversight
No automation path may assume generated documentation is correct without review.
The system must support human approval, diff inspection, and rollback at every critical boundary.

## Engineering Standards

### 11. Small Composable Scripts
Hooks and automation entrypoints must be implemented as small composable scripts with clear inputs and outputs.
Business logic must not be embedded directly in hook configuration when it can be placed in versioned scripts.

### 12. Structured Inputs And Outputs
All hook-driven automation must exchange structured data whenever possible.
Git-derived change sets, Claude inputs, and validation results should be represented in machine-readable form.

### 13. Idempotent Workflows
Running the same workflow multiple times on the same repository state must not create duplicate or compounding changes.

### 14. Observable Execution
Every automation run must emit enough logs or status output to explain why it ran, what scope it selected, what files it changed, and why it failed if it fails.

## Spec Kit Governance

### 15. Constitution Overrides Convenience
If a requested implementation conflicts with this constitution, the constitution wins.
Specs, plans, and tasks must explicitly show compliance with these principles before implementation proceeds.

### 16. Keep The Constitution Stable
This constitution defines long-lived project law.
Implementation details belong in specs and plans unless they are truly universal and non-negotiable.