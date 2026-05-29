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
    """compare-runs detects when M2 didn't actually reuse cache (Tasks 1/2/3)."""
    tmpdir = tempfile.mkdtemp(prefix="compare-runs-fail-")
    try:
        # Create schema-compliant reports where M2 didn't reuse cache
        # (Task 2: Reports must pass schema validation)
        m1_report = {
            "status": "committed",
            "root": "abc123",
            "run_id": "m1_run",
            "build": "test",
            "site": "/tmp/m1",
            "elapsed_s": 1.0,
            "fuel": {"start": 10, "end": 8},
            "cost": {"paid": 0.0008, "reused": 0.0, "projected": 0.0008},
            "delta": {"changed": [], "new": ["generate"], "unchanged": []},
            "nodes": [{
                "name": "generate",
                "kind": "oracle",
                "state": "fired",
                "classification": "converging",
                "prompt_len": 100,
                "prompt_trend": "flat",
                "fuel_consumed": 2,
                "fuel_trend": "falling",
                "output_hashes": ["hash1"],
                "output_changed": True,
                "cost": {"this_run": 0.0008, "first_paid": 0.0008, "per_rerun": 0.0},
                "cached": False,
                "tokens": {"input": 100, "output": 50},
                "seal": {"hash": "seal_hash", "recipe_changed": False},
            }]
        }

        # M2 report shows it didn't actually reuse cache (paid cost, fired state, cached=False)
        # Task 1/3: This should fail because M2 has no cache_hits and no cached node evidence
        m2_report = {
            "status": "committed",
            "root": "abc123",
            "run_id": "m2_run",
            "build": "test",
            "site": "/tmp/m2",
            "elapsed_s": 1.0,
            "fuel": {"start": 10, "end": 8},
            "cost": {"paid": 0.0008, "reused": 0.0, "projected": 0.0008},  # Should be 0!
            "delta": {"changed": [], "new": ["generate"], "unchanged": []},
            "nodes": [{
                "name": "generate",
                "kind": "oracle",
                "state": "fired",  # Should be sealed!
                "classification": "converging",
                "prompt_len": 100,
                "prompt_trend": "flat",
                "fuel_consumed": 2,
                "fuel_trend": "falling",
                "output_hashes": ["hash1"],
                "output_changed": True,
                "cost": {"this_run": 0.0008, "first_paid": 0.0008, "per_rerun": 0.0008},  # Should be 0!
                "cached": False,  # Should be True!
                "tokens": {"input": 100, "output": 50},
                "seal": {"hash": "seal_hash", "recipe_changed": False},
            }]
        }

        m3_report = {
            "status": "committed",
            "root": "abc123",
            "run_id": "m3_run",
            "build": "test",
            "site": "/tmp/m3",
            "elapsed_s": 1.0,
            "fuel": {"start": 10, "end": 8},
            "cost": {"paid": 0.0008, "reused": 0.0, "projected": 0.0008},
            "delta": {"changed": [], "new": ["generate"], "unchanged": []},
            "nodes": [{
                "name": "generate",
                "kind": "oracle",
                "state": "fired",
                "classification": "converging",
                "prompt_len": 100,
                "prompt_trend": "flat",
                "fuel_consumed": 2,
                "fuel_trend": "falling",
                "output_hashes": ["hash1"],
                "output_changed": True,
                "cost": {"this_run": 0.0008, "first_paid": 0.0008, "per_rerun": 0.0},
                "cached": False,
                "tokens": {"input": 100, "output": 50},
                "seal": {"hash": "seal_hash", "recipe_changed": False},
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
