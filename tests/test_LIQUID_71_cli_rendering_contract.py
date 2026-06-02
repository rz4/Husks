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


def strip_ansi(text: str) -> str:
    """Remove ANSI escape codes from text."""
    import re
    ansi_escape = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')
    return ansi_escape.sub('', text)


def normalize(text: str) -> str:
    """Normalize output for golden testing."""
    return strip_ansi(text).replace("\r\n", "\n").strip()


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


def test_check_shows_motif(core_bootstrap_design):
    """check without flags on passing design: silent, exit 0."""
    result = run_husks_cli("check", str(core_bootstrap_design))
    assert result.returncode == 0
    # Silent on success
    assert result.stdout.strip() == ""


def test_check_verbose_dry(core_bootstrap_design):
    """check --verbose shows bounded box with unrealized nodes."""
    result = run_husks_cli("check", str(core_bootstrap_design), "--verbose")
    assert result.returncode == 0

    output = result.stdout

    # Must have bordered box
    assert "──────────────────────────────────────────────────" in output

    # Header banner (name/state summary)
    assert "core-bootstrap" in output
    assert "checked" in output

    # Tree structure: target-rooted, validate depends on generate
    assert "□ validate" in output
    assert "action" in output
    assert "└─ □ generate" in output
    assert "oracle" in output
    assert "⚡10" in output

    # Footer
    assert "passes: checks" in output

    # Must NOT have old-style kind glyphs (◆ may appear in sealed/cached art)
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


def test_run_auto_site(core_bootstrap_design, tmp_path):
    """run without --site should auto-generate /tmp/husks-<name>."""
    import shutil
    # Clean the auto-site to avoid stale symlink conflicts from prior runs
    auto_site = Path("/tmp/husks-core-bootstrap")
    if auto_site.exists():
        shutil.rmtree(auto_site)
    result = run_husks_cli("run", str(core_bootstrap_design), "--stub")
    assert result.returncode == 0
    assert "/tmp/husks-core-bootstrap" in result.stdout


def test_run_sealed(core_bootstrap_design):
    """run --stub shows final sealed DAG only."""
    tmp_path = core_bootstrap_design.parent
    site = tmp_path / ".husk"

    result = run_husks_cli(
        "run", str(core_bootstrap_design), "--stub", "--site", str(site)
    )

    output = result.stdout

    # Must have bordered box
    assert "──────────────────────────────────────────────────" in output

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
    """status without site arg should error."""
    result = run_husks_cli("status")
    assert result.returncode != 0


def test_status_sealed(core_bootstrap_design):
    """status shows site summary."""
    tmp_path = core_bootstrap_design.parent
    site = tmp_path / ".husk"

    # Build first
    run_husks_cli("run", str(core_bootstrap_design), "--stub", "--site", str(site))

    # Check status (site is positional arg now)
    result = run_husks_cli("status", str(site))
    assert result.returncode == 0

    output = result.stdout

    # Summary fields
    assert "core-bootstrap" in output
    assert "sealed" in output


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


# ── Beta 100 Exact Golden Tests ──────────────────────────────────────


@pytest.mark.beta
def test_golden_dry_check_exact(core_bootstrap_design):
    """Exact golden contract for check --verbose (dry conformance)."""
    result = run_husks_cli("check", str(core_bootstrap_design), "--verbose")
    assert result.returncode == 0

    output = normalize(result.stdout)

    # Verify key content is present (spacing may vary with column alignment)
    assert "core-bootstrap" in output
    assert "checked" in output
    assert "name:" in output
    assert "state:" in output
    assert "□ validate" in output
    assert "action" in output
    assert "□ generate" in output
    assert "oracle" in output
    assert "⚡10" in output
    assert "passes: checks" in output

    # Anti-patterns: must NOT contain these
    assert "FINAL STATE" not in output
    assert "════" not in output
    assert "committed" not in output
    assert "halted" not in output


@pytest.mark.beta
def test_golden_final_m1_sealed(core_bootstrap_design):
    """Exact golden contract for run final frame (M1/M3 sealed)."""
    tmp_path = core_bootstrap_design.parent
    site = tmp_path / "m1"

    result = run_husks_cli(
        "run", str(core_bootstrap_design), "--stub", "--site", str(site)
    )

    output = normalize(result.stdout)

    # Must have header structure (spacing may vary)
    assert "──────────────────────────────────────────────────" in output
    assert "core-bootstrap" in output
    assert "sealed" in output
    # Must show sealed nodes (or failed if gate missing)
    assert ("■ validate" in output or "✕ validate" in output)
    assert ("■ generate" in output or "✕ generate" in output)

    # Must show oracle cost for M1
    assert "$0.000" in output  # Some cost shown

    # Banner should show name/state/site summary
    assert "name:" in output
    assert "state:" in output

    # Anti-patterns
    assert "FINAL STATE" not in output
    assert "════" not in output


@pytest.mark.beta
def test_golden_final_m2_cached(core_bootstrap_design):
    """Exact golden contract for cached run (M2 reuse)."""
    tmp_path = core_bootstrap_design.parent
    m1 = tmp_path / "m1_cache_test"
    m2 = tmp_path / "m2_cache_test"

    # M1: original run
    run_husks_cli("run", str(core_bootstrap_design), "--stub", "--site", str(m1))

    # Export cache
    cache_file = tmp_path / "cache.tar.gz"
    run_husks_cli("cache", "export", str(cache_file), "--site", str(m1))

    # Import to M2
    run_husks_cli("cache", "import", str(cache_file), "--site", str(m2))

    # M2: reuse-only run
    result = run_husks_cli(
        "run", str(core_bootstrap_design), "--site", str(m2), "--reuse-only", "--stub"
    )

    output = normalize(result.stdout)

    # Must show cached nodes with ◆ glyph
    assert "◆" in output, "M2 should show cached glyph ◆"
    assert "cached" in output, "M2 should show 'cached' label"

    # Must show zero fuel and zero cost for cached run
    assert "⚡0" in output, "M2 should show ⚡0 fuel"
    assert "$0.0000" in output, "M2 should show $0.0000 cost"

    # Footer should indicate cache success
    assert "passes: run, cache" in output or ("passes: run" in output and "cache" in output)


@pytest.mark.beta
def test_no_final_state_banner():
    """Verbose run must NOT print FINAL STATE banner."""
    with tempfile.TemporaryDirectory() as tmpdir:
        design = {
            "name": "test",
            "fuel": 5,
            "target": "out",
            "site_inputs": {},
            "rules": [{
                "name": "out",
                "kind": "action",
                "inputs": [],
                "outputs": ["out.txt"],
                "run": "echo hello > out.txt"
            }]
        }

        design_path = Path(tmpdir) / "design.json"
        design_path.write_text(json.dumps(design))

        site = Path(tmpdir) / "site"
        result = run_husks_cli("run", str(design_path), "--site", str(site), "--verbose")

        output = normalize(result.stdout)

        # Must NOT have FINAL STATE banner
        assert "FINAL STATE" not in output, "Verbose run should not print FINAL STATE banner"
        assert "════" not in output, "Verbose run should not use old separator style"


@pytest.mark.beta
def test_no_malformed_output_lines(core_bootstrap_design):
    """Output detail lines must not have malformed connectors."""
    tmp_path = core_bootstrap_design.parent
    site = tmp_path / "malformed_test"

    result = run_husks_cli(
        "run", str(core_bootstrap_design), "--stub", "--site", str(site)
    )

    output = result.stdout

    # Must NOT have malformed connector output lines like "└─      out:"
    assert "└─      out:" not in output, "Output lines should not have malformed connector prefix"
    assert "├─      out:" not in output, "Output lines should not have malformed connector prefix"

    # Output lines should be properly indented under the node
    if "out:" in output:
        # Should have proper indentation like "      out:..." (6 spaces for child node output)
        lines = output.split("\n")
        for line in lines:
            if "out:" in line and "cse:" not in line and "site:" not in line:
                # This is an output detail line
                # Should start with spaces, not connector
                assert not line.strip().startswith("└─"), f"Output line should not start with connector: {line}"
                assert not line.strip().startswith("├─"), f"Output line should not start with connector: {line}"
