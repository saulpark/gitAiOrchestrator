"""Tests for src/skill_registry.py — skill contract + registry (feature 005)."""
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

from skill_registry import CONTRACT_VERSION, validate_manifest  # noqa: E402

GOOD_MANIFEST = {
    "name": "doc-sync",
    "version": "1.0.0",
    "description": "Regenerates docs for changed modules",
    "input": "hook-context@1.0",
    "output": "skill-result@1.0",
    "behaviors": {"non_blocking": True, "idempotent": True},
}


def _make_skill(tmp_path, manifest=GOOD_MANIFEST, run=True, dirname="doc-sync"):
    d = tmp_path / "skills" / dirname
    d.mkdir(parents=True)
    if manifest is not None:
        (d / "skill.json").write_text(json.dumps(manifest))
    if run:
        r = d / "run"
        r.write_text("#!/bin/sh\ncat > /dev/null\nexit 0\n")
        r.chmod(0o755)
    return d


def _violation_rules(violations):
    return {v.split(":", 1)[0] for v in violations}


def test_compliant_manifest_has_no_violations(tmp_path):
    d = _make_skill(tmp_path)
    assert validate_manifest(str(d)) == []


def test_missing_manifest_file(tmp_path):
    d = _make_skill(tmp_path, manifest=None)
    assert _violation_rules(validate_manifest(str(d))) == {"missing-manifest"}


def test_unparseable_manifest(tmp_path):
    d = _make_skill(tmp_path, manifest=None)
    (d / "skill.json").write_text("{nope")
    assert _violation_rules(validate_manifest(str(d))) == {"missing-manifest"}


def test_each_field_violation_is_named(tmp_path):
    cases = {
        "name": {**GOOD_MANIFEST, "name": "Bad Name!"},
        "version": {**GOOD_MANIFEST, "version": "1.0"},
        "description": {**GOOD_MANIFEST, "description": ""},
        "input": {**GOOD_MANIFEST, "input": "custom@2"},
        "output": {**GOOD_MANIFEST, "output": "whatever"},
        "behaviors": {**GOOD_MANIFEST, "behaviors": {"idempotent": True}},
    }
    for rule, manifest in cases.items():
        d = _make_skill(tmp_path, manifest, dirname=f"case-{rule}")
        rules = _violation_rules(validate_manifest(str(d)))
        assert rule in rules, f"expected {rule} in {rules}"


def test_non_blocking_false_violates_behaviors(tmp_path):
    m = {**GOOD_MANIFEST, "behaviors": {"non_blocking": False, "idempotent": True}}
    d = _make_skill(tmp_path, m)
    assert "behaviors" in _violation_rules(validate_manifest(str(d)))


def test_reserved_name_rejected(tmp_path):
    m = {**GOOD_MANIFEST, "name": "registry"}
    d = _make_skill(tmp_path, m)
    assert "name-reserved" in _violation_rules(validate_manifest(str(d)))


def test_missing_run_is_entry_point_violation(tmp_path):
    d = _make_skill(tmp_path, run=False)
    assert "entry-point" in _violation_rules(validate_manifest(str(d)))


def test_non_executable_run_is_entry_point_violation(tmp_path):
    d = _make_skill(tmp_path)
    (d / "run").chmod(0o644)
    assert "entry-point" in _violation_rules(validate_manifest(str(d)))


def test_all_violations_reported_in_one_pass(tmp_path):
    d = _make_skill(tmp_path, manifest={}, run=False)
    rules = _violation_rules(validate_manifest(str(d)))
    assert {"name", "version", "description", "input", "output",
            "behaviors", "entry-point"} <= rules


def test_contract_version_is_one_zero():
    assert CONTRACT_VERSION == "1.0"
