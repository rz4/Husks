"""
test_compare_runs.py -- Beta Gate C/F/G: compare-runs command.

Tests the `husks compare-runs` command for validating three-machine proof
from JSON report files.
"""

import json
import tempfile
import shutil
from pathlib import Path

from conftest import run_husks_cli


def test_compare_runs_three_machine_proof():
    """compare-runs validates three-machine proof from JSON reports."""
    tmpdir = tempfile.mkdtemp(prefix="compare-runs-")
    try:
        # Use beta seed example to generate real reports
        beta_seed_dir = Path(__file__).parent.parent / "examples" / "beta_seed"
        design_path = beta_seed_dir / "design.json"

        # Machine 1: Build with stub oracle
        m1_site = Path(tmpdir) / "m1_site"
        m1_site.mkdir()
        m1_result = run_husks_cli(
            "run", str(design_path),
            "--site", str(m1_site),
            "--stub",
            "--json",
        )
        assert m1_result.returncode == 0
        m1_json = Path(tmpdir) / "m1.json"
        m1_json.write_text(m1_result.stdout)

        # Export cache
        cache_file = Path(tmpdir) / "cache.tar.gz"
        run_husks_cli(
            "cache", "export", str(cache_file),
            "--site", str(m1_site),
            "--json",
        )

        # Machine 2: Import cache and reuse
        m2_site = Path(tmpdir) / "m2_site"
        m2_site.mkdir()
        run_husks_cli(
            "cache", "import", str(cache_file),
            "--site", str(m2_site),
            "--json",
        )
        m2_result = run_husks_cli(
            "run", str(design_path),
            "--site", str(m2_site),
            "--reuse-only",
            "--json",
        )
        assert m2_result.returncode == 0
        m2_json = Path(tmpdir) / "m2.json"
        m2_json.write_text(m2_result.stdout)

        # Machine 3: Independent build
        m3_site = Path(tmpdir) / "m3_site"
        m3_site.mkdir()
        m3_result = run_husks_cli(
            "run", str(design_path),
            "--site", str(m3_site),
            "--stub",
            "--json",
        )
        assert m3_result.returncode == 0
        m3_json = Path(tmpdir) / "m3.json"
        m3_json.write_text(m3_result.stdout)

        # Now compare the three reports
        compare_result = run_husks_cli(
            "compare-runs",
            str(m1_json), str(m2_json), str(m3_json),
            "--json",
        )

        assert compare_result.returncode == 0, (
            f"compare-runs should pass for valid three-machine proof\n"
            f"stdout: {compare_result.stdout}\n"
            f"stderr: {compare_result.stderr}"
        )

        # Parse and validate comparison output
        comparison = json.loads(compare_result.stdout)
        assert comparison["reports"] == 3
        assert comparison["equivalent"] is True, (
            f"Three-machine proof should be equivalent\n"
            f"Violations: {comparison.get('violations', [])}"
        )

        # Verify checks passed
        checks = comparison["checks"]
        assert checks.get("m1_paid_cost") is True, "M1 should have paid oracle cost"
        assert checks.get("m2_zero_oracle_calls") is True, "M2 should have zero oracle calls"
        assert checks.get("m2_zero_cost") is True, "M2 should have zero cost"
        assert checks.get("m3_paid_cost") is True, "M3 should have paid oracle cost"

        # Verify M1 and M3 costs are comparable
        runs = comparison["runs"]
        m1_cost = runs[0]["cost_paid"]
        m3_cost = runs[2]["cost_paid"]
        assert m1_cost > 0, "M1 should have non-zero cost"
        assert m3_cost > 0, "M3 should have non-zero cost"
        # For stub oracle, costs should be exactly equal
        assert m1_cost == m3_cost, f"Stub oracle costs should match: {m1_cost} vs {m3_cost}"

        # Verify M2 has zero cost
        m2_cost = runs[1]["cost_paid"]
        assert m2_cost == 0.0, f"M2 should have zero cost, got {m2_cost}"

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_compare_runs_detects_m2_cache_miss():
    """compare-runs detects when M2 didn't actually reuse cache."""
    tmpdir = tempfile.mkdtemp(prefix="compare-runs-fail-")
    try:
        # Create fake reports where M2 didn't reuse cache
        m1_report = {
            "status": "committed",
            "cost": {"paid": 0.0008, "reused": 0.0, "projected": 0.0008},
            "root": "abc123",
            "nodes": [{
                "name": "generate",
                "kind": "oracle",
                "state": "fired",
                "cost": {"this_run": 0.0008},
                "cached": False,
            }]
        }

        m2_report = {
            "status": "committed",
            "cost": {"paid": 0.0008, "reused": 0.0, "projected": 0.0008},  # Should be 0!
            "root": "abc123",
            "nodes": [{
                "name": "generate",
                "kind": "oracle",
                "state": "fired",  # Should be sealed!
                "cost": {"this_run": 0.0008},  # Should be 0!
                "cached": False,  # Should be True!
            }]
        }

        m3_report = {
            "status": "committed",
            "cost": {"paid": 0.0008, "reused": 0.0, "projected": 0.0008},
            "root": "abc123",
            "nodes": [{
                "name": "generate",
                "kind": "oracle",
                "state": "fired",
                "cost": {"this_run": 0.0008},
                "cached": False,
            }]
        }

        m1_json = Path(tmpdir) / "m1.json"
        m2_json = Path(tmpdir) / "m2.json"
        m3_json = Path(tmpdir) / "m3.json"

        m1_json.write_text(json.dumps(m1_report))
        m2_json.write_text(json.dumps(m2_report))
        m3_json.write_text(json.dumps(m3_report))

        # Compare should fail
        compare_result = run_husks_cli(
            "compare-runs",
            str(m1_json), str(m2_json), str(m3_json),
            "--json",
        )

        assert compare_result.returncode != 0, "Should fail when M2 didn't reuse cache"

        comparison = json.loads(compare_result.stdout)
        assert comparison["equivalent"] is False
        assert len(comparison["violations"]) > 0
        assert any("M2" in v for v in comparison["violations"])

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)
