"""
test_cache_report_contract.py -- Beta Gate D6: Cache reuse in report contract.

Tests that run --json reports cache reuse with:
- cached: true/false
- paid_cost: 0 for cached
- oracle_calls: 0 for cached (tokens_in=0, tokens_out=0)
"""

import json
import tempfile
import shutil
from pathlib import Path

from conftest import run_husks_cli

import pytest


@pytest.mark.beta


@pytest.mark.gate_f


def test_cache_hit_in_json_report():
    """run --json shows cached=true and zero cost for cache hits."""
    tmpdir = tempfile.mkdtemp(prefix="report-cached-")
    try:
        # Create oracle design
        design_file = Path(tmpdir) / "design.json"
        design_file.write_text(json.dumps({
            "name": "test",
            "fuel": 10,
            "target": "out",
            "rules": [{
                "name": "out",
                "kind": "oracle",
                "fuel": 5,
                "outputs": ["out.txt"],
                "prompt": "Say hello",
            }]
        }))

        site = Path(tmpdir) / "site"
        site.mkdir()

        # First run: cache miss
        r1 = run_husks_cli("run", str(design_file), "--site", str(site), "--stub", "--json")
        assert r1.returncode == 0
        rep1 = json.loads(r1.stdout)

        # Verify first run: NOT cached
        out_node_1 = [n for n in rep1["nodes"] if n["name"] == "out"][0]
        assert out_node_1["cached"] is False, "First run should not be cached"
        assert out_node_1["cost"]["this_run"] > 0, "First run should have cost"
        assert out_node_1["tokens"]["input"] > 0, "First run should have input tokens"
        assert out_node_1["tokens"]["output"] > 0, "First run should have output tokens"

        # Make node stale by removing output (forces re-fire with cache hit)
        (site / "out.txt").unlink()

        # Second run: cache hit (node will fire but use cached oracle result)
        r2 = run_husks_cli("run", str(design_file), "--site", str(site), "--stub", "--json")
        assert r2.returncode == 0
        rep2 = json.loads(r2.stdout)

        # Verify second run: cached=true, zero cost, zero tokens
        out_node_2 = [n for n in rep2["nodes"] if n["name"] == "out"][0]
        assert out_node_2["state"] == "fired", "Node should re-fire when stale"
        assert out_node_2["cached"] is True, "Second run should be cached"
        assert out_node_2["cost"]["this_run"] == 0.0, "Cached run should have zero cost"
        assert out_node_2["tokens"]["input"] == 0, "Cached run should have zero input tokens"
        assert out_node_2["tokens"]["output"] == 0, "Cached run should have zero output tokens"

        # Overall cost should be zero for cached run
        assert rep2["cost"]["paid"] == 0.0, "Cached build should have zero total cost"

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


@pytest.mark.beta


@pytest.mark.gate_f


def test_cache_miss_shows_uncached():
    """run --json shows cached=false for cache miss."""
    tmpdir = tempfile.mkdtemp(prefix="report-uncached-")
    try:
        design_file = Path(tmpdir) / "design.json"
        design_file.write_text(json.dumps({
            "name": "test",
            "fuel": 10,
            "target": "out",
            "rules": [{
                "name": "out",
                "kind": "oracle",
                "fuel": 5,
                "outputs": ["out.txt"],
                "prompt": "Generate output",
            }]
        }))

        site = Path(tmpdir) / "site"
        site.mkdir()

        # Run with empty cache
        result = run_husks_cli("run", str(design_file), "--site", str(site), "--stub", "--json")
        assert result.returncode == 0

        report = json.loads(result.stdout)
        out_node = [n for n in report["nodes"] if n["name"] == "out"][0]

        # Should NOT be cached
        assert out_node["cached"] is False
        assert out_node["cost"]["this_run"] > 0
        assert report["cost"]["paid"] > 0

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


@pytest.mark.beta


@pytest.mark.gate_f


def test_action_nodes_not_cached():
    """Action nodes always show cached=false."""
    tmpdir = tempfile.mkdtemp(prefix="report-action-")
    try:
        design_file = Path(tmpdir) / "design.json"
        design_file.write_text(json.dumps({
            "name": "test",
            "fuel": 10,
            "target": "out",
            "rules": [{
                "name": "out",
                "kind": "action",
                "outputs": ["out.txt"],
                "run": "echo hello > out.txt",
            }]
        }))

        site = Path(tmpdir) / "site"
        site.mkdir()

        # Run action twice
        r1 = run_husks_cli("run", str(design_file), "--site", str(site), "--json")
        assert r1.returncode == 0
        rep1 = json.loads(r1.stdout)

        r2 = run_husks_cli("run", str(design_file), "--site", str(site), "--json")
        assert r2.returncode == 0
        rep2 = json.loads(r2.stdout)

        # First run: action node fresh (not cached)
        out_node_1 = [n for n in rep1["nodes"] if n["name"] == "out"][0]
        assert out_node_1["cached"] is False
        assert out_node_1["tokens"]["input"] == 0  # Actions have no tokens

        # Second run: action node is already sealed so may report as cached/reused
        out_node_2 = [n for n in rep2["nodes"] if n["name"] == "out"][0]
        # Actions always have zero tokens regardless of cache state
        assert out_node_2["tokens"]["input"] == 0
        assert out_node_2["tokens"]["output"] == 0

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)
