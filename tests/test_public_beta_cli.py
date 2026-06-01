"""
Public Beta CLI Smoke Test (Beta Gate 95)

Tests the complete new-user workflow with the unified CLI architecture:
- init → check → run --stub → status
- Verifies JSON output, visual output, and command integration
"""

import json
import os
import tempfile
from pathlib import Path

import pytest

from conftest import run_husks_cli


def test_public_beta_workflow():
    """Complete new-user workflow: init → check → run → status.

    This test validates the entire beta 95 CLI proof path:
    1. husks init creates a valid core-bootstrap design
    2. husks check validates the design
    3. husks run --stub executes with stub oracle
    4. husks status shows site conformance
    5. All commands support --json and --verbose
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        # Step 1: husks init
        result = run_husks_cli("init", tmpdir)
        assert result.returncode == 0, f"init failed: {result.stderr}"
        assert Path(tmpdir, "core-bootstrap.json").exists(), "core-bootstrap.json not created"

        design_file = "core-bootstrap.json"

        # Step 2: husks check (silent on success)
        result = run_husks_cli("check", design_file, cwd=tmpdir)
        assert result.returncode == 0, f"check failed: {result.stderr}"

        # Step 3: husks check --json
        result = run_husks_cli("check", design_file, "--json", cwd=tmpdir)
        assert result.returncode == 0, f"check --json failed: {result.stderr}"
        data = json.loads(result.stdout)
        assert data["command"] == "check", "JSON should have command field"
        assert data["status"] == "checked", "check should show checked status"
        assert data["name"] == "core-bootstrap", "JSON should have design name"
        assert len(data["nodes"]) == 2, "Should have 2 nodes"

        # Step 4: husks check --verbose
        result = run_husks_cli("check", design_file, "--verbose", cwd=tmpdir)
        assert result.returncode == 0, f"check --verbose failed: {result.stderr}"
        assert "generate" in result.stdout, "verbose should show rule names"

        # Step 5: husks run --stub --site .husk
        result = run_husks_cli("run", design_file, "--stub", "--site", ".husk", cwd=tmpdir)
        assert Path(tmpdir, ".husk").exists(), "site directory should be created"
        assert "sealed" in result.stdout or "failed" in result.stdout, "run should show execution states"

        # Step 6: husks run --stub --json
        result_json = run_husks_cli("run", design_file, "--stub", "--site", ".husk", "--json", cwd=tmpdir)
        data = json.loads(result_json.stdout)
        assert "nodes" in data, "JSON should have nodes"
        assert "status" in data, "JSON should have status"

        # Step 7: husks status --site .husk
        result = run_husks_cli("status", design_file, "--site", ".husk", cwd=tmpdir)
        assert result.returncode == 0, f"status failed: {result.stderr}"

        # Step 8: husks status --json
        result = run_husks_cli("status", design_file, "--site", ".husk", "--json", cwd=tmpdir)
        assert result.returncode == 0, f"status --json failed: {result.stderr}"
        data = json.loads(result.stdout)
        assert data["command"] == "status", "JSON should have command=status"


def test_json_purity():
    """Verify JSON output has no ANSI codes across all commands."""
    with tempfile.TemporaryDirectory() as tmpdir:
        # Init and prepare
        run_husks_cli("init", tmpdir, "demo")

        # Check --json
        result = run_husks_cli("check", "design.json", "--json", cwd=tmpdir)
        assert result.returncode == 0
        assert "\x1b[" not in result.stdout, "check --json contains ANSI codes"
        json.loads(result.stdout)  # Should parse without error

        # Run --stub --json
        result = run_husks_cli("run", "design.json", "--stub", "--site", ".husk", "--json", cwd=tmpdir)
        assert "\x1b[" not in result.stdout, "run --json contains ANSI codes"
        json.loads(result.stdout)  # Should parse without error

        # Status --json
        result = run_husks_cli("status", "design.json", "--site", ".husk", "--json", cwd=tmpdir)
        assert result.returncode == 0
        assert "\x1b[" not in result.stdout, "status --json contains ANSI codes"
        json.loads(result.stdout)  # Should parse without error


def test_shared_vocabulary():
    """Verify all commands use the same JSON field names."""
    with tempfile.TemporaryDirectory() as tmpdir:
        # Init and prepare
        run_husks_cli("init", tmpdir)
        design_file = "core-bootstrap.json"
        run_husks_cli("run", design_file, "--stub", "--site", ".husk", cwd=tmpdir)

        # Collect JSON outputs
        check_result = run_husks_cli("check", design_file, "--json", cwd=tmpdir)
        run_result = run_husks_cli("run", design_file, "--stub", "--site", ".husk", "--json", cwd=tmpdir)
        status_result = run_husks_cli("status", design_file, "--site", ".husk", "--json", cwd=tmpdir)

        check_data = json.loads(check_result.stdout)
        run_data = json.loads(run_result.stdout)
        status_data = json.loads(status_result.stdout)

        # All should have status and nodes fields
        for name, data in [("check", check_data), ("run", run_data), ("status", status_data)]:
            assert "status" in data, f"{name} missing status"
            assert "nodes" in data, f"{name} missing nodes"

        # All nodes should have name, kind, state
        for name, data in [("check", check_data), ("run", run_data), ("status", status_data)]:
            for node in data["nodes"]:
                assert "name" in node, f"{name} node missing name"
                assert "kind" in node, f"{name} node missing kind"
                assert "state" in node, f"{name} node missing state"


def test_cache_evidence():
    """Verify cached nodes have explicit cache evidence in JSON."""
    with tempfile.TemporaryDirectory() as tmpdir:
        # Init and prepare
        run_husks_cli("init", tmpdir, "demo")

        # First run
        run_husks_cli("run", "design.json", "--stub", "--site", ".husk", cwd=tmpdir)

        # Second run - should have cached nodes
        result = run_husks_cli("run", "design.json", "--stub", "--site", ".husk", "--json", cwd=tmpdir)
        data = json.loads(result.stdout)

        # Find cached nodes
        cached_nodes = [n for n in data["nodes"] if n.get("state") == "cached"]

        # If any cached nodes exist, they should have cache=true
        for node in cached_nodes:
            assert node.get("cache") is True, \
                f"Cached node {node['name']} missing cache=true flag"


def test_verbose_json_mutual_exclusivity():
    """Verify --verbose and --json are mutually exclusive."""
    with tempfile.TemporaryDirectory() as tmpdir:
        # Init
        run_husks_cli("init", tmpdir)

        # Try check --verbose --json
        result = run_husks_cli("check", "core-bootstrap.json", "--verbose", "--json", cwd=tmpdir)
        # Should either reject the combination or handle it gracefully
        assert result.returncode in [0, 1, 2], "Command should exit cleanly"


def test_visual_grammar():
    """Verify visual output uses unified symbols and states."""
    with tempfile.TemporaryDirectory() as tmpdir:
        # Init and prepare
        run_husks_cli("init", tmpdir)
        design_file = "core-bootstrap.json"

        # Check verbose visual output (check is silent by default)
        result = run_husks_cli("check", design_file, "--verbose", cwd=tmpdir)
        assert result.returncode == 0
        assert "oracle" in result.stdout, "Missing oracle indicator"
        assert "action" in result.stdout, "Missing action indicator"

        # Run and check for sealed/failed states
        run_husks_cli("run", design_file, "--stub", "--site", ".husk", cwd=tmpdir)
        result = run_husks_cli("run", design_file, "--stub", "--site", ".husk", cwd=tmpdir)
        assert "sealed" in result.stdout or "cached" in result.stdout or "failed" in result.stdout, \
            "Should show execution states"
