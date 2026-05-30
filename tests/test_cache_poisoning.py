"""
test_cache_poisoning.py -- Beta Gate D1: Cache poisoning prevention.

Regression tests proving that poisoned cache entries cannot materialize
as successful zero-cost builds.
"""

import json
import tempfile
import shutil
from pathlib import Path

from conftest import run_husks_cli

import pytest


@pytest.mark.beta


@pytest.mark.gate_d


def test_cache_poisoning_outputs_json():
    """Beta Gate D1: Poisoned outputs.json is rejected during reuse-only."""
    tmpdir = tempfile.mkdtemp(prefix="cache-poison-")
    try:
        beta_seed_dir = Path(__file__).parent.parent / "examples" / "beta_seed"
        design_path = beta_seed_dir / "design.json"

        # Machine 1: Build with cache
        m1_site = Path(tmpdir) / "m1_site"
        m1_site.mkdir()

        m1_result = run_husks_cli(
            "run", str(design_path),
            "--site", str(m1_site),
            "--stub",
            "--json",
        )

        assert m1_result.returncode == 0, "M1 should succeed"
        m1_report = json.loads(m1_result.stdout)
        assert m1_report["status"] == "committed", "M1 should commit"

        # Poison the cache by modifying outputs.json
        cache_dirs = list((m1_site / ".cache").iterdir())
        assert len(cache_dirs) > 0, "Cache should have entries"

        cache_entry = cache_dirs[0]
        outputs_json = cache_entry / "outputs.json"
        assert outputs_json.exists(), "outputs.json should exist"

        # Modify the cached output content
        outputs = json.loads(outputs_json.read_text())
        # Change content of first output
        first_output_name = list(outputs.keys())[0]
        outputs[first_output_name] = "POISONED CONTENT"
        outputs_json.write_text(json.dumps(outputs, indent=2))

        # Export poisoned cache
        cache_file = Path(tmpdir) / "poisoned-cache.tar.gz"
        export_result = run_husks_cli(
            "cache", "export", str(cache_file),
            "--site", str(m1_site),
            "--json",
        )
        assert export_result.returncode == 0, "Export should succeed"

        # Machine 2: Import poisoned cache and try reuse-only
        m2_site = Path(tmpdir) / "m2_site"
        m2_site.mkdir()

        import_result = run_husks_cli(
            "cache", "import", str(cache_file),
            "--site", str(m2_site),
            "--json",
        )
        assert import_result.returncode == 0, "Import should succeed"

        # Try to run with reuse-only - should fail because cache validation fails
        m2_result = run_husks_cli(
            "run", str(design_path),
            "--site", str(m2_site),
            "--reuse-only",
            "--json",
        )

        # Should fail (poisoned cache rejected)
        assert m2_result.returncode != 0, (
            f"Poisoned cache should be rejected in reuse-only mode\n"
            f"stdout: {m2_result.stdout}\nstderr: {m2_result.stderr}"
        )

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


@pytest.mark.beta


@pytest.mark.gate_d


def test_cache_poisoning_seal_tampered():
    """Beta Gate D1: Tampered seal.json is rejected."""
    tmpdir = tempfile.mkdtemp(prefix="cache-seal-poison-")
    try:
        beta_seed_dir = Path(__file__).parent.parent / "examples" / "beta_seed"
        design_path = beta_seed_dir / "design.json"

        # Machine 1: Build with cache
        m1_site = Path(tmpdir) / "m1_site"
        m1_site.mkdir()

        m1_result = run_husks_cli(
            "run", str(design_path),
            "--site", str(m1_site),
            "--stub",
            "--json",
        )

        assert m1_result.returncode == 0, "M1 should succeed"

        # Tamper with seal.json by changing recipe_digest
        cache_dirs = list((m1_site / ".cache").iterdir())
        cache_entry = cache_dirs[0]
        seal_json = cache_entry / "seal.json"
        assert seal_json.exists(), "seal.json should exist"

        seal = json.loads(seal_json.read_text())
        seal["recipe_digest"] = "tampered_digest_" + seal["recipe_digest"]
        seal_json.write_text(json.dumps(seal, indent=2))

        # Export tampered cache
        cache_file = Path(tmpdir) / "tampered-cache.tar.gz"
        export_result = run_husks_cli(
            "cache", "export", str(cache_file),
            "--site", str(m1_site),
            "--json",
        )
        assert export_result.returncode == 0, "Export should succeed"

        # Machine 2: Import and try reuse-only
        m2_site = Path(tmpdir) / "m2_site"
        m2_site.mkdir()

        import_result = run_husks_cli(
            "cache", "import", str(cache_file),
            "--site", str(m2_site),
            "--json",
        )
        assert import_result.returncode == 0, "Import should succeed"

        m2_result = run_husks_cli(
            "run", str(design_path),
            "--site", str(m2_site),
            "--reuse-only",
            "--json",
        )

        # Should fail (tampered seal rejected)
        assert m2_result.returncode != 0, (
            "Tampered seal should cause reuse-only to fail"
        )

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


@pytest.mark.beta


@pytest.mark.gate_d


def test_cache_validation_allows_valid_reuse():
    """Beta Gate D1: Valid cache entries still work after validation."""
    tmpdir = tempfile.mkdtemp(prefix="cache-valid-")
    try:
        beta_seed_dir = Path(__file__).parent.parent / "examples" / "beta_seed"
        design_path = beta_seed_dir / "design.json"

        # Machine 1: Build
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
        m1_cost = m1_report["cost"]["paid"]
        assert m1_cost > 0, "M1 should have oracle cost"

        # Export valid cache
        cache_file = Path(tmpdir) / "valid-cache.tar.gz"
        run_husks_cli(
            "cache", "export", str(cache_file),
            "--site", str(m1_site),
            "--json",
        )

        # Machine 2: Import and reuse
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

        # Should succeed with valid cache
        assert m2_result.returncode == 0, (
            f"Valid cache should work with reuse-only\n"
            f"stdout: {m2_result.stdout}\nstderr: {m2_result.stderr}"
        )

        m2_report = json.loads(m2_result.stdout)
        assert m2_report["status"] == "committed", "M2 should commit"
        m2_cost = m2_report["cost"]["paid"]
        assert m2_cost == 0.0, "M2 should have zero cost (cache hit)"

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)
