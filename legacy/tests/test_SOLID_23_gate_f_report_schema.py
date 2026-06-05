"""
test_report_schema_version.py -- Task 9: Stabilized beta report contract.

Tests that the report schema includes schema_version="beta-1" and validates
correctly against the stabilized beta contract.
"""

import json
import tempfile
import shutil
from pathlib import Path

from conftest import run_husks_cli
from husks.report import validate_report_schema

import pytest


@pytest.mark.beta


@pytest.mark.gate_f


def test_report_includes_schema_version():
    """All reports include schema_version='beta-1' (Task 9)."""
    tmpdir = tempfile.mkdtemp(prefix="schema-version-")
    try:
        # Run a minimal design to generate a report
        design_file = Path(tmpdir) / "design.json"
        design_file.write_text(json.dumps({
            "name": "test",
            "fuel": 5,
            "target": "out",
            "rules": [{
                "name": "out",
                "kind": "action",
                "outputs": ["out.txt"],
                "run": "echo test > out.txt"
            }]
        }))

        site_dir = Path(tmpdir) / "site"
        site_dir.mkdir()

        result = run_husks_cli(
            "run", str(design_file),
            "--site", str(site_dir),
            "--json",
        )

        assert result.returncode == 0, f"Run should succeed: {result.stderr}"

        # Parse report
        report = json.loads(result.stdout)

        # Verify schema_version is present and correct
        assert "schema_version" in report, "Report must include schema_version field"
        assert report["schema_version"] == "beta-1", (
            f"schema_version should be 'beta-1', got '{report['schema_version']}'"
        )

        # Verify report passes schema validation
        valid, errors = validate_report_schema(report)
        assert valid, f"Report should pass schema validation:\n" + "\n".join(f"  - {e}" for e in errors)

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


@pytest.mark.beta


@pytest.mark.gate_f


def test_schema_validation_requires_version():
    """Schema validation requires schema_version field (Task 9)."""
    # Report missing schema_version
    report = {
        "status": "committed",
        "root": "abc123",
        "run_id": "test_run",
        "build": "test",
        "site": "/tmp/test",
        "elapsed_s": 1.0,
        "fuel": {"start": 10, "end": 8},
        # Task 7 (New): Use renamed estimate fields
        "cost": {"paid": 0.0, "reused_estimate": 0.0, "projected_estimate": 0.0},
        "delta": {"changed": [], "new": [], "unchanged": []},
        "nodes": [],
    }

    valid, errors = validate_report_schema(report)
    assert not valid, "Report without schema_version should fail validation"
    assert any("schema_version" in e for e in errors), (
        f"Validation should complain about missing schema_version, got: {errors}"
    )


@pytest.mark.beta


@pytest.mark.gate_f


def test_schema_validation_rejects_wrong_version():
    """Schema validation rejects unsupported versions (Task 9)."""
    # Report with wrong schema_version
    report = {
        "schema_version": "beta-2",  # Future version
        "status": "committed",
        "root": "abc123",
        "run_id": "test_run",
        "build": "test",
        "site": "/tmp/test",
        "elapsed_s": 1.0,
        "fuel": {"start": 10, "end": 8},
        # Task 7 (New): Use renamed estimate fields
        "cost": {"paid": 0.0, "reused_estimate": 0.0, "projected_estimate": 0.0},
        "delta": {"changed": [], "new": [], "unchanged": []},
        "nodes": [],
    }

    valid, errors = validate_report_schema(report)
    assert not valid, "Report with unsupported schema_version should fail validation"
    assert any("unsupported schema_version" in e for e in errors), (
        f"Validation should complain about unsupported version, got: {errors}"
    )


@pytest.mark.beta


@pytest.mark.gate_f


def test_schema_version_appears_in_text_output():
    """Text rendering includes schema version (Task 9)."""
    from husks.report import render_text

    report = {
        "schema_version": "beta-1",
        "status": "committed",
        "root": "abc123",
        "run_id": "test_run",
        "build": "test",
        "site": "/tmp/test",
        "elapsed_s": 1.234,
        "fuel": {"start": 10, "end": 8},
        # Task 7 (New): Use renamed estimate fields
        "cost": {"paid": 0.0012, "reused_estimate": 0.0, "projected_estimate": 0.0012},
        "delta": {"changed": [], "new": ["out"], "unchanged": []},
        "nodes": [{
            "name": "out",
            "kind": "action",
            "state": "fired",
            "classification": "stable",
            "prompt_len": None,
            "prompt_trend": None,
            "fuel_consumed": 0,
            "fuel_trend": None,
            "output_hashes": ["hash1"],
            "output_changed": True,
            "cost": {"this_run": 0.0, "first_paid": 0.0, "per_rerun": 0.0},
            "cached": False,
            "tokens": {"input": 0, "output": 0},
            "seal": {"hash": "seal_hash", "recipe_changed": False},
        }],
    }

    text = render_text(report)
    assert "schema:" in text.lower(), "Text output should include schema version"
    assert "beta-1" in text, "Text output should show beta-1 version"
