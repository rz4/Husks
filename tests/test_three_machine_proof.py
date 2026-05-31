"""
Three-Machine Proof Test (Beta Gate 95)

Validates core-bootstrap reproducibility across three machines:
- M1: Fresh run on site1 (seals and commits)
- M2: Rerun on site1 (fully cached, zero oracle calls)
- M3: Fresh run on site3 (seals again, comparable cost to M1)

All three should produce the same build root.
M2 should have explicit cache evidence.
"""

import json
import os
import tempfile
from pathlib import Path
import shutil

import pytest

from conftest import run_husks_cli


@pytest.fixture
def bootstrap_design(tmp_path):
    """Create a minimal bootstrap-style design for testing."""
    design = {
        "name": "test-bootstrap",
        "fuel": 10,
        "target": "action1",
        "site_inputs": {},
        "rules": [
            {
                "name": "oracle1",
                "kind": "oracle",
                "inputs": [],
                "outputs": ["output.txt"],
                "prompt": "Write 'hello' to output.txt",
                "tools": ["write-file"],
                "fuel": 5,
            },
            {
                "name": "action1",
                "kind": "action",
                "inputs": ["output.txt"],
                "outputs": ["result.txt"],
                "run": "cat output.txt > result.txt",
            },
        ],
    }

    design_path = tmp_path / "design.json"
    design_path.write_text(json.dumps(design, indent=2))
    return design_path


def test_three_machine_proof(bootstrap_design):
    """Three-machine proof: M1 fresh, M2 cached, M3 fresh → same root."""
    tmp_path = bootstrap_design.parent

    # Machine 1: Fresh run on site1
    site1 = tmp_path / "site1"
    result_m1 = run_husks_cli(
        "run", str(bootstrap_design), "--stub", "--site", str(site1), "--json"
    )
    assert result_m1.returncode == 0, f"M1 failed: {result_m1.stderr}"
    m1_data = json.loads(result_m1.stdout)
    m1_root = m1_data.get("root")
    m1_cost = m1_data.get("cost", 0.0)
    m1_nodes = {n["name"]: n for n in m1_data["nodes"]}

    # Verify M1 sealed outputs
    assert m1_data["status"] == "committed", "M1 should commit successfully"
    assert m1_root is not None, "M1 should produce a build root"
    assert m1_nodes["oracle1"]["state"] == "sealed", "M1 oracle should seal"

    # Machine 2: Rerun on site1 (should be fully cached)
    result_m2 = run_husks_cli(
        "run", str(bootstrap_design), "--stub", "--site", str(site1), "--json"
    )
    assert result_m2.returncode == 0, f"M2 failed: {result_m2.stderr}"
    m2_data = json.loads(result_m2.stdout)
    m2_root = m2_data.get("root")
    m2_nodes = {n["name"]: n for n in m2_data["nodes"]}

    # Verify M2 reused from cache
    assert m2_root == m1_root, "M2 root should match M1 root"
    assert m2_nodes["oracle1"]["state"] == "cached", "M2 oracle should be cached"
    assert m2_nodes["oracle1"].get("cache") is True, "M2 should have cache=true flag"

    # Machine 3: Fresh run on site3 (independent site)
    site3 = tmp_path / "site3"
    result_m3 = run_husks_cli(
        "run", str(bootstrap_design), "--stub", "--site", str(site3), "--json"
    )
    assert result_m3.returncode == 0, f"M3 failed: {result_m3.stderr}"
    m3_data = json.loads(result_m3.stdout)
    m3_root = m3_data.get("root")
    m3_cost = m3_data.get("cost", 0.0)
    m3_nodes = {n["name"]: n for n in m3_data["nodes"]}

    # Verify M3 sealed (fresh run)
    assert m3_root == m1_root, "M3 root should match M1 root"
    assert m3_nodes["oracle1"]["state"] == "sealed", "M3 oracle should seal (not cached)"
    # Costs should be comparable (both fresh runs)
    assert abs(m3_cost - m1_cost) < 0.001, f"M3 cost {m3_cost} should match M1 cost {m1_cost}"


def test_cache_reuse_zero_cost():
    """Verify cached runs have zero additional oracle cost."""
    with tempfile.TemporaryDirectory() as tmpdir:
        design = {
            "name": "test-cache",
            "fuel": 10,
            "target": "oracle1",
            "site_inputs": {},
            "rules": [
                {
                    "name": "oracle1",
                    "kind": "oracle",
                    "inputs": [],
                    "outputs": ["output.txt"],
                    "prompt": "Write 'test' to output.txt",
                    "tools": ["write-file"],
                    "fuel": 5,
                }
            ],
        }

        design_path = Path(tmpdir) / "design.json"
        design_path.write_text(json.dumps(design))
        site = Path(tmpdir) / "site"

        # First run
        result1 = run_husks_cli("run", str(design_path), "--stub", "--site", str(site), "--json")
        data1 = json.loads(result1.stdout)
        cost1 = data1.get("cost", 0.0)

        # Second run (cached)
        result2 = run_husks_cli("run", str(design_path), "--stub", "--site", str(site), "--json")
        data2 = json.loads(result2.stdout)
        cost2 = data2.get("cost", 0.0)

        # Second run should have zero cost (reused from cache)
        assert cost2 == 0.0, f"Cached run should have zero cost, got {cost2}"
        assert cost1 > 0.0, "First run should have non-zero cost"


def test_output_hash_consistency():
    """Verify output hashes are consistent across machines."""
    with tempfile.TemporaryDirectory() as tmpdir:
        design = {
            "name": "test-hash",
            "fuel": 10,
            "target": "oracle1",
            "site_inputs": {},
            "rules": [
                {
                    "name": "oracle1",
                    "kind": "oracle",
                    "inputs": [],
                    "outputs": ["output.txt"],
                    "prompt": "Write 'deterministic' to output.txt",
                    "tools": ["write-file"],
                    "fuel": 5,
                }
            ],
        }

        design_path = Path(tmpdir) / "design.json"
        design_path.write_text(json.dumps(design))

        # Run on site1
        site1 = Path(tmpdir) / "site1"
        result1 = run_husks_cli("run", str(design_path), "--stub", "--site", str(site1), "--json")
        data1 = json.loads(result1.stdout)
        hash1 = data1["nodes"][0].get("output_hash")

        # Run on site2
        site2 = Path(tmpdir) / "site2"
        result2 = run_husks_cli("run", str(design_path), "--stub", "--site", str(site2), "--json")
        data2 = json.loads(result2.stdout)
        hash2 = data2["nodes"][0].get("output_hash")

        # Output hashes should be identical (deterministic build)
        assert hash1 is not None, "Output hash should be captured"
        assert hash2 is not None, "Output hash should be captured"
        assert hash1 == hash2, f"Output hashes should match: {hash1} vs {hash2}"


def test_root_verification():
    """Verify build root is captured and consistent."""
    with tempfile.TemporaryDirectory() as tmpdir:
        design = {
            "name": "test-root",
            "fuel": 10,
            "target": "action1",
            "site_inputs": {},
            "rules": [
                {
                    "name": "action1",
                    "kind": "action",
                    "inputs": [],
                    "outputs": ["out.txt"],
                    "run": "echo hello > out.txt",
                }
            ],
        }

        design_path = Path(tmpdir) / "design.json"
        design_path.write_text(json.dumps(design))
        site = Path(tmpdir) / "site"

        # Run and verify root is captured
        result = run_husks_cli("run", str(design_path), "--site", str(site), "--json")
        data = json.loads(result.stdout)
        root = data.get("root")

        assert root is not None, "Build root should be captured"
        assert len(root) == 64, "Root should be 64-char hex string"
        assert data["status"] == "committed", "Build should commit successfully"

        # Rerun should produce same root
        result2 = run_husks_cli("run", str(design_path), "--site", str(site), "--json")
        data2 = json.loads(result2.stdout)
        root2 = data2.get("root")

        assert root2 == root, "Rerun should produce same root"
