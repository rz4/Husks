"""
test_three_machine_cli_acceptance.py -- Beta Gate G1: CLI-level three-machine proof.

End-to-end acceptance test simulating the three-machine beta workflow using
only CLI commands. This is the user-runnable proof that Husks beta is complete.

Machine 1: builds with oracle cost, exports cache
Machine 2: imports cache, reuses with zero cost
Machine 3: builds independently with comparable cost
"""

import json
import shutil
import tempfile
from pathlib import Path

import pytest

from conftest import run_husks_cli


@pytest.mark.beta
@pytest.mark.gate_g
def test_three_machine_cli_acceptance_stub():
    """CLI three-machine acceptance using stub oracle (G1/G3).

    This is the primary beta acceptance test. All three machines use
    CLI commands only (no direct Python API calls). Also validates
    that all reports conform to the beta report schema (Beta Gate G3).
    """
    from husks.report import validate_report_schema

    tmpdir = tempfile.mkdtemp(prefix="cli-three-machine-")
    try:
        # Beta 100: Use husks init instead of examples/beta_seed
        project_dir = Path(tmpdir) / "project"
        project_dir.mkdir()

        # Initialize project with core-bootstrap template
        init_result = run_husks_cli("init", str(project_dir), cwd=str(tmpdir))
        assert init_result.returncode == 0, (
            f"husks init should succeed\n"
            f"stdout: {init_result.stdout}\nstderr: {init_result.stderr}"
        )

        # Verify init created expected files (core-bootstrap template)
        design_path = project_dir / "core-bootstrap.json"
        assert design_path.exists(), f"core-bootstrap.json not found: {design_path}"

        # Beta 100: core-bootstrap uses embedded prompts, no separate prompt.txt file

        # ──────────────────────────────────────────────────────────
        # Machine 1: Original realization with empty cache
        # ──────────────────────────────────────────────────────────
        m1_dir = Path(tmpdir) / "machine1"
        m1_dir.mkdir()
        m1_site = m1_dir / "site"
        m1_site.mkdir()

        # Beta Gate A1/E3: No manual input copying - site_inputs resolve automatically
        # Run with stub oracle
        m1_result = run_husks_cli(
            "run", str(design_path),
            "--site", str(m1_site),
            "--stub",
            "--json",
            cwd=str(m1_dir),
        )

        assert m1_result.returncode == 0, (
            f"Machine 1 should succeed\n"
            f"stdout: {m1_result.stdout}\nstderr: {m1_result.stderr}"
        )

        m1_report = json.loads(m1_result.stdout)

        # Beta Gate G3: Validate report schema
        valid, errors = validate_report_schema(m1_report)
        assert valid, f"M1 report schema validation failed:\n" + "\n".join(f"  - {e}" for e in errors)

        assert m1_report["status"] == "committed", "M1 should commit"

        # M1 should have paid oracle cost (stub reports non-zero)
        m1_cost = m1_report["cost"]["paid"]
        assert m1_cost > 0, f"M1 should have oracle cost, got {m1_cost}"

        # M1 should have oracle calls in nodes
        m1_nodes = m1_report["nodes"]
        generate_node = [n for n in m1_nodes if n["name"] == "generate"][0]
        assert generate_node["cost"]["this_run"] > 0, "Generate node should have cost"

        # Validation should pass
        validation_path = m1_site / "validation.txt"
        assert validation_path.exists(), "Validation output should exist"
        assert validation_path.read_text().strip() == "PASS", "Validation should pass"

        # ──────────────────────────────────────────────────────────
        # Export cache from Machine 1
        # ──────────────────────────────────────────────────────────
        cache_file = Path(tmpdir) / "cache.tar.gz"

        export_result = run_husks_cli(
            "cache", "export", str(cache_file),
            "--site", str(m1_site),
            "--json",
        )

        assert export_result.returncode == 0, (
            f"Cache export should succeed\\n"
            f"stdout: {export_result.stdout}\\nstderr: {export_result.stderr}"
        )

        export_report = json.loads(export_result.stdout)
        assert export_report["status"] == "exported", "Export should report success"
        assert export_report["entries"] > 0, "Should export at least one cache entry"
        assert cache_file.exists(), "Cache export should create file"

        # ──────────────────────────────────────────────────────────
        # Machine 2: Cache reuse with zero oracle cost
        # ──────────────────────────────────────────────────────────
        m2_dir = Path(tmpdir) / "machine2"
        m2_dir.mkdir()
        m2_site = m2_dir / "site"
        m2_site.mkdir()

        # Beta Gate A1/E3: No manual input copying - site_inputs resolve automatically
        # Import cache
        import_result = run_husks_cli(
            "cache", "import", str(cache_file),
            "--site", str(m2_site),
            "--json",
        )

        assert import_result.returncode == 0, (
            f"Cache import should succeed\\n"
            f"stdout: {import_result.stdout}\\nstderr: {import_result.stderr}"
        )

        import_report = json.loads(import_result.stdout)
        assert import_report["status"] == "imported", "Import should report success"
        assert import_report["entries"] > 0, "Should import at least one cache entry"

        # Run with reuse-only (Beta Gate G2/D6)
        m2_result = run_husks_cli(
            "run", str(design_path),
            "--site", str(m2_site),
            "--reuse-only",
            "--json",
            cwd=str(m2_dir),
        )

        assert m2_result.returncode == 0, (
            f"Machine 2 should succeed\n"
            f"stdout: {m2_result.stdout}\nstderr: {m2_result.stderr}"
        )

        m2_report = json.loads(m2_result.stdout)

        # Beta Gate G3: Validate report schema
        valid, errors = validate_report_schema(m2_report)
        assert valid, f"M2 report schema validation failed:\n" + "\n".join(f"  - {e}" for e in errors)

        assert m2_report["status"] == "committed", "M2 should commit"

        # M2 should have ZERO oracle cost (cache hit)
        m2_cost = m2_report["cost"]["paid"]
        assert m2_cost == 0.0, f"M2 should have zero cost (cache hit), got {m2_cost}"

        # M2 validation should also pass
        assert (m2_site / "validation.txt").read_text().strip() == "PASS"

        # ──────────────────────────────────────────────────────────
        # Machine 3: Independent re-realization with empty cache
        # ──────────────────────────────────────────────────────────
        m3_dir = Path(tmpdir) / "machine3"
        m3_dir.mkdir()
        m3_site = m3_dir / "site"
        m3_site.mkdir()

        # Beta Gate A1/E3: No manual input copying - site_inputs resolve automatically
        # Run with stub oracle (empty cache, independent)
        m3_result = run_husks_cli(
            "run", str(design_path),
            "--site", str(m3_site),
            "--stub",
            "--json",
            cwd=str(m3_dir),
        )

        assert m3_result.returncode == 0, (
            f"Machine 3 should succeed\n"
            f"stdout: {m3_result.stdout}\nstderr: {m3_result.stderr}"
        )

        m3_report = json.loads(m3_result.stdout)

        # Beta Gate G3: Validate report schema
        valid, errors = validate_report_schema(m3_report)
        assert valid, f"M3 report schema validation failed:\n" + "\n".join(f"  - {e}" for e in errors)

        assert m3_report["status"] == "committed", "M3 should commit"

        # M3 should have paid oracle cost (comparable to M1)
        m3_cost = m3_report["cost"]["paid"]
        assert m3_cost > 0, f"M3 should have oracle cost, got {m3_cost}"

        # Cost should be comparable (stub oracle is deterministic)
        assert m1_cost == m3_cost, (
            f"M1 and M3 costs should be equal (stub oracle), "
            f"M1: {m1_cost}, M3: {m3_cost}"
        )

        # M3 validation should pass
        assert (m3_site / "validation.txt").read_text().strip() == "PASS"

        # ──────────────────────────────────────────────────────────
        # Beta Gate G4: Save JSON reports to files for compare-runs
        # ──────────────────────────────────────────────────────────
        m1_json_file = Path(tmpdir) / "m1.json"
        m2_json_file = Path(tmpdir) / "m2.json"
        m3_json_file = Path(tmpdir) / "m3.json"

        m1_json_file.write_text(m1_result.stdout)
        m2_json_file.write_text(m2_result.stdout)
        m3_json_file.write_text(m3_result.stdout)

        # ──────────────────────────────────────────────────────────
        # Beta Gate C/F/G: Compare runs via compare-runs command
        # ──────────────────────────────────────────────────────────
        compare_runs_result = run_husks_cli(
            "compare-runs",
            str(m1_json_file), str(m2_json_file), str(m3_json_file),
            "--json",
        )

        assert compare_runs_result.returncode == 0, (
            f"compare-runs should validate three-machine proof\n"
            f"stdout: {compare_runs_result.stdout}\n"
            f"stderr: {compare_runs_result.stderr}"
        )

        # Validate the three-machine proof via compare-runs
        proof = json.loads(compare_runs_result.stdout)
        assert proof["equivalent"] is True, (
            f"Three-machine proof should be equivalent\n"
            f"Violations: {proof.get('violations', [])}"
        )

        # Verify all checks passed
        checks = proof["checks"]
        assert checks["m1_paid_cost"] is True, "M1 should have paid cost"
        assert checks["m2_zero_oracle_calls"] is True, "M2 should have zero oracle calls"
        assert checks["m2_zero_cost"] is True, "M2 should have zero cost"
        assert checks["m3_paid_cost"] is True, "M3 should have paid cost"

        # ──────────────────────────────────────────────────────────
        # Legacy site-level compare (keep for compatibility)
        # ──────────────────────────────────────────────────────────
        compare_result = run_husks_cli(
            "compare",
            str(m1_site), str(m2_site), str(m3_site),
            "--json",
        )

        assert compare_result.returncode == 0, (
            f"Compare should pass for equivalent sites\n"
            f"stdout: {compare_result.stdout}\nstderr: {compare_result.stderr}"
        )

        compare = json.loads(compare_result.stdout)
        # Note: M1, M2, M3 have same design but may have different roots
        # (cache metadata differs). They should have equivalent outputs.
        # For now, just verify the command works.

        print("\n✓ Three-machine CLI acceptance: PASS")
        print(f"  M1 cost: ${m1_cost:.4f} (oracle)")
        print(f"  M2 cost: ${m2_cost:.4f} (cache hit)")
        print(f"  M3 cost: ${m3_cost:.4f} (oracle)")
        print(f"  compare-runs: {proof['checks']}")

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_cli_json_contracts():
    """Verify JSON contracts for acceptance commands (G2/G3).

    Tests that run --json, compare --json produce valid, parseable JSON
    with no console noise and conform to the beta report schema.
    """
    from husks.report import validate_report_schema

    tmpdir = tempfile.mkdtemp(prefix="json-contracts-")
    try:
        # Create minimal design
        design_file = Path(tmpdir) / "design.json"
        design_file.write_text(json.dumps({
            "name": "test",
            "fuel": 10,
            "target": "out",
            "rules": [{
                "name": "out",
                "kind": "action",
                "outputs": ["out.txt"],
                "run": "echo hello > out.txt"
            }]
        }))

        site = Path(tmpdir) / "site"
        site.mkdir()

        # Test run --json contract (Beta Gate G3)
        result = run_husks_cli("run", str(design_file), "--site", str(site), "--json")
        assert result.returncode == 0

        # Should be valid JSON conforming to beta report schema
        report = json.loads(result.stdout)
        valid, errors = validate_report_schema(report)
        assert valid, f"Report schema validation failed:\n" + "\n".join(f"  - {e}" for e in errors)

        # Verify core fields
        assert report["status"] == "committed"
        assert report["cost"]["paid"] == 0.0  # action rule, no oracle cost
        assert len(report["nodes"]) == 1
        assert report["nodes"][0]["name"] == "out"
        assert report["nodes"][0]["kind"] == "action"

        # Test compare --json contract
        site2 = Path(tmpdir) / "site2"
        site2.mkdir()
        run_husks_cli("run", str(design_file), "--site", str(site2), "--json")

        cmp_result = run_husks_cli("compare", str(site), str(site2), "--json")
        assert cmp_result.returncode == 0

        # Compare contract: equivalent + comparisons
        comparison = json.loads(cmp_result.stdout)
        assert "equivalent" in comparison
        assert "comparisons" in comparison
        assert isinstance(comparison["equivalent"], bool)
        assert isinstance(comparison["comparisons"], list)

        # For this case, sites should be equivalent
        assert comparison["equivalent"] is True

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)
