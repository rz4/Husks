"""
test_live_oracle_readiness.py -- Task 6/Gate E: Live oracle proof readiness.

Tests that the live oracle path is structurally sound using the same beta_seed
and report schema as the stub proof. These tests are SKIPPED unless live oracle
credentials are available.

Required environment variables:
- ANTHROPIC_API_KEY: Anthropic API key for Claude models

Set HUSKS_ENABLE_LIVE_TESTS=1 to run these tests even with API key present
(default: skip to avoid API costs in CI).
"""

import json
import os
import tempfile
import shutil
from pathlib import Path

import pytest

from conftest import run_husks_cli


# Check for required environment variables
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
ENABLE_LIVE_TESTS = os.getenv("HUSKS_ENABLE_LIVE_TESTS") == "1"

# Skip all tests in this module unless explicitly enabled
pytestmark = pytest.mark.skipif(
    not (ANTHROPIC_API_KEY and ENABLE_LIVE_TESTS),
    reason=(
        "Live oracle tests skipped (requires ANTHROPIC_API_KEY "
        "and HUSKS_ENABLE_LIVE_TESTS=1 to avoid API costs)"
    )
)


def test_live_oracle_single_run():
    """Live oracle runs beta_seed and produces valid report (Task 6).

    This test validates that:
    - Live oracle can execute the beta_seed design
    - Report conforms to beta schema
    - Validator passes with live oracle output
    - Cost is non-zero (oracle was called)
    """
    from husks.report import validate_report_schema

    tmpdir = tempfile.mkdtemp(prefix="live-single-")
    try:
        beta_seed_dir = Path(__file__).parent.parent / "examples" / "beta_seed"
        design_path = beta_seed_dir / "design.json"

        site = Path(tmpdir) / "site"
        site.mkdir()

        # Run with live oracle (no --stub flag)
        result = run_husks_cli(
            "run", str(design_path),
            "--site", str(site),
            "--model", "anthropic/claude-haiku-4-5-20251001",
            "--json",
        )

        # Should succeed
        assert result.returncode == 0, (
            f"Live oracle run should succeed\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )

        # Parse report
        report = json.loads(result.stdout)

        # Validate report schema
        valid, errors = validate_report_schema(report)
        assert valid, f"Live report schema validation failed:\n" + "\n".join(f"  - {e}" for e in errors)

        # Check report fields
        assert report["status"] == "committed", f"Expected committed, got {report['status']}"
        assert report["cost"]["paid"] > 0, "Live oracle should have non-zero cost"

        # Check oracle node
        generate_node = [n for n in report["nodes"] if n["name"] == "generate"][0]
        assert generate_node["kind"] == "oracle"
        assert generate_node["state"] == "fired"
        assert generate_node["cost"]["this_run"] > 0, "Live oracle should have cost"
        assert generate_node["cached"] is False, "First run should not be cached"

        # Check validation passed
        validation_path = site / "validation.txt"
        assert validation_path.exists(), "Validation output should exist"
        validation_result = validation_path.read_text().strip()
        assert validation_result == "PASS", f"Validation should pass, got: {validation_result}"

        # Check response has correct format
        response_path = site / "response.txt"
        assert response_path.exists(), "Response should exist"
        response_text = response_path.read_text().strip()
        assert response_text.startswith("ANSWER:"), f"Response should have ANSWER: format, got: {response_text}"

        print(f"\n✓ Live oracle single run: PASS")
        print(f"  Cost: ${report['cost']['paid']:.6f}")
        print(f"  Response: {response_text[:50]}")

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_live_oracle_cache_reuse():
    """Live oracle cache reuse works correctly (Task 6).

    This test validates that:
    - First run pays oracle cost
    - Second run reuses cache with zero cost
    - Both runs produce same validation result
    """
    from husks.report import validate_report_schema

    tmpdir = tempfile.mkdtemp(prefix="live-cache-")
    try:
        beta_seed_dir = Path(__file__).parent.parent / "examples" / "beta_seed"
        design_path = beta_seed_dir / "design.json"

        site = Path(tmpdir) / "site"
        site.mkdir()

        # First run - should pay cost
        result1 = run_husks_cli(
            "run", str(design_path),
            "--site", str(site),
            "--model", "anthropic/claude-haiku-4-5-20251001",
            "--json",
        )

        assert result1.returncode == 0, "First run should succeed"
        report1 = json.loads(result1.stdout)

        valid, _ = validate_report_schema(report1)
        assert valid, "First run report should be valid"
        assert report1["status"] == "committed"
        assert report1["cost"]["paid"] > 0, "First run should pay cost"

        cost1 = report1["cost"]["paid"]

        # Second run - should reuse cache
        result2 = run_husks_cli(
            "run", str(design_path),
            "--site", str(site),
            "--model", "anthropic/claude-haiku-4-5-20251001",
            "--json",
        )

        assert result2.returncode == 0, "Second run should succeed"
        report2 = json.loads(result2.stdout)

        valid, _ = validate_report_schema(report2)
        assert valid, "Second run report should be valid"
        assert report2["status"] == "committed"
        assert report2["cost"]["paid"] == 0.0, "Second run should reuse cache (zero cost)"

        # Check oracle node was cached
        generate_node = [n for n in report2["nodes"] if n["name"] == "generate"][0]
        assert generate_node["cached"] is True, "Second run should have cached oracle"

        # Both validations should pass
        validation_path = site / "validation.txt"
        assert validation_path.read_text().strip() == "PASS"

        print(f"\n✓ Live oracle cache reuse: PASS")
        print(f"  Run 1 cost: ${cost1:.6f}")
        print(f"  Run 2 cost: $0.000000 (cached)")

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_live_oracle_three_machine_proof():
    """Live oracle three-machine proof (Task 6).

    This test validates the full three-machine proof with live oracle:
    - M1: Builds with live oracle, pays cost
    - M2: Imports cache, reuses with zero cost
    - M3: Rebuilds independently, pays comparable cost
    - All three validate correctly
    - compare-runs validates the proof
    """
    from husks.report import validate_report_schema

    tmpdir = tempfile.mkdtemp(prefix="live-three-machine-")
    try:
        beta_seed_dir = Path(__file__).parent.parent / "examples" / "beta_seed"
        design_path = beta_seed_dir / "design.json"

        # Machine 1: Original build with live oracle
        m1_site = Path(tmpdir) / "m1"
        m1_site.mkdir()

        m1_result = run_husks_cli(
            "run", str(design_path),
            "--site", str(m1_site),
            "--model", "anthropic/claude-haiku-4-5-20251001",
            "--json",
        )

        assert m1_result.returncode == 0, "M1 should succeed"
        m1_report = json.loads(m1_result.stdout)

        valid, _ = validate_report_schema(m1_report)
        assert valid, "M1 report should be valid"
        assert m1_report["status"] == "committed"
        assert m1_report["cost"]["paid"] > 0, "M1 should pay oracle cost"

        m1_cost = m1_report["cost"]["paid"]

        # Export cache
        cache_file = Path(tmpdir) / "cache.tar.gz"
        export_result = run_husks_cli(
            "cache", "export", str(cache_file),
            "--site", str(m1_site),
            "--json",
        )
        assert export_result.returncode == 0, "Cache export should succeed"
        assert cache_file.exists(), "Cache file should exist"

        # Machine 2: Import cache and reuse
        m2_site = Path(tmpdir) / "m2"
        m2_site.mkdir()

        import_result = run_husks_cli(
            "cache", "import", str(cache_file),
            "--site", str(m2_site),
            "--json",
        )
        assert import_result.returncode == 0, "Cache import should succeed"

        m2_result = run_husks_cli(
            "run", str(design_path),
            "--site", str(m2_site),
            "--reuse-only",
            "--json",
        )

        assert m2_result.returncode == 0, "M2 should succeed"
        m2_report = json.loads(m2_result.stdout)

        valid, _ = validate_report_schema(m2_report)
        assert valid, "M2 report should be valid"
        assert m2_report["status"] == "committed"
        assert m2_report["cost"]["paid"] == 0.0, "M2 should have zero cost (cache hit)"

        # Machine 3: Independent rebuild
        m3_site = Path(tmpdir) / "m3"
        m3_site.mkdir()

        m3_result = run_husks_cli(
            "run", str(design_path),
            "--site", str(m3_site),
            "--model", "anthropic/claude-haiku-4-5-20251001",
            "--json",
        )

        assert m3_result.returncode == 0, "M3 should succeed"
        m3_report = json.loads(m3_result.stdout)

        valid, _ = validate_report_schema(m3_report)
        assert valid, "M3 report should be valid"
        assert m3_report["status"] == "committed"
        assert m3_report["cost"]["paid"] > 0, "M3 should pay oracle cost"

        m3_cost = m3_report["cost"]["paid"]

        # Save reports for compare-runs
        m1_json = Path(tmpdir) / "m1.json"
        m2_json = Path(tmpdir) / "m2.json"
        m3_json = Path(tmpdir) / "m3.json"

        m1_json.write_text(m1_result.stdout)
        m2_json.write_text(m2_result.stdout)
        m3_json.write_text(m3_result.stdout)

        # Validate three-machine proof
        compare_result = run_husks_cli(
            "compare-runs",
            str(m1_json), str(m2_json), str(m3_json),
            "--json",
        )

        assert compare_result.returncode == 0, "compare-runs should validate proof"

        proof = json.loads(compare_result.stdout)
        assert proof["equivalent"] is True, f"Proof should be equivalent\nViolations: {proof.get('violations', [])}"

        # Verify all checks passed
        checks = proof["checks"]
        assert checks["m1_paid_cost"] is True
        assert checks["m2_zero_oracle_calls"] is True
        assert checks["m2_zero_cost"] is True
        assert checks["m2_has_cache_hits"] is True
        assert checks["m2_cached_node_evidence"] is True
        assert checks["m3_paid_cost"] is True

        print(f"\n✓ Live oracle three-machine proof: PASS")
        print(f"  M1 cost: ${m1_cost:.6f}")
        print(f"  M2 cost: $0.000000 (cached)")
        print(f"  M3 cost: ${m3_cost:.6f}")
        print(f"  Proof checks: {proof['checks']}")

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)
