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
