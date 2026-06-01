"""
test_compare_runs.py -- Beta Gate C/F/G: three-machine proof via compare.

Tests the three-machine proof logic (formerly in compare-runs, now unified
into the compare command). Synthetic report tests call _three_machine_proof
directly; the real CLI test uses `husks compare` with site directories.
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
def test_compare_three_machine_proof():
    """compare validates three-machine proof from site reports."""
    tmpdir = tempfile.mkdtemp(prefix="compare-proof-")
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

        # Compare the three sites (reads .traces/report.json automatically)
        compare_result = run_husks_cli(
            "compare",
            str(m1_site), str(m2_site), str(m3_site),
            "--json",
        )

        assert compare_result.returncode == 0, (
            f"compare should pass for valid three-machine proof\n"
            f"stdout: {compare_result.stdout}\n"
            f"stderr: {compare_result.stderr}"
        )

        # Parse and validate comparison output
        comparison = json.loads(compare_result.stdout)
        assert comparison["equivalent"] is True, (
            f"Three-machine proof should be equivalent\n"
            f"Proof: {comparison.get('proof', {})}"
        )

        # Verify proof section is present
        proof = comparison.get("proof", {})
        assert proof, "Proof section should be present for 3 sites"
        assert proof["reports"] == 3

        # Verify checks passed
        checks = proof["checks"]
        assert checks.get("m1_paid_cost") is True, "M1 should have paid oracle cost"
        assert checks.get("m2_zero_oracle_calls") is True, "M2 should have zero oracle calls"
        assert checks.get("m2_zero_cost") is True, "M2 should have zero cost"
        assert checks.get("m3_paid_cost") is True, "M3 should have paid oracle cost"

        # Verify M1 and M3 costs are comparable
        runs = proof["runs"]
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
def test_proof_detects_m2_cache_miss():
    """Three-machine proof detects when M2 didn't actually reuse cache (Tasks 1/2/3)."""
    from husks.cli.cmd.compare import _three_machine_proof

    # Create schema-compliant reports where M2 didn't reuse cache
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

    # M2 report shows it didn't actually reuse cache
    m2_report = {
        "schema_version": "beta-1",
        "status": "committed",
        "root": "abc123",
        "run_id": "m2_run",
        "build": "test",
        "site": "/tmp/m2",
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
            "cost": {"this_run": 0.0008, "first_paid": 0.0008, "per_rerun": 0.0008},
            "cached": False,
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

    reports = [
        {"path": "/tmp/m1/.traces/report.json", "data": m1_report},
        {"path": "/tmp/m2/.traces/report.json", "data": m2_report},
        {"path": "/tmp/m3/.traces/report.json", "data": m3_report},
    ]

    comparison = _three_machine_proof(reports, json_output=True)
    assert comparison["equivalent"] is False
    assert len(comparison["violations"]) > 0
    assert any("M2" in v for v in comparison["violations"])


@pytest.mark.beta
@pytest.mark.gate_c
@pytest.mark.gate_f
def test_proof_rejects_non_committed_status():
    """Three-machine proof rejects reports with status != 'committed' (Task 1)."""
    from husks.cli.cmd.compare import _three_machine_proof

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

    m2_report = {
        "schema_version": "beta-1",
        "status": "halted",
        "root": None,
        "run_id": "m2_run",
        "build": "test",
        "site": "/tmp/m2",
        "elapsed_s": 1.0,
        "fuel": {"start": 10, "end": 8},
        "cost": {"paid": 0.0, "reused_estimate": 0.0, "projected_estimate": 0.0},
        "delta": {"changed": [], "new": [], "unchanged": []},
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

    reports = [
        {"path": "/tmp/m1/.traces/report.json", "data": m1_report},
        {"path": "/tmp/m2/.traces/report.json", "data": m2_report},
        {"path": "/tmp/m3/.traces/report.json", "data": m3_report},
    ]

    comparison = _three_machine_proof(reports, json_output=True)
    assert comparison["equivalent"] is False
    assert any("halted" in v for v in comparison.get("violations", []))


@pytest.mark.beta
@pytest.mark.gate_c
@pytest.mark.gate_f
def test_proof_requires_m1_oracle_evidence():
    """Three-machine proof requires M1 to have oracle_calls > 0 (Task 2)."""
    from husks.cli.cmd.compare import _three_machine_proof

    # M1 report with cost_paid > 0 BUT no actual oracle node that fired
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

    reports = [
        {"path": "/tmp/m1/.traces/report.json", "data": m1_report},
        {"path": "/tmp/m2/.traces/report.json", "data": m2_report},
        {"path": "/tmp/m3/.traces/report.json", "data": m3_report},
    ]

    comparison = _three_machine_proof(reports, json_output=True)
    assert comparison["equivalent"] is False
    assert any("M1" in v and ("oracle" in v.lower() or "fire" in v.lower())
               for v in comparison["violations"]), f"Expected M1 oracle violation, got: {comparison['violations']}"


@pytest.mark.beta
@pytest.mark.gate_c
@pytest.mark.gate_f
def test_proof_requires_m3_oracle_evidence():
    """Three-machine proof requires M3 to have oracle_calls > 0 (Task 2)."""
    from husks.cli.cmd.compare import _three_machine_proof

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

    # M3 with no actual oracle node that fired
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

    reports = [
        {"path": "/tmp/m1/.traces/report.json", "data": m1_report},
        {"path": "/tmp/m2/.traces/report.json", "data": m2_report},
        {"path": "/tmp/m3/.traces/report.json", "data": m3_report},
    ]

    comparison = _three_machine_proof(reports, json_output=True)
    assert comparison["equivalent"] is False
    assert any("M3" in v and ("oracle" in v.lower() or "fire" in v.lower())
               for v in comparison["violations"]), f"Expected M3 oracle violation, got: {comparison['violations']}"


@pytest.mark.beta
@pytest.mark.gate_f
def test_run_json_includes_oracle_evidence():
    """run --json includes oracle_calls, cache_hits, and cached_nodes (Task 3)."""
    tmpdir = tempfile.mkdtemp(prefix="run-oracle-evidence-")
    try:
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

        assert "oracle_calls" in m1_report, "Report should include oracle_calls"
        assert "cache_hits" in m1_report, "Report should include cache_hits"
        assert "cached_nodes" in m1_report, "Report should include cached_nodes"

        assert m1_report["oracle_calls"] > 0
        assert m1_report["cache_hits"] == 0
        assert len(m1_report["cached_nodes"]) == 0

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

        m2_report = json.loads(m2_result.stdout)

        assert "oracle_calls" in m2_report
        assert "cache_hits" in m2_report
        assert "cached_nodes" in m2_report

        assert m2_report["oracle_calls"] == 0
        assert m2_report["cache_hits"] > 0
        assert len(m2_report["cached_nodes"]) > 0

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


@pytest.mark.beta
@pytest.mark.gate_c
@pytest.mark.gate_f
def test_proof_rejects_cost_drift():
    """Three-machine proof fails when M1 and M3 costs are not comparable."""
    from husks.cli.cmd.compare import _three_machine_proof

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

    # M3 with HUGE cost drift (999.0 vs 0.0008)
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

    reports = [
        {"path": "/tmp/m1/.traces/report.json", "data": m1_report},
        {"path": "/tmp/m2/.traces/report.json", "data": m2_report},
        {"path": "/tmp/m3/.traces/report.json", "data": m3_report},
    ]

    comparison = _three_machine_proof(reports, json_output=True)
    assert comparison["equivalent"] is False
    assert len(comparison["violations"]) > 0
    assert any("cost" in v.lower() and ("comparable" in v.lower() or "tolerance" in v.lower())
                for v in comparison["violations"]), (
        f"Should have cost violation, got: {comparison['violations']}"
    )
