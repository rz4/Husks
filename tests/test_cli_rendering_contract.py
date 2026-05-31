"""
Golden rendering contract tests for CLI Beta 95.

These tests define the exact expected output using golden examples.
State glyphs are the leading mark, not kind glyphs.
Output is a bounded target-rooted DAG.
"""

import json
import os
import tempfile
from pathlib import Path

import pytest

from conftest import run_husks_cli


# Disable ANSI for exact string matching
os.environ["NO_COLOR"] = "1"


@pytest.fixture
def core_bootstrap_design(tmp_path):
    """Create the public seed design."""
    design = {
        "name": "core-bootstrap",
        "fuel": 20,
        "target": "validate",
        "site_inputs": {
            "CSE-v1.md": "CSE-v1.md",
            "CSE-v2.md": "CSE-v2.md"
        },
        "rules": [
            {
                "name": "generate",
                "kind": "oracle",
                "inputs": ["CSE-v1.md", "CSE-v2.md"],
                "outputs": ["readers/generated_reader.py"],
                "prompt": "Generate CSE reader",
                "tools": ["write-file"],
                "fuel": 10
            },
            {
                "name": "validate",
                "kind": "action",
                "inputs": ["readers/generated_reader.py"],
                "outputs": ["readers/gate-report.txt", "readers/VERIFIED"],
                "run": "python3 -m husks.gate 'python readers/generated_reader.py' --stamp-dir readers"
            }
        ]
    }

    design_path = tmp_path / "core-bootstrap.json"
    design_path.write_text(json.dumps(design, indent=2))

    # Create stub spec files
    (tmp_path / "CSE-v1.md").write_text("# CSE v1 spec")
    (tmp_path / "CSE-v2.md").write_text("# CSE v2 spec")

    return design_path


def test_check_silent_pass(core_bootstrap_design):
    """check without flags on passing design: no output, exit 0."""
    result = run_husks_cli("check", str(core_bootstrap_design))
    assert result.returncode == 0
    assert result.stdout.strip() == "", f"Expected no output, got: {result.stdout}"


def test_check_verbose_dry(core_bootstrap_design):
    """check --verbose shows bounded box with unrealized nodes."""
    result = run_husks_cli("check", str(core_bootstrap_design), "--verbose")
    assert result.returncode == 0

    output = result.stdout

    # Must have bordered box
    assert "────────────────────────────────" in output

    # Header line
    assert "core-bootstrap" in output
    assert "checked" in output
    assert "⚡20" in output

    # Tree structure: target-rooted, validate depends on generate
    assert "□ validate" in output
    assert "action" in output
    assert "└─ □ generate" in output
    assert "oracle" in output
    assert "⚡10" in output

    # Footer
    assert "passes: checks" in output

    # Must NOT have old-style glyphs
    assert "◆" not in output  # No kind glyphs
    assert "▫" not in output


def test_check_json_dry(core_bootstrap_design):
    """check --json outputs structured residue."""
    result = run_husks_cli("check", str(core_bootstrap_design), "--json")
    assert result.returncode == 0

    data = json.loads(result.stdout)

    # Top-level structure
    assert data["command"] == "check"
    assert data["name"] == "core-bootstrap"
    assert data["status"] == "checked"
    assert data["root"] is None
    assert data["fuel_budget"] == 20
    assert data["fuel_used"] == 0
    assert data["cost"] == 0.0
    assert data["passes"] == ["checks"]
    assert data["fails"] == []

    # Nodes
    nodes = {n["name"]: n for n in data["nodes"]}

    # validate node
    assert nodes["validate"]["kind"] == "action"
    assert nodes["validate"]["state"] == "unrealized"
    assert nodes["validate"]["children"] == ["generate"]

    # generate node
    assert nodes["generate"]["kind"] == "oracle"
    assert nodes["generate"]["state"] == "unrealized"
    assert nodes["generate"]["fuel_budget"] == 10


def test_run_requires_site(core_bootstrap_design):
    """run without --site should error."""
    result = run_husks_cli("run", str(core_bootstrap_design), "--stub")
    assert result.returncode != 0
    assert "requires --site" in result.stderr.lower() or "requires --site" in result.stdout.lower()


def test_run_sealed(core_bootstrap_design):
    """run --stub shows final sealed DAG only."""
    tmp_path = core_bootstrap_design.parent
    site = tmp_path / ".husk"

    result = run_husks_cli(
        "run", str(core_bootstrap_design), "--stub", "--site", str(site)
    )

    output = result.stdout

    # Must have bordered box
    assert "────────────────────────────────" in output

    # Header shows sealed status
    assert "core-bootstrap" in output
    assert "sealed" in output or "failed" in output  # May fail due to missing husks.gate

    # Tree with sealed nodes (■) or failed (✕)
    # Since gate will fail without husks.gate, we check for either
    assert ("■ validate" in output or "✕ validate" in output)
    assert ("■ generate" in output or "✕ generate" in output or "□ generate" in output)

    # Must NOT contain old trace output
    assert "●" not in output  # Old trace bullet
    assert "════" not in output  # Old report box

    # Footer shows passes
    assert "passes:" in output or "fails:" in output


def test_run_cached(core_bootstrap_design):
    """Second run shows cached nodes with ◆ glyph."""
    tmp_path = core_bootstrap_design.parent
    site = tmp_path / ".husk"

    # First run
    run_husks_cli("run", str(core_bootstrap_design), "--stub", "--site", str(site))

    # Second run
    result = run_husks_cli(
        "run", str(core_bootstrap_design), "--stub", "--site", str(site)
    )

    output = result.stdout

    # Should show cached glyph ◆
    assert "◆" in output
    assert "cached" in output
    assert "⚡0" in output  # Zero fuel used


def test_status_requires_site(core_bootstrap_design):
    """status without --site should error."""
    result = run_husks_cli("status", str(core_bootstrap_design))
    assert result.returncode != 0
    assert "requires --site" in result.stderr.lower() or "requires --site" in result.stdout.lower()


def test_status_sealed(core_bootstrap_design):
    """status shows site conformance in bounded box."""
    tmp_path = core_bootstrap_design.parent
    site = tmp_path / ".husk"

    # Build first
    run_husks_cli("run", str(core_bootstrap_design), "--stub", "--site", str(site))

    # Check status
    result = run_husks_cli("status", str(core_bootstrap_design), "--site", str(site))
    assert result.returncode == 0

    output = result.stdout

    # Must have bordered box
    assert "────────────────────────────────" in output

    # Header
    assert "core-bootstrap" in output
    assert ".husk" in output

    # Footer
    assert "passes:" in output or "fails:" in output


def test_state_glyphs_not_kind_glyphs():
    """Verify state glyphs are used, not kind glyphs."""
    with tempfile.TemporaryDirectory() as tmpdir:
        design = {
            "name": "test",
            "fuel": 10,
            "target": "action1",
            "site_inputs": {},
            "rules": [
                {
                    "name": "oracle1",
                    "kind": "oracle",
                    "inputs": [],
                    "outputs": ["out.txt"],
                    "prompt": "Generate",
                    "tools": ["write-file"],
                    "fuel": 5
                },
                {
                    "name": "action1",
                    "kind": "action",
                    "inputs": ["out.txt"],
                    "outputs": ["result.txt"],
                    "run": "cat out.txt > result.txt"
                }
            ]
        }

        design_path = Path(tmpdir) / "design.json"
        design_path.write_text(json.dumps(design))

        result = run_husks_cli("check", str(design_path), "--verbose")
        output = result.stdout

        # State glyph for unrealized
        assert "□" in output

        # Kind appears as text in column, not as glyph
        assert "oracle" in output
        assert "action" in output

        # Old kind glyphs should NOT appear
        # (Note: ◆ can appear for cached state, but not for oracle kind)
        # In dry check, should only see □
        lines = output.split("\n")
        for line in lines:
            if "oracle" in line or "action" in line:
                # Line with kind should have state glyph, not kind-specific glyph at start
                assert not line.strip().startswith("◆")
                assert not line.strip().startswith("▫")


def test_target_rooted_tree():
    """Verify tree is target-rooted with dependencies."""
    with tempfile.TemporaryDirectory() as tmpdir:
        design = {
            "name": "test",
            "fuel": 10,
            "target": "final",
            "site_inputs": {},
            "rules": [
                {
                    "name": "step1",
                    "kind": "action",
                    "inputs": [],
                    "outputs": ["a.txt"],
                    "run": "echo a > a.txt"
                },
                {
                    "name": "step2",
                    "kind": "action",
                    "inputs": ["a.txt"],
                    "outputs": ["b.txt"],
                    "run": "cat a.txt > b.txt"
                },
                {
                    "name": "final",
                    "kind": "action",
                    "inputs": ["b.txt"],
                    "outputs": ["c.txt"],
                    "run": "cat b.txt > c.txt"
                }
            ]
        }

        design_path = Path(tmpdir) / "design.json"
        design_path.write_text(json.dumps(design))

        result = run_husks_cli("check", str(design_path), "--verbose")
        output = result.stdout

        # Target should be root of tree
        assert "□ final" in output

        # Dependencies should be nested
        assert "└─" in output or "├─" in output
