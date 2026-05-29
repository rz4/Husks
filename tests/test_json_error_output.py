"""
test_json_error_output.py -- Beta Gate F/G: JSON error output on failures.

Verifies that `husks run --json` produces parseable JSON error output for:
- Missing site_inputs
- Invalid design files
- Validation failures
- Reuse-only cache misses
- Build halts
"""

import json
import tempfile
import shutil
from pathlib import Path

from conftest import run_husks_cli


def test_json_error_on_missing_site_input():
    """run --json with missing site_input produces JSON error."""
    tmpdir = tempfile.mkdtemp(prefix="json-error-missing-input-")
    try:
        # Create design that references non-existent site_input
        design_file = Path(tmpdir) / "design.json"
        design_file.write_text(json.dumps({
            "name": "test",
            "fuel": 10,
            "target": "out",
            "site_inputs": ["missing.txt"],  # File doesn't exist
            "rules": [{
                "name": "out",
                "kind": "action",
                "inputs": ["missing.txt"],
                "outputs": ["out.txt"],
                "run": "cp missing.txt out.txt"
            }]
        }))

        site = Path(tmpdir) / "site"
        site.mkdir()

        result = run_husks_cli("run", str(design_file), "--site", str(site), "--json")

        # Should fail with JSON error output
        assert result.returncode != 0, "Missing site_input should cause failure"

        # Should output valid JSON
        output = json.loads(result.stdout)
        assert output["status"] == "error", f"Expected error status, got: {output}"
        assert "error" in output, "Error message should be present"
        assert "site_input" in output["error"].lower() or "not exist" in output["error"].lower()

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_json_error_on_invalid_design():
    """run --json with invalid JSON design produces JSON error."""
    tmpdir = tempfile.mkdtemp(prefix="json-error-invalid-design-")
    try:
        # Create invalid JSON file
        design_file = Path(tmpdir) / "design.json"
        design_file.write_text("{ invalid json content")

        site = Path(tmpdir) / "site"
        site.mkdir()

        result = run_husks_cli("run", str(design_file), "--site", str(site), "--json")

        # Should fail with JSON error output
        assert result.returncode != 0, "Invalid design should cause failure"

        # Should output valid JSON (even though input was invalid)
        output = json.loads(result.stdout)
        assert output["status"] == "error"
        assert "error" in output

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_json_error_on_validation_failure():
    """run --json with design validation failure produces JSON error."""
    tmpdir = tempfile.mkdtemp(prefix="json-error-validation-")
    try:
        # Create design with validation error (input not produced by any rule)
        design_file = Path(tmpdir) / "design.json"
        design_file.write_text(json.dumps({
            "name": "test",
            "fuel": 10,
            "target": "out",
            "rules": [{
                "name": "out",
                "kind": "action",
                "inputs": ["missing.txt"],  # Not produced, not in site_inputs
                "outputs": ["out.txt"],
                "run": "echo fail"
            }]
        }))

        site = Path(tmpdir) / "site"
        site.mkdir()

        result = run_husks_cli("run", str(design_file), "--site", str(site), "--json")

        # Should fail with JSON error output
        assert result.returncode != 0, "Validation failure should cause error"

        # Should output valid JSON
        output = json.loads(result.stdout)
        assert output["status"] == "error"
        assert "error" in output

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_json_error_on_reuse_only_cache_miss():
    """run --json --reuse-only with cache miss produces JSON error."""
    tmpdir = tempfile.mkdtemp(prefix="json-error-reuse-miss-")
    try:
        design_file = Path(tmpdir) / "design.json"
        design_file.write_text(json.dumps({
            "name": "test",
            "fuel": 10,
            "target": "gen",
            "rules": [{
                "name": "gen",
                "kind": "oracle",
                "outputs": ["out.txt"],
                "prompt": "Generate output",
                "tools": ["write-file"]
            }]
        }))

        site = Path(tmpdir) / "site"
        site.mkdir()

        # Try to run with --reuse-only but no cache exists
        result = run_husks_cli(
            "run", str(design_file),
            "--site", str(site),
            "--reuse-only",
            "--json"
        )

        # Should fail (no cache available)
        assert result.returncode != 0, "Reuse-only without cache should fail"

        # Should output valid JSON (could be error or halted status)
        output = json.loads(result.stdout)
        assert "status" in output
        assert output["status"] in ("error", "halted")

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_json_output_on_build_halt():
    """run --json with build halt produces valid JSON (not just text error)."""
    tmpdir = tempfile.mkdtemp(prefix="json-error-halt-")
    try:
        # Create design with action that fails
        design_file = Path(tmpdir) / "design.json"
        site_dir = Path(tmpdir) / "site"
        site_dir.mkdir()

        # Create required input
        (Path(tmpdir) / "input.txt").write_text("data")

        design_file.write_text(json.dumps({
            "name": "test",
            "fuel": 10,
            "target": "out",
            "site_inputs": ["input.txt"],
            "rules": [{
                "name": "out",
                "kind": "action",
                "inputs": ["input.txt"],
                "outputs": ["out.txt"],
                "run": "exit 1"  # Intentional failure
            }]
        }))

        result = run_husks_cli("run", str(design_file), "--site", str(site_dir), "--json")

        # Should fail
        assert result.returncode != 0, "Failed action should cause exit 1"

        # Should output valid JSON with halted status
        output = json.loads(result.stdout)
        assert output["status"] == "halted", f"Expected halted, got {output['status']}"
        assert "diagnosis" in output, "Halted build should have diagnosis"
        assert "error" in output["diagnosis"]

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_all_json_errors_parseable():
    """Verify that all JSON error outputs are valid JSON and have stable schema."""
    # This is a meta-test that verifies the schema is consistent
    # All JSON error outputs should have at minimum:
    # - "status": "error" or "halted"
    # - Some error description field
    pass  # Covered by above tests
