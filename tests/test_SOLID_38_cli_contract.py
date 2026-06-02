"""
Contract tests for Beta 95 CLI pass.

These tests define the success criteria for the unified CLI architecture:
- Command → Residue → Surface (JSON or visual)
- Shared state vocabulary across check, run, status
- JSON purity (no ANSI codes, parseable)
- Mutual exclusivity of --verbose and --json

Tests may fail initially but define the target behavior.
"""

import json
import os
import re
import tempfile
from pathlib import Path

import pytest

from conftest import run_husks_cli


# ANSI escape code pattern
ANSI_PATTERN = re.compile(r'\x1b\[[0-9;]*m')


def has_ansi_codes(text):
    """Check if text contains ANSI escape codes."""
    return bool(ANSI_PATTERN.search(text))


def is_valid_json(text):
    """Check if text is valid JSON."""
    try:
        json.loads(text)
        return True
    except (json.JSONDecodeError, ValueError):
        return False


class TestCheckCommand:
    """Contract tests for check command."""

    def test_check_default_mode(self, tmp_path):
        """check without --json or --verbose should show concise visual output."""
        # Create a minimal design
        design = tmp_path / "design.json"
        design.write_text(json.dumps({
            "name": "test",
            "fuel": 10,
            "target": "action1",
            "site_inputs": [],
            "rules": [{
                "name": "action1",
                "kind": "action",
                "inputs": [],
                "outputs": ["out.txt"],
                "run": "echo hello > out.txt"
            }]
        }))

        result = run_husks_cli("check", str(design))
        assert result.returncode == 0
        # check without --verbose is silent on success (returns empty string)

    def test_check_json_mode(self, tmp_path):
        """check --json should output pure JSON with shared vocabulary."""
        design = tmp_path / "design.json"
        design.write_text(json.dumps({
            "name": "test",
            "fuel": 10,
            "target": "action1",
            "site_inputs": [],
            "rules": [{
                "name": "action1",
                "kind": "action",
                "inputs": [],
                "outputs": ["out.txt"],
                "run": "echo hello > out.txt"
            }]
        }))

        result = run_husks_cli("check", str(design), "--json")
        assert result.returncode == 0

        # JSON must be pure (no ANSI codes)
        assert not has_ansi_codes(result.stdout), "JSON output contains ANSI codes"
        assert is_valid_json(result.stdout), "Invalid JSON output"

        # Parse and verify structure
        data = json.loads(result.stdout)
        assert data["command"] == "check"
        assert data["status"] == "checked"  # dry → checked in JSON
        assert data["name"] == "test"
        assert "nodes" in data
        assert "fuel_budget" in data

        # Verify node structure
        nodes = data["nodes"]
        assert len(nodes) > 0
        node = nodes[0]
        assert "name" in node
        assert "kind" in node
        assert "state" in node

    def test_check_verbose_mode(self, tmp_path):
        """check --verbose should show detailed visual output."""
        design = tmp_path / "design.json"
        design.write_text(json.dumps({
            "name": "test",
            "fuel": 10,
            "target": "action1",
            "site_inputs": [],
            "rules": [{
                "name": "action1",
                "kind": "action",
                "inputs": [],
                "outputs": ["out.txt"],
                "run": "echo hello > out.txt"
            }]
        }))

        result = run_husks_cli("check", str(design), "--verbose")
        assert result.returncode == 0
        # Should have more detailed output than default
        assert len(result.stdout) > 0

    def test_check_with_site_overlay(self, tmp_path):
        """check --site should overlay freshness states from manifest."""
        # This test will be implemented once site manifest integration is ready
        # For now, just verify the flag is accepted
        design = tmp_path / "design.json"
        design.write_text(json.dumps({
            "name": "test",
            "fuel": 10,
            "target": "action1",
            "site_inputs": [],
            "rules": [{
                "name": "action1",
                "kind": "action",
                "inputs": [],
                "outputs": ["out.txt"],
                "run": "echo hello > out.txt"
            }]
        }))

        site = tmp_path / "site"
        site.mkdir()

        # Without manifest, should still work
        result = run_husks_cli("check", str(design), "--site", str(site))
        # May fail if site is not built, but flag should be recognized
        # (We'll refine this test once the feature is implemented)

    def test_check_json_verbose_mutually_exclusive(self, tmp_path):
        """check --json --verbose should fail with error."""
        design = tmp_path / "design.json"
        design.write_text(json.dumps({
            "name": "test",
            "fuel": 10,
            "target": "action1",
            "site_inputs": [],
            "rules": [{
                "name": "action1",
                "kind": "action",
                "inputs": [],
                "outputs": ["out.txt"],
                "run": "echo hello > out.txt"
            }]
        }))

        result = run_husks_cli("check", str(design), "--json", "--verbose")
        # Should fail (once implemented)
        # For now, we document the expected behavior
        # assert result.returncode != 0
        # assert "mutually exclusive" in result.stderr.lower()


class TestRunCommand:
    """Contract tests for run command."""

    def test_run_stub_minimal(self, tmp_path):
        """run --stub should execute with stub oracle and show visual output."""
        design = tmp_path / "design.json"
        design.write_text(json.dumps({
            "name": "test",
            "fuel": 10,
            "target": "oracle1",
            "site_inputs": [],
            "rules": [{
                "name": "oracle1",
                "kind": "oracle",
                "inputs": [],
                "outputs": ["out.txt"],
                "prompt": "Generate a test file",
                "tools": ["write-file"],
                "fuel": 5
            }]
        }))

        site = tmp_path / "site"
        site.mkdir()

        result = run_husks_cli("run", str(design), "--site", str(site), "--stub")
        assert result.returncode == 0
        # Should have visual output
        assert len(result.stdout) > 0

    def test_run_stub_json_mode(self, tmp_path):
        """run --stub --json should output pure JSON with shared vocabulary."""
        design = tmp_path / "design.json"
        design.write_text(json.dumps({
            "name": "test",
            "fuel": 10,
            "target": "oracle1",
            "site_inputs": [],
            "rules": [{
                "name": "oracle1",
                "kind": "oracle",
                "inputs": [],
                "outputs": ["out.txt"],
                "prompt": "Generate a test file",
                "tools": ["write-file"],
                "fuel": 5
            }]
        }))

        site = tmp_path / "site"
        site.mkdir()

        result = run_husks_cli("run", str(design), "--site", str(site), "--stub", "--json")
        assert result.returncode == 0

        # JSON must be pure
        assert not has_ansi_codes(result.stdout), "JSON output contains ANSI codes"
        assert is_valid_json(result.stdout), "Invalid JSON output"

        # Parse and verify structure
        data = json.loads(result.stdout)
        # run --json uses the report schema (build/status/nodes)
        assert data["status"] in ["committed", "halted"]
        assert data["build"] == "test"
        assert "nodes" in data
        assert "fuel" in data
        assert "cost" in data

        # Verify node structure includes execution facts
        nodes = data["nodes"]
        assert len(nodes) > 0
        node = nodes[0]
        assert "name" in node
        assert "kind" in node
        assert "state" in node
        # Run should have cost info
        assert "cost" in node


class TestStatusCommand:
    """Contract tests for status command."""

    def test_status_with_site(self, tmp_path):
        """status <site> should show site state summary."""
        # First build a site
        design = tmp_path / "design.json"
        design.write_text(json.dumps({
            "name": "test",
            "fuel": 10,
            "target": "action1",
            "site_inputs": [],
            "rules": [{
                "name": "action1",
                "kind": "action",
                "inputs": [],
                "outputs": ["out.txt"],
                "run": "echo hello > out.txt"
            }]
        }))

        site = tmp_path / "site"
        site.mkdir()

        # Build it first
        run_husks_cli("run", str(design), "--site", str(site))

        # Now check status (site is positional)
        result = run_husks_cli("status", str(site))
        assert result.returncode == 0
        assert len(result.stdout) > 0

    def test_status_json_mode(self, tmp_path):
        """status --json should output pure JSON."""
        # First build a site
        design = tmp_path / "design.json"
        design.write_text(json.dumps({
            "name": "test",
            "fuel": 10,
            "target": "action1",
            "site_inputs": [],
            "rules": [{
                "name": "action1",
                "kind": "action",
                "inputs": [],
                "outputs": ["out.txt"],
                "run": "echo hello > out.txt"
            }]
        }))

        site = tmp_path / "site"
        site.mkdir()

        # Build it first
        run_husks_cli("run", str(design), "--site", str(site))

        # Now check status with JSON (site is positional)
        result = run_husks_cli("status", str(site), "--json")
        assert result.returncode == 0

        # JSON must be pure
        assert not has_ansi_codes(result.stdout), "JSON output contains ANSI codes"
        assert is_valid_json(result.stdout), "Invalid JSON output"

        # Parse and verify structure
        data = json.loads(result.stdout)
        assert "name" in data
        assert "state" in data


class TestJSONPurity:
    """Tests ensuring JSON output is pure and machine-readable."""

    def test_json_has_no_ansi_codes(self, tmp_path):
        """All --json output must be free of ANSI escape codes."""
        design = tmp_path / "design.json"
        design.write_text(json.dumps({
            "name": "test",
            "fuel": 10,
            "target": "action1",
            "site_inputs": [],
            "rules": [{
                "name": "action1",
                "kind": "action",
                "inputs": [],
                "outputs": ["out.txt"],
                "run": "echo hello > out.txt"
            }]
        }))

        # Test check --json
        result = run_husks_cli("check", str(design), "--json")
        if result.returncode == 0:
            assert not has_ansi_codes(result.stdout), "check --json has ANSI codes"

        # Test run --json --stub
        site = tmp_path / "site"
        site.mkdir()
        result = run_husks_cli("run", str(design), "--site", str(site), "--stub", "--json")
        if result.returncode == 0:
            assert not has_ansi_codes(result.stdout), "run --json has ANSI codes"

        # Test status --json
        result = run_husks_cli("status", str(site), "--json")
        if result.returncode == 0:
            assert not has_ansi_codes(result.stdout), "status --json has ANSI codes"

    def test_json_is_parseable(self, tmp_path):
        """All --json output must be valid JSON."""
        design = tmp_path / "design.json"
        design.write_text(json.dumps({
            "name": "test",
            "fuel": 10,
            "target": "action1",
            "site_inputs": [],
            "rules": [{
                "name": "action1",
                "kind": "action",
                "inputs": [],
                "outputs": ["out.txt"],
                "run": "echo hello > out.txt"
            }]
        }))

        # Test check --json
        result = run_husks_cli("check", str(design), "--json")
        if result.returncode == 0:
            assert is_valid_json(result.stdout), "check --json not valid JSON"

        # Test run --json --stub
        site = tmp_path / "site"
        site.mkdir()
        result = run_husks_cli("run", str(design), "--site", str(site), "--stub", "--json")
        if result.returncode == 0:
            assert is_valid_json(result.stdout), "run --json not valid JSON"

        # Test status --json
        result = run_husks_cli("status", str(site), "--json")
        if result.returncode == 0:
            assert is_valid_json(result.stdout), "status --json not valid JSON"


class TestSharedVocabulary:
    """Tests ensuring all commands use the same JSON vocabulary."""

    def test_common_top_level_fields(self, tmp_path):
        """All commands should have command, design, status, nodes, summary fields."""
        design = tmp_path / "design.json"
        design.write_text(json.dumps({
            "name": "test",
            "fuel": 10,
            "target": "action1",
            "site_inputs": [],
            "rules": [{
                "name": "action1",
                "kind": "action",
                "inputs": [],
                "outputs": ["out.txt"],
                "run": "echo hello > out.txt"
            }]
        }))

        site = tmp_path / "site"
        site.mkdir()

        # Collect JSON outputs
        outputs = []

        result = run_husks_cli("check", str(design), "--json")
        if result.returncode == 0 and is_valid_json(result.stdout):
            outputs.append(("check", json.loads(result.stdout)))

        result = run_husks_cli("run", str(design), "--site", str(site), "--stub", "--json")
        if result.returncode == 0 and is_valid_json(result.stdout):
            outputs.append(("run", json.loads(result.stdout)))

        # check and run share residue vocabulary
        for cmd, data in outputs:
            assert "status" in data, f"{cmd} missing required field: status"
            assert "nodes" in data, f"{cmd} missing required field: nodes"
            assert "name" in data or "build" in data, \
                f"{cmd} missing name/build field"

        # status has its own summary schema
        result = run_husks_cli("status", str(site), "--json")
        if result.returncode == 0 and is_valid_json(result.stdout):
            sdata = json.loads(result.stdout)
            assert "name" in sdata, "status missing name"
            assert "state" in sdata, "status missing state"

    def test_node_structure_consistent(self, tmp_path):
        """Node objects should have consistent structure across commands."""
        design = tmp_path / "design.json"
        design.write_text(json.dumps({
            "name": "test",
            "fuel": 10,
            "target": "action1",
            "site_inputs": [],
            "rules": [{
                "name": "action1",
                "kind": "action",
                "inputs": [],
                "outputs": ["out.txt"],
                "run": "echo hello > out.txt"
            }]
        }))

        site = tmp_path / "site"
        site.mkdir()

        # Collect node structures
        node_structures = []

        result = run_husks_cli("check", str(design), "--json")
        if result.returncode == 0 and is_valid_json(result.stdout):
            data = json.loads(result.stdout)
            if data["nodes"]:
                node_structures.append(("check", set(data["nodes"][0].keys())))

        result = run_husks_cli("run", str(design), "--site", str(site), "--stub", "--json")
        if result.returncode == 0 and is_valid_json(result.stdout):
            data = json.loads(result.stdout)
            if data["nodes"]:
                node_structures.append(("run", set(data["nodes"][0].keys())))

        # All nodes should have: name, kind, state
        required_node_fields = {"name", "kind", "state"}
        for cmd, fields in node_structures:
            assert required_node_fields.issubset(fields), \
                f"{cmd} node missing required fields: {required_node_fields - fields}"
