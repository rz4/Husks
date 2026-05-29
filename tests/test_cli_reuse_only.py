"""
test_cli_reuse_only.py -- Beta Gate D5: CLI --reuse-only flag.

Tests that husks run --reuse-only uses cache and rejects oracle execution.
"""

import json
import tempfile
import shutil
from pathlib import Path

from conftest import run_husks_cli


def test_cli_reuse_only_with_cache():
    """husks run --reuse-only uses cache and skips oracle."""
    tmpdir = tempfile.mkdtemp(prefix="cli-reuse-")
    try:
        # Create minimal oracle design
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

        # First run: populate cache
        r1 = run_husks_cli("run", str(design_file), "--site", str(site), "--stub", "--json")
        assert r1.returncode == 0
        rep1 = json.loads(r1.stdout)
        assert rep1["status"] == "committed"
        assert rep1["cost"]["paid"] > 0  # First run pays

        # Second run with --reuse-only: should use cache
        r2 = run_husks_cli(
            "run", str(design_file),
            "--site", str(site),
            "--stub",
            "--reuse-only",
            "--json"
        )
        assert r2.returncode == 0
        rep2 = json.loads(r2.stdout)
        assert rep2["status"] == "committed"
        assert rep2["cost"]["paid"] == 0.0  # Reuse-only pays nothing

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_cli_reuse_only_without_cache_fails():
    """husks run --reuse-only fails when cache is empty."""
    tmpdir = tempfile.mkdtemp(prefix="cli-reuse-miss-")
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
                "prompt": "Say hello",
            }]
        }))

        site = Path(tmpdir) / "site"
        site.mkdir()

        # Run with --reuse-only but no cache: should fail
        result = run_husks_cli(
            "run", str(design_file),
            "--site", str(site),
            "--stub",
            "--reuse-only",
            "--json"
        )

        # Should halt due to cache miss in reuse-only mode
        assert result.returncode != 0, f"Should fail, got: {result.stdout}"
        rep = json.loads(result.stdout)
        assert rep["status"] == "halted", f"Should halt, got status: {rep.get('status')}"
        # Check that the error message mentions reuse-only
        assert "cache-reuse-only" in str(rep.get("value", "")) or \
               "cache-reuse-only" in str(rep.get("nodes", []))

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)
