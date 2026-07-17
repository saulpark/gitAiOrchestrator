"""Tests for src/skill_registry.py — skill contract + registry (feature 005)."""
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

from skill_registry import (  # noqa: E402
    CONTRACT_VERSION,
    deregister_skill,
    load_registry,
    register_skill,
    validate_manifest,
    validate_registry,
)

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


def test_contract_version_is_one_one():
    assert CONTRACT_VERSION == "1.1"


def test_invalid_time_budget_is_violation(tmp_path):
    m = {**GOOD_MANIFEST, "time_budget_seconds": -5}
    d = _make_skill(tmp_path, m, dirname="bad-budget")
    assert "time-budget" in _violation_rules(validate_manifest(str(d)))


def test_valid_time_budget_accepted(tmp_path):
    m = {**GOOD_MANIFEST, "time_budget_seconds": 12}
    d = _make_skill(tmp_path, m, dirname="good-budget")
    assert validate_manifest(str(d)) == []


# --- registry operations (Task 2) ---

def _skills_dir(tmp_path):
    return str(tmp_path / "skills")


def test_register_compliant_skill_writes_registry(tmp_path):
    d = _make_skill(tmp_path)
    ok, messages = register_skill(_skills_dir(tmp_path), str(d))
    assert ok
    reg = json.loads((tmp_path / "skills" / "registry.json").read_text())
    assert reg["contract_version"] == CONTRACT_VERSION
    assert reg["skills"]["doc-sync"]["dir"] == "doc-sync"
    assert reg["skills"]["doc-sync"]["version"] == "1.0.0"


def test_rejected_skill_not_written(tmp_path):
    d = _make_skill(tmp_path, manifest={}, run=False)
    ok, messages = register_skill(_skills_dir(tmp_path), str(d))
    assert not ok and len(messages) >= 6
    assert not (tmp_path / "skills" / "registry.json").exists() or \
        json.loads((tmp_path / "skills" / "registry.json").read_text())["skills"] == {}


def test_duplicate_name_rejected_without_update(tmp_path):
    d = _make_skill(tmp_path)
    assert register_skill(_skills_dir(tmp_path), str(d))[0]
    ok, messages = register_skill(_skills_dir(tmp_path), str(d))
    assert not ok and any("duplicate-name" in m for m in messages)
    ok, _ = register_skill(_skills_dir(tmp_path), str(d), update=True)
    assert ok


def test_deregister_removes_and_warns_on_route_reference(tmp_path):
    d = _make_skill(tmp_path)
    register_skill(_skills_dir(tmp_path), str(d))
    routes = tmp_path / "routes.json"
    routes.write_text('{"version": "1.0", "routes": {"pre-commit": ["doc-sync"]}}')
    ok, warnings = deregister_skill(_skills_dir(tmp_path), "doc-sync", str(routes))
    assert ok
    assert any("pre-commit" in w for w in warnings)
    reg = load_registry(_skills_dir(tmp_path), [])
    assert reg["skills"] == {}


def test_deregister_unknown_name_fails(tmp_path):
    ok, messages = deregister_skill(_skills_dir(tmp_path), "ghost", None)
    assert not ok


def test_load_registry_missing_or_corrupt(tmp_path):
    warnings = []
    reg = load_registry(_skills_dir(tmp_path), warnings)
    assert reg["skills"] == {} and warnings
    (tmp_path / "skills").mkdir()
    (tmp_path / "skills" / "registry.json").write_text("{bad")
    warnings = []
    reg = load_registry(_skills_dir(tmp_path), warnings)
    assert reg["skills"] == {} and warnings


def test_validate_registry_flags_broken_skill_and_drift(tmp_path):
    d = _make_skill(tmp_path)
    register_skill(_skills_dir(tmp_path), str(d))
    (d / "run").unlink()  # break the skill after registration
    reg_path = tmp_path / "skills" / "registry.json"
    reg = json.loads(reg_path.read_text())
    reg["contract_version"] = "0.9"  # simulate contract drift
    reg_path.write_text(json.dumps(reg))
    report = validate_registry(_skills_dir(tmp_path))
    assert any("entry-point" in v for v in report["skills"]["doc-sync"])
    assert report["contract_version_drift"]


def test_validate_registry_clean(tmp_path):
    d = _make_skill(tmp_path)
    register_skill(_skills_dir(tmp_path), str(d))
    report = validate_registry(_skills_dir(tmp_path))
    assert report["skills"]["doc-sync"] == []
    assert not report["contract_version_drift"]


# --- CLI (Task 3) ---

def _run_cli(*args, cwd):
    import subprocess
    return subprocess.run(
        [sys.executable, str(REPO_ROOT / "src" / "skill_registry.py"), *args],
        capture_output=True, text=True, timeout=10, cwd=cwd,
    )


def test_cli_register_ok_then_duplicate_then_update(tmp_path):
    d = _make_skill(tmp_path)
    r = _run_cli("register", str(d), "--skills-dir", _skills_dir(tmp_path), cwd=tmp_path)
    assert r.returncode == 0 and "registered" in r.stdout
    r = _run_cli("register", str(d), "--skills-dir", _skills_dir(tmp_path), cwd=tmp_path)
    assert r.returncode == 1 and "duplicate-name" in r.stderr
    r = _run_cli("register", str(d), "--skills-dir", _skills_dir(tmp_path),
                 "--update", cwd=tmp_path)
    assert r.returncode == 0


def test_cli_register_rejection_lists_all_violations(tmp_path):
    d = _make_skill(tmp_path, manifest={}, run=False, dirname="bad")
    r = _run_cli("register", str(d), "--skills-dir", _skills_dir(tmp_path), cwd=tmp_path)
    assert r.returncode == 1
    for rule in ("name", "version", "description", "input", "output",
                 "behaviors", "entry-point"):
        assert rule in r.stderr


def test_cli_resolve_and_list(tmp_path):
    d = _make_skill(tmp_path)
    _run_cli("register", str(d), "--skills-dir", _skills_dir(tmp_path), cwd=tmp_path)
    r = _run_cli("resolve", "doc-sync", "--skills-dir", _skills_dir(tmp_path), cwd=tmp_path)
    assert r.returncode == 0 and json.loads(r.stdout)["dir"] == "doc-sync"
    r = _run_cli("resolve", "ghost", "--skills-dir", _skills_dir(tmp_path), cwd=tmp_path)
    assert r.returncode == 1
    r = _run_cli("list", "--skills-dir", _skills_dir(tmp_path), cwd=tmp_path)
    assert r.returncode == 0 and "doc-sync" in r.stdout


def test_cli_validate_exit_codes(tmp_path):
    d = _make_skill(tmp_path)
    _run_cli("register", str(d), "--skills-dir", _skills_dir(tmp_path), cwd=tmp_path)
    assert _run_cli("validate", "--skills-dir", _skills_dir(tmp_path),
                    cwd=tmp_path).returncode == 0
    (d / "run").unlink()
    r = _run_cli("validate", "--skills-dir", _skills_dir(tmp_path), cwd=tmp_path)
    assert r.returncode == 1 and "doc-sync" in r.stderr
