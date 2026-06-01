"""
test_compare_runs.py -- Beta Gate C/F/G: compare-runs command.

Tests the `husks compare-runs` command for validating three-machine proof
from JSON report files.
"""

import json
import tempfile
import shutil
from pathlib import Path

import pytest

from conftest import run_husks_cli


@pytest.mark.beta
@pytest.mark.gate_c
@pytest.mark.gate_f
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


@pytest.mark.beta
@pytest.mark.gate_c
@pytest.mark.gate_f
def test_compare_runs_detects_m2_cache_miss():
    """compare-runs detects when M2 didn't actually reuse cache (Tasks 1/2/3)."""
    tmpdir = tempfile.mkdtemp(prefix="compare-runs-fail-")
    try:
        # Create schema-compliant reports where M2 didn't reuse cache
        # (Task 2: Reports must pass schema validation)
        # (Task 9: Include schema_version)
        m1_report = {
            "schema_version": "beta-1",
            "status": "committed",
            "root": "abc123",
            "run_id": "m1_run",
            "build": "test",
            "site": "/tmp/m1",
            "elapsed_s": 1.0,
            "fuel": {"start": 10, "end": 8},
            "cost": {"paid": 0.0008, "reused_estimate": 0.0, "projected_estimate": 0.0008},
            "delta": {"changed": [], "new": ["generate"], "unchanged": []},
            # Beta Readiness Task 4: Add required oracle evidence fields
            "oracle_calls": 1,
            "cache_hits": 0,
            "cached_nodes": [],
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
            "schema_version": "beta-1",
            "status": "committed",
            "root": "abc123",
            "run_id": "m2_run",
            "build": "test",
            "site": "/tmp/m2",
            "elapsed_s": 1.0,
            "fuel": {"start": 10, "end": 8},
            "cost": {"paid": 0.0008, "reused_estimate": 0.0, "projected_estimate": 0.0008},  # Should be 0!
            "delta": {"changed": [], "new": ["generate"], "unchanged": []},
            # Beta Readiness Task 4: Add required oracle evidence fields
            "oracle_calls": 1,
            "cache_hits": 0,
            "cached_nodes": [],
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
            "schema_version": "beta-1",
            "status": "committed",
            "root": "abc123",
            "run_id": "m3_run",
            "build": "test",
            "site": "/tmp/m3",
            "elapsed_s": 1.0,
            "fuel": {"start": 10, "end": 8},
            "cost": {"paid": 0.0008, "reused_estimate": 0.0, "projected_estimate": 0.0008},
            "delta": {"changed": [], "new": ["generate"], "unchanged": []},
            # Beta Readiness Task 4: Add required oracle evidence fields
            "oracle_calls": 1,
            "cache_hits": 0,
            "cached_nodes": [],
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


@pytest.mark.beta
@pytest.mark.gate_c
@pytest.mark.gate_f
def test_compare_runs_rejects_non_committed_status():
    """compare-runs rejects reports with status != 'committed' (Task 1 - New)."""
    tmpdir = tempfile.mkdtemp(prefix="compare-runs-status-")
    try:
        # Create a valid M1 report
        m1_report = {
            "schema_version": "beta-1",
            "status": "committed",
            "root": "abc123",
            "run_id": "m1_run",
            "build": "test",
            "site": "/tmp/m1",
            "elapsed_s": 1.0,
            "fuel": {"start": 10, "end": 8},
            "cost": {"paid": 0.0008, "reused_estimate": 0.0, "projected_estimate": 0.0008},
            "delta": {"changed": [], "new": ["generate"], "unchanged": []},
            # Beta Readiness Task 4: Add required oracle evidence fields
            "oracle_calls": 1,
            "cache_hits": 0,
            "cached_nodes": [],
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

        # M2 report with status = "halted" (SHOULD BE REJECTED)
        m2_report = {
            "schema_version": "beta-1",
            "status": "halted",  # BUG: compare-runs should reject this!
            "root": None,
            "run_id": "m2_run",
            "build": "test",
            "site": "/tmp/m2",
            "elapsed_s": 1.0,
            "fuel": {"start": 10, "end": 8},
            "cost": {"paid": 0.0, "reused_estimate": 0.0, "projected_estimate": 0.0},
            "delta": {"changed": [], "new": [], "unchanged": []},
            # Beta Readiness Task 4: Add required oracle evidence fields
            "oracle_calls": 1,
            "cache_hits": 0,
            "cached_nodes": [],
            "nodes": [],
            "diagnosis": {
                "error": "Build halted",
                "failed_nodes": []
            }
        }

        m3_report = {
            "schema_version": "beta-1",
            "status": "committed",
            "root": "abc123",
            "run_id": "m3_run",
            "build": "test",
            "site": "/tmp/m3",
            "elapsed_s": 1.0,
            "fuel": {"start": 10, "end": 8},
            "cost": {"paid": 0.0008, "reused_estimate": 0.0, "projected_estimate": 0.0008},
            "delta": {"changed": [], "new": ["generate"], "unchanged": []},
            # Beta Readiness Task 4: Add required oracle evidence fields
            "oracle_calls": 1,
            "cache_hits": 0,
            "cached_nodes": [],
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

        # Write reports
        m1_json = Path(tmpdir) / "m1.json"
        m2_json = Path(tmpdir) / "m2.json"
        m3_json = Path(tmpdir) / "m3.json"

        m1_json.write_text(json.dumps(m1_report))
        m2_json.write_text(json.dumps(m2_report))
        m3_json.write_text(json.dumps(m3_report))

        # compare-runs should REJECT because M2 status is "halted"
        compare_result = run_husks_cli(
            "compare-runs",
            str(m1_json), str(m2_json), str(m3_json),
            "--json",
        )

        # Should fail with exit code 1 (BUILD_FAIL)
        assert compare_result.returncode == 1, (
            f"compare-runs should reject halted status (exit 1), got {compare_result.returncode}\n"
            f"stdout: {compare_result.stdout}\n"
            f"stderr: {compare_result.stderr}"
        )

        # Check error message in JSON output
        error_output = json.loads(compare_result.stdout)
        assert error_output["equivalent"] is False
        assert "non_committed_status" in error_output.get("error", "")
        assert any("halted" in v for v in error_output.get("violations", []))

        print("\n✓ Task 1 (New): compare-runs correctly rejects non-committed status")

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


@pytest.mark.beta
@pytest.mark.gate_c
@pytest.mark.gate_f
def test_compare_runs_requires_m1_oracle_evidence():
    """compare-runs requires M1 to have oracle_calls > 0 (Task 2 - New)."""
    tmpdir = tempfile.mkdtemp(prefix="compare-runs-m1-evidence-")
    try:
        # M1 report with cost_paid > 0 BUT oracle_calls == 0 (mocked/invalid)
        # This simulates a fraudulent report that claims cost without oracle evidence
        m1_report = {
            "schema_version": "beta-1",
            "status": "committed",
            "root": "abc123",
            "run_id": "m1_run",
            "build": "test",
            "site": "/tmp/m1",
            "elapsed_s": 1.0,
            "fuel": {"start": 10, "end": 8},
            "cost": {"paid": 0.0008, "reused_estimate": 0.0, "projected_estimate": 0.0008},  # Claims cost
            "delta": {"changed": [], "new": ["generate"], "unchanged": []},
            # Beta Readiness Task 4: Add required oracle evidence fields
            "oracle_calls": 1,
            "cache_hits": 0,
            "cached_nodes": [],
            "nodes": [{
                "name": "generate",
                "kind": "oracle",
                "state": "sealed",  # Sealed but no oracle call
                "classification": "converging",
                "prompt_len": 100,
                "prompt_trend": "flat",
                "fuel_consumed": 0,  # No fuel consumed
                "fuel_trend": "flat",
                "output_hashes": ["hash1"],
                "output_changed": False,
                "cost": {"this_run": 0.0, "first_paid": 0.0008, "per_rerun": 0.0},  # No cost this run
                "cached": True,  # Claims cache, but M1 shouldn't have cache
                "tokens": {"input": 0, "output": 0},  # No tokens
                "seal": {"hash": "seal_hash", "recipe_changed": False},
            }]
        }

        # Valid M2 (cache reuse)
        m2_report = {
            "schema_version": "beta-1",
            "status": "committed",
            "root": "abc123",
            "run_id": "m2_run",
            "build": "test",
            "site": "/tmp/m2",
            "elapsed_s": 1.0,
            "fuel": {"start": 10, "end": 8},
            "cost": {"paid": 0.0, "reused_estimate": 0.0008, "projected_estimate": 0.0},
            "delta": {"changed": [], "new": [], "unchanged": ["generate"]},
            # Beta Readiness Task 4: Add required oracle evidence fields
            "oracle_calls": 1,
            "cache_hits": 0,
            "cached_nodes": [],
            "nodes": [{
                "name": "generate",
                "kind": "oracle",
                "state": "sealed",
                "classification": "converging",
                "prompt_len": 100,
                "prompt_trend": "flat",
                "fuel_consumed": 0,
                "fuel_trend": "flat",
                "output_hashes": ["hash1"],
                "output_changed": False,
                "cost": {"this_run": 0.0, "first_paid": 0.0008, "per_rerun": 0.0},
                "cached": True,
                "tokens": {"input": 0, "output": 0},
                "seal": {"hash": "seal_hash", "recipe_changed": False},
            }]
        }

        # Valid M3 (fired oracle)
        m3_report = {
            "schema_version": "beta-1",
            "status": "committed",
            "root": "abc123",
            "run_id": "m3_run",
            "build": "test",
            "site": "/tmp/m3",
            "elapsed_s": 1.0,
            "fuel": {"start": 10, "end": 8},
            "cost": {"paid": 0.0008, "reused_estimate": 0.0, "projected_estimate": 0.0008},
            "delta": {"changed": [], "new": ["generate"], "unchanged": []},
            # Beta Readiness Task 4: Add required oracle evidence fields
            "oracle_calls": 1,
            "cache_hits": 0,
            "cached_nodes": [],
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

        # Write reports
        m1_json = Path(tmpdir) / "m1.json"
        m2_json = Path(tmpdir) / "m2.json"
        m3_json = Path(tmpdir) / "m3.json"

        m1_json.write_text(json.dumps(m1_report))
        m2_json.write_text(json.dumps(m2_report))
        m3_json.write_text(json.dumps(m3_report))

        # compare-runs should REJECT because M1 has oracle_calls == 0
        compare_result = run_husks_cli(
            "compare-runs",
            str(m1_json), str(m2_json), str(m3_json),
            "--json",
        )

        assert compare_result.returncode != 0, "Should fail when M1 has no oracle evidence"

        comparison = json.loads(compare_result.stdout)
        assert comparison["equivalent"] is False
        # Check for M1-related violations (either oracle_calls or oracle node evidence)
        assert any("M1" in v and ("oracle" in v.lower() or "fire" in v.lower())
                   for v in comparison["violations"]), f"Expected M1 oracle violation, got: {comparison['violations']}"

        print("\n✓ Task 2 (New): compare-runs correctly requires M1 oracle evidence")

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


@pytest.mark.beta
@pytest.mark.gate_c
@pytest.mark.gate_f
def test_compare_runs_requires_m3_oracle_evidence():
    """compare-runs requires M3 to have oracle_calls > 0 (Task 2 - New)."""
    tmpdir = tempfile.mkdtemp(prefix="compare-runs-m3-evidence-")
    try:
        # Valid M1 (fired oracle)
        m1_report = {
            "schema_version": "beta-1",
            "status": "committed",
            "root": "abc123",
            "run_id": "m1_run",
            "build": "test",
            "site": "/tmp/m1",
            "elapsed_s": 1.0,
            "fuel": {"start": 10, "end": 8},
            "cost": {"paid": 0.0008, "reused_estimate": 0.0, "projected_estimate": 0.0008},
            "delta": {"changed": [], "new": ["generate"], "unchanged": []},
            # Beta Readiness Task 4: Add required oracle evidence fields
            "oracle_calls": 1,
            "cache_hits": 0,
            "cached_nodes": [],
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

        # Valid M2 (cache reuse)
        m2_report = {
            "schema_version": "beta-1",
            "status": "committed",
            "root": "abc123",
            "run_id": "m2_run",
            "build": "test",
            "site": "/tmp/m2",
            "elapsed_s": 1.0,
            "fuel": {"start": 10, "end": 8},
            "cost": {"paid": 0.0, "reused_estimate": 0.0008, "projected_estimate": 0.0},
            "delta": {"changed": [], "new": [], "unchanged": ["generate"]},
            # Beta Readiness Task 4: Add required oracle evidence fields
            "oracle_calls": 1,
            "cache_hits": 0,
            "cached_nodes": [],
            "nodes": [{
                "name": "generate",
                "kind": "oracle",
                "state": "sealed",
                "classification": "converging",
                "prompt_len": 100,
                "prompt_trend": "flat",
                "fuel_consumed": 0,
                "fuel_trend": "flat",
                "output_hashes": ["hash1"],
                "output_changed": False,
                "cost": {"this_run": 0.0, "first_paid": 0.0008, "per_rerun": 0.0},
                "cached": True,
                "tokens": {"input": 0, "output": 0},
                "seal": {"hash": "seal_hash", "recipe_changed": False},
            }]
        }

        # M3 report with cost_paid > 0 BUT oracle_calls == 0 (mocked/invalid)
        m3_report = {
            "schema_version": "beta-1",
            "status": "committed",
            "root": "abc123",
            "run_id": "m3_run",
            "build": "test",
            "site": "/tmp/m3",
            "elapsed_s": 1.0,
            "fuel": {"start": 10, "end": 8},
            "cost": {"paid": 0.0008, "reused_estimate": 0.0, "projected_estimate": 0.0008},  # Claims cost
            "delta": {"changed": [], "new": ["generate"], "unchanged": []},
            # Beta Readiness Task 4: Add required oracle evidence fields
            "oracle_calls": 1,
            "cache_hits": 0,
            "cached_nodes": [],
            "nodes": [{
                "name": "generate",
                "kind": "oracle",
                "state": "sealed",  # Sealed but no oracle call
                "classification": "converging",
                "prompt_len": 100,
                "prompt_trend": "flat",
                "fuel_consumed": 0,  # No fuel consumed
                "fuel_trend": "flat",
                "output_hashes": ["hash1"],
                "output_changed": False,
                "cost": {"this_run": 0.0, "first_paid": 0.0008, "per_rerun": 0.0},  # No cost this run
                "cached": True,  # Claims cache, but M3 shouldn't have cache
                "tokens": {"input": 0, "output": 0},  # No tokens
                "seal": {"hash": "seal_hash", "recipe_changed": False},
            }]
        }

        # Write reports
        m1_json = Path(tmpdir) / "m1.json"
        m2_json = Path(tmpdir) / "m2.json"
        m3_json = Path(tmpdir) / "m3.json"

        m1_json.write_text(json.dumps(m1_report))
        m2_json.write_text(json.dumps(m2_report))
        m3_json.write_text(json.dumps(m3_report))

        # compare-runs should REJECT because M3 has oracle_calls == 0
        compare_result = run_husks_cli(
            "compare-runs",
            str(m1_json), str(m2_json), str(m3_json),
            "--json",
        )

        assert compare_result.returncode != 0, "Should fail when M3 has no oracle evidence"

        comparison = json.loads(compare_result.stdout)
        assert comparison["equivalent"] is False
        # Check for M3-related violations (either oracle_calls or oracle node evidence)
        assert any("M3" in v and ("oracle" in v.lower() or "fire" in v.lower())
                   for v in comparison["violations"]), f"Expected M3 oracle violation, got: {comparison['violations']}"

        print("\n✓ Task 2 (New): compare-runs correctly requires M3 oracle evidence")

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


@pytest.mark.beta
@pytest.mark.gate_f
def test_run_json_includes_oracle_evidence():
    """run --json includes oracle_calls, cache_hits, and cached_nodes (Task 3 - New)."""
    tmpdir = tempfile.mkdtemp(prefix="run-oracle-evidence-")
    try:
        # Use beta seed example to generate real reports
        beta_seed_dir = Path(__file__).parent.parent / "examples" / "beta_seed"
        design_path = beta_seed_dir / "design.json"

        # Machine 1: Build with stub oracle (should have oracle_calls > 0)
        m1_site = Path(tmpdir) / "m1_site"
        m1_site.mkdir()
        m1_result = run_husks_cli(
            "run", str(design_path),
            "--site", str(m1_site),
            "--stub",
            "--json",
        )
        assert m1_result.returncode == 0

        m1_report = json.loads(m1_result.stdout)

        # Task 3 (New): Verify oracle evidence fields are present
        assert "oracle_calls" in m1_report, "Report should include oracle_calls"
        assert "cache_hits" in m1_report, "Report should include cache_hits"
        assert "cached_nodes" in m1_report, "Report should include cached_nodes"

        # M1 should have fired oracles
        assert m1_report["oracle_calls"] > 0, f"M1 should have oracle_calls > 0, got {m1_report['oracle_calls']}"
        assert m1_report["cache_hits"] == 0, f"M1 should have cache_hits == 0, got {m1_report['cache_hits']}"
        assert len(m1_report["cached_nodes"]) == 0, f"M1 should have no cached_nodes, got {m1_report['cached_nodes']}"

        # Export cache
        cache_file = Path(tmpdir) / "cache.tar.gz"
        run_husks_cli(
            "cache", "export", str(cache_file),
            "--site", str(m1_site),
            "--json",
        )

        # Machine 2: Import cache and reuse (should have cache_hits > 0, oracle_calls == 0)
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

        m2_report = json.loads(m2_result.stdout)

        # Task 3 (New): Verify M2 oracle evidence shows cache reuse
        assert "oracle_calls" in m2_report
        assert "cache_hits" in m2_report
        assert "cached_nodes" in m2_report

        # M2 should have reused_estimate from cache
        assert m2_report["oracle_calls"] == 0, f"M2 should have oracle_calls == 0, got {m2_report['oracle_calls']}"
        assert m2_report["cache_hits"] > 0, f"M2 should have cache_hits > 0, got {m2_report['cache_hits']}"
        assert len(m2_report["cached_nodes"]) > 0, f"M2 should have cached_nodes, got {m2_report['cached_nodes']}"

        print("\n✓ Task 3 (New): run --json includes oracle_calls, cache_hits, cached_nodes")
        print(f"  M1: {m1_report['oracle_calls']} oracle calls, {m1_report['cache_hits']} cache hits")
        print(f"  M2: {m2_report['oracle_calls']} oracle calls, {m2_report['cache_hits']} cache hits")
        print(f"  M2 cached nodes: {m2_report['cached_nodes']}")

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


@pytest.mark.beta
@pytest.mark.gate_c
@pytest.mark.gate_f
def test_compare_runs_rejects_cost_drift():
    """compare-runs fails when M1 and M3 costs are not comparable (Beta Readiness Task 3)."""
    tmpdir = tempfile.mkdtemp(prefix="compare-runs-cost-drift-")
    try:
        # M1 report with cost = 0.0008
        m1_report = {
            "schema_version": "beta-1",
            "status": "committed",
            "root": "abc123",
            "run_id": "m1_run",
            "build": "test",
            "site": "/tmp/m1",
            "elapsed_s": 1.0,
            "fuel": {"start": 10, "end": 8},
            "cost": {"paid": 0.0008, "reused_estimate": 0.0, "projected_estimate": 0.0008},
            "delta": {"changed": [], "new": ["generate"], "unchanged": []},
            "oracle_calls": 1,
            "cache_hits": 0,
            "cached_nodes": [],
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

        # M2 report (valid cache reuse)
        m2_report = {
            "schema_version": "beta-1",
            "status": "committed",
            "root": "abc123",
            "run_id": "m2_run",
            "build": "test",
            "site": "/tmp/m2",
            "elapsed_s": 1.0,
            "fuel": {"start": 10, "end": 8},
            "cost": {"paid": 0.0, "reused_estimate": 0.0008, "projected_estimate": 0.0},
            "delta": {"changed": [], "new": [], "unchanged": ["generate"]},
            "oracle_calls": 0,
            "cache_hits": 1,
            "cached_nodes": ["generate"],
            "nodes": [{
                "name": "generate",
                "kind": "oracle",
                "state": "sealed",
                "classification": "converging",
                "prompt_len": 100,
                "prompt_trend": "flat",
                "fuel_consumed": 0,
                "fuel_trend": "flat",
                "output_hashes": ["hash1"],
                "output_changed": False,
                "cost": {"this_run": 0.0, "first_paid": 0.0008, "per_rerun": 0.0},
                "cached": True,
                "tokens": {"input": 0, "output": 0},
                "seal": {"hash": "seal_hash", "recipe_changed": False},
            }]
        }

        # M3 report with HUGE cost drift (999.0 vs 0.0008)
        m3_report = {
            "schema_version": "beta-1",
            "status": "committed",
            "root": "abc123",
            "run_id": "m3_run",
            "build": "test",
            "site": "/tmp/m3",
            "elapsed_s": 1.0,
            "fuel": {"start": 10, "end": 8},
            "cost": {"paid": 999.0, "reused_estimate": 0.0, "projected_estimate": 999.0},
            "delta": {"changed": [], "new": ["generate"], "unchanged": []},
            "oracle_calls": 1,
            "cache_hits": 0,
            "cached_nodes": [],
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
                "cost": {"this_run": 999.0, "first_paid": 999.0, "per_rerun": 0.0},
                "cached": False,
                "tokens": {"input": 100, "output": 50},
                "seal": {"hash": "seal_hash", "recipe_changed": False},
            }]
        }

        # Write reports
        m1_json = Path(tmpdir) / "m1.json"
        m2_json = Path(tmpdir) / "m2.json"
        m3_json = Path(tmpdir) / "m3.json"

        m1_json.write_text(json.dumps(m1_report))
        m2_json.write_text(json.dumps(m2_report))
        m3_json.write_text(json.dumps(m3_report))

        # compare-runs should FAIL due to cost drift
        compare_result = run_husks_cli(
            "compare-runs",
            str(m1_json), str(m2_json), str(m3_json),
            "--json",
        )

        assert compare_result.returncode != 0, (
            "compare-runs should fail when M1 and M3 costs differ significantly"
        )

        comparison = json.loads(compare_result.stdout)
        assert comparison["equivalent"] is False, "Should not be equivalent"
        assert len(comparison["violations"]) > 0, "Should have violations"
        assert any("cost" in v.lower() and ("comparable" in v.lower() or "tolerance" in v.lower())
                    for v in comparison["violations"]), (
            f"Should have cost violation, got: {comparison['violations']}"
        )

        print("\n✓ Beta Readiness Task 3: compare-runs rejects cost drift (0.0008 vs 999.0)")

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)
