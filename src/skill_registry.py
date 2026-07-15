#!/usr/bin/env python3
"""Skill registry (feature 005).

Validates skill manifests against skill contract v1.0 and maintains the
catalog skills/registry.json. The workflow router resolves identifiers
through this registry. Contract (the human-readable artifact developers
consult): specs/005-skill-contract/contracts/skill-contract.md
"""
from __future__ import annotations

import json
import os
import re

CONTRACT_VERSION = "1.0"
RESERVED_NAMES = frozenset({"registry", "contract", "skills"})
REQUIRED_INPUT = "hook-context@1.0"
REQUIRED_OUTPUT = "skill-result@1.0"
_NAME_RE = re.compile(r"[a-z0-9][a-z0-9-]{0,63}")
_SEMVER_RE = re.compile(r"\d+\.\d+\.\d+")


def validate_manifest(skill_dir: str) -> list[str]:
    """Check a skill directory against contract v1.0.

    Returns a complete list of violations in one pass (SC-003), each as
    "<rule-name>: <explanation>". Empty list = compliant.
    """
    violations: list[str] = []
    manifest_path = os.path.join(skill_dir, "skill.json")
    try:
        with open(manifest_path, encoding="utf-8") as fh:
            manifest = json.load(fh)
        if not isinstance(manifest, dict):
            raise ValueError("manifest must be a JSON object")
    except (OSError, ValueError) as exc:
        return [f"missing-manifest: cannot read {manifest_path}: {exc}"]

    name = manifest.get("name")
    if not isinstance(name, str) or not _NAME_RE.fullmatch(name):
        violations.append("name: required string matching ^[a-z0-9][a-z0-9-]{0,63}$")
    elif name in RESERVED_NAMES:
        violations.append(f"name-reserved: '{name}' is a reserved identifier")

    version = manifest.get("version")
    if not isinstance(version, str) or not _SEMVER_RE.fullmatch(version):
        violations.append("version: required semver string X.Y.Z")

    description = manifest.get("description")
    if not isinstance(description, str) or not description.strip():
        violations.append("description: required non-empty string")

    if manifest.get("input") != REQUIRED_INPUT:
        violations.append(f"input: must be exactly '{REQUIRED_INPUT}'")

    if manifest.get("output") != REQUIRED_OUTPUT:
        violations.append(f"output: must be exactly '{REQUIRED_OUTPUT}'")

    behaviors = manifest.get("behaviors")
    if (not isinstance(behaviors, dict)
            or behaviors.get("non_blocking") is not True
            or not isinstance(behaviors.get("idempotent"), bool)):
        violations.append(
            "behaviors: required object with non_blocking=true and boolean idempotent")

    run_path = os.path.join(skill_dir, "run")
    if not (os.path.isfile(run_path) and os.access(run_path, os.X_OK)):
        violations.append(f"entry-point: executable 'run' missing at {run_path}")

    return violations
