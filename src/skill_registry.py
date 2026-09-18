#!/usr/bin/env python3
"""Skill registry (feature 005).

Validates skill manifests against skill contract v1.0 and maintains the
catalog skills/registry.json. The workflow router resolves identifiers
through this registry. Contract (the human-readable artifact developers
consult): specs/005-skill-contract/contracts/skill-contract.md
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys

CONTRACT_VERSION = "1.1"   # 1.0 + optional time_budget_seconds (feature 006)
MAX_TIME_BUDGET_SECONDS = 600
# Names that would collide with registry/tooling concepts on disk or in the CLI.
RESERVED_NAMES = frozenset({"registry", "contract", "skills"})
# Pinned schema versions: a skill must declare exactly the context it is handed
# and the result shape the executor knows how to read.
REQUIRED_INPUT = "hook-context@1.0"
REQUIRED_OUTPUT = "skill-result@1.0"
_NAME_RE = re.compile(r"[a-z0-9][a-z0-9-]{0,63}")  # safe as a dir/CLI token
_SEMVER_RE = re.compile(r"\d+\.\d+\.\d+")


def validate_manifest(skill_dir: str) -> list[str]:
    """Check a skill directory against contract v1.0.

    Returns a complete list of violations in one pass (SC-003), each as
    "<rule-name>: <explanation>". Empty list = compliant.

    One pass, not fail-fast: an author fixing a manifest should see everything
    that is wrong with it at once. The only early return is an unreadable
    manifest, where no further rule can be meaningfully checked.
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

    # non_blocking must be literally true: a skill declares up front that it
    # cannot hang the git operation. Blocking is the operator's decision, made
    # in routes.json (feature 008), never the skill's.
    behaviors = manifest.get("behaviors")
    if (not isinstance(behaviors, dict)
            or behaviors.get("non_blocking") is not True
            or not isinstance(behaviors.get("idempotent"), bool)):
        violations.append(
            "behaviors: required object with non_blocking=true and boolean idempotent")

    # Optional (contract 1.1). isinstance(True, int) is True in Python, so
    # bools are excluded explicitly — "time_budget_seconds": true is nonsense.
    budget = manifest.get("time_budget_seconds")
    if budget is not None and not (
            isinstance(budget, (int, float)) and not isinstance(budget, bool)
            and 0 < budget <= MAX_TIME_BUDGET_SECONDS):
        violations.append(
            f"time-budget: time_budget_seconds must be a number in "
            f"(0, {MAX_TIME_BUDGET_SECONDS}] when present")

    # The one entry point the executor knows how to call. Executability is part
    # of the contract: a non-executable run file is a broken skill, not a skill.
    run_path = os.path.join(skill_dir, "run")
    if not (os.path.isfile(run_path) and os.access(run_path, os.X_OK)):
        violations.append(f"entry-point: executable 'run' missing at {run_path}")

    return violations


def _registry_path(skills_dir: str) -> str:
    return os.path.join(skills_dir, "registry.json")


def load_registry(skills_dir: str, warnings: list[str]) -> dict:
    """Read skills/registry.json, degrading to an empty catalog on any problem.

    A missing or corrupt registry means "no skills registered" — the pipeline
    then routes to nothing, which is the safe state.
    """
    empty = {"contract_version": CONTRACT_VERSION, "skills": {}}
    path = _registry_path(skills_dir)
    try:
        with open(path, encoding="utf-8") as fh:
            reg = json.load(fh)
        if not isinstance(reg, dict) or not isinstance(reg.get("skills"), dict):
            raise ValueError("registry must be an object with a 'skills' object")
    except FileNotFoundError:
        warnings.append(f"registry not found: {path}")
        return empty
    except (OSError, ValueError) as exc:
        warnings.append(f"registry unreadable ({path}): {exc}")
        return empty
    reg.setdefault("contract_version", CONTRACT_VERSION)
    return reg


def _save_registry(skills_dir: str, registry: dict) -> None:
    """Write the catalog back, stamped with the contract version it was
    validated against. sort_keys + indent keep diffs reviewable in git."""
    registry["contract_version"] = CONTRACT_VERSION
    os.makedirs(skills_dir, exist_ok=True)
    with open(_registry_path(skills_dir), "w", encoding="utf-8") as fh:
        json.dump(registry, fh, indent=2, sort_keys=True)
        fh.write("\n")


def register_skill(skills_dir: str, skill_dir: str,
                   update: bool = False) -> tuple[bool, list[str]]:
    """Validate and add a skill. Returns (accepted, messages).

    On rejection, messages is the complete violation list (SC-003) and the
    registry is left untouched (SC-002).
    """
    # Validate before touching the catalog: a rejected skill must leave no
    # trace, so the registry can never contain a non-compliant entry.
    violations = validate_manifest(skill_dir)
    if violations:
        return False, violations

    with open(os.path.join(skill_dir, "skill.json"), encoding="utf-8") as fh:
        manifest = json.load(fh)
    name = manifest["name"]

    # Re-registering silently would let one skill shadow another with the same
    # name; --update makes overwriting an explicit act.
    registry = load_registry(skills_dir, [])
    if name in registry["skills"] and not update:
        return False, [f"duplicate-name: '{name}' is already registered "
                       f"(pass --update to re-register with intent)"]

    # Only the basename is stored: entries stay valid whatever path the
    # register command was run from, and resolution is always skills/<dir>.
    registry["skills"][name] = {
        "dir": os.path.basename(os.path.normpath(skill_dir)),
        "version": manifest["version"],
        "description": manifest["description"],
    }
    _save_registry(skills_dir, registry)
    return True, [f"registered '{name}' (contract {CONTRACT_VERSION})"]


def deregister_skill(skills_dir: str, name: str,
                     routes_path: str | None) -> tuple[bool, list[str]]:
    """Remove a skill; warn when the routing config still references it (FR-007)."""
    registry = load_registry(skills_dir, [])
    if name not in registry["skills"]:
        return False, [f"'{name}' is not registered"]
    del registry["skills"][name]
    _save_registry(skills_dir, registry)

    # Deregistering does not edit routes.json — that is the operator's file.
    # Instead, warn about the dangling reference so it can be cleaned up; at
    # run time the executor would simply report the skill as "skipped".
    warnings: list[str] = []
    if routes_path and os.path.isfile(routes_path):
        try:
            with open(routes_path, encoding="utf-8") as fh:
                routes = json.load(fh).get("routes", {})
            events = [e for e, wfs in routes.items()
                      if isinstance(wfs, list) and name in wfs]
            if events:
                warnings.append(
                    f"'{name}' is still referenced in {routes_path} "
                    f"for events: {', '.join(sorted(events))}")
        except (OSError, ValueError):
            pass
    return True, warnings


def validate_registry(skills_dir: str) -> dict:
    """Re-validate every registered skill against the current contract (FR-008).

    Skills are validated at registration time, but the contract itself evolves
    and skill directories are edited afterwards — this is the drift check.
    """
    warnings: list[str] = []
    registry = load_registry(skills_dir, warnings)
    report = {
        "contract_version_drift":
            registry.get("contract_version") != CONTRACT_VERSION,
        "skills": {},
    }
    for name, entry in registry["skills"].items():
        skill_dir = os.path.join(skills_dir, entry.get("dir", name))
        report["skills"][name] = validate_manifest(skill_dir)
    return report


def main(argv: list[str] | None = None) -> int:
    """CLI: register / deregister / resolve / list / validate.

    Exit 0 = success, 1 = rejected or non-compliant, so these commands compose
    in shell scripts and CI.
    """
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--skills-dir", default="skills")
    parser = argparse.ArgumentParser(
        description="Skill registry — contract: "
                    "specs/005-skill-contract/contracts/skill-contract.md")
    sub = parser.add_subparsers(dest="command", required=True)
    p_reg = sub.add_parser("register", parents=[common])
    p_reg.add_argument("skill_dir")
    p_reg.add_argument("--update", action="store_true")
    p_dereg = sub.add_parser("deregister", parents=[common])
    p_dereg.add_argument("name")
    p_dereg.add_argument("--routes", default="config/routes.json")
    p_res = sub.add_parser("resolve", parents=[common])
    p_res.add_argument("name")
    sub.add_parser("list", parents=[common])
    sub.add_parser("validate", parents=[common])
    args = parser.parse_args(argv)

    if args.command == "register":
        ok, messages = register_skill(args.skills_dir, args.skill_dir, args.update)
        for m in messages:
            print(m if ok else f"violation: {m}", file=sys.stdout if ok else sys.stderr)
        return 0 if ok else 1

    if args.command == "deregister":
        ok, warnings = deregister_skill(args.skills_dir, args.name, args.routes)
        for w in warnings:
            print(f"warning: {w}", file=sys.stderr)
        if not ok:
            return 1
        print(f"deregistered '{args.name}'")
        return 0

    if args.command == "resolve":
        registry = load_registry(args.skills_dir, [])
        entry = registry["skills"].get(args.name)
        if entry is None:
            print(f"'{args.name}' is not registered", file=sys.stderr)
            return 1
        json.dump(entry, sys.stdout)
        sys.stdout.write("\n")
        return 0

    if args.command == "list":
        registry = load_registry(args.skills_dir, [])
        for name, entry in sorted(registry["skills"].items()):
            print(f"{name} {entry.get('version', '?')} — {entry.get('description', '')}")
        return 0

    # validate
    report = validate_registry(args.skills_dir)
    bad = {n: v for n, v in report["skills"].items() if v}
    if report["contract_version_drift"]:
        print(f"warning: registry contract version differs from current "
              f"({CONTRACT_VERSION}) — re-validating all skills", file=sys.stderr)
    for name, violations in sorted(bad.items()):
        for v in violations:
            print(f"non-compliant: {name}: {v}", file=sys.stderr)
    print(f"validated {len(report['skills'])} skill(s), "
          f"{len(bad)} non-compliant")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
