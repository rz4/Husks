"""
Beta 100 Public CLI Acceptance Test

This test defines the public beta contract: a fresh user can run the
three-machine proof from `husks init` with no manual setup.

The beta is sealed when this test passes.
"""

import json
import pytest
from conftest import run_husks_cli


@pytest.mark.beta
def test_beta100_public_three_machine_from_init(tmp_path):
    """
    Beta 100 acceptance: full three-machine proof from husks init.

    Flow:
    1. husks init creates core-bootstrap.json
    2. husks check validates dry conformance
    3. M1 realizes the design, pays oracle cost
    4. M1 exports cache
    5. M2 imports cache, reuses at zero oracle cost
    6. M3 independently re-realizes with comparable expense
    7. compare proves equivalence (three-machine proof with 3 sites)

    This test should fail until beta 100 is fully implemented.
    """
    project = tmp_path / "beta-demo"

    # Step 1: Initialize the beta seed
    init_result = run_husks_cli("init", str(project))
    assert init_result.returncode == 0, f"init failed: {init_result.stderr}"

    design = project / "core-bootstrap.json"
    assert design.exists(), "core-bootstrap.json not created by init"

    # Step 2: Check dry conformance
    check_v = run_husks_cli("check", str(design), "--verbose", cwd=project)
    assert check_v.returncode == 0, f"check --verbose failed: {check_v.stderr}"
    assert "core-bootstrap" in check_v.stdout
    assert "checked" in check_v.stdout or "design" in check_v.stdout
    assert "□ validate" in check_v.stdout or "validate" in check_v.stdout
    assert "□ generate" in check_v.stdout or "generate" in check_v.stdout

    # Check JSON also works
    check_j = run_husks_cli("check", str(design), "--json", cwd=project)
    assert check_j.returncode == 0, f"check --json failed: {check_j.stderr}"
    check_data = json.loads(check_j.stdout)
    assert check_data["command"] == "check"
    assert check_data["status"] in ["checked", "valid"]

    # Step 3: M1 realizes the design (with sidecar JSON report)
    m1 = project / "m1"
    m1_json = project / "m1.json"
    r1 = run_husks_cli(
        "run", str(design), "--site", str(m1), "--stub", "--verbose",
        "--report-json", str(m1_json),
        cwd=project
    )
    assert r1.returncode == 0, f"M1 run failed: {r1.stderr}"
    assert "core-bootstrap" in r1.stdout
    assert "■ validate" in r1.stdout or "validate" in r1.stdout
    assert "■ generate" in r1.stdout or "◆ generate" in r1.stdout or "generate" in r1.stdout

    # Verify M1 husk artifact and JSON report were created
    husk_artifact = m1 / "core-bootstrap.husk"
    assert husk_artifact.exists(), "M1 did not produce core-bootstrap.husk"
    assert m1_json.exists(), "M1 did not produce JSON report"

    # Step 4: Export M1 cache
    cache = project / "cache.tar.gz"
    export_result = run_husks_cli(
        "cache", "export", str(cache), "--site", str(m1),
        cwd=project
    )
    assert export_result.returncode == 0, f"cache export failed: {export_result.stderr}"
    assert cache.exists(), "cache.tar.gz not created"

    # Step 5: Import cache to M2
    m2 = project / "m2"
    import_result = run_husks_cli(
        "cache", "import", str(cache), "--site", str(m2),
        cwd=project
    )
    assert import_result.returncode == 0, f"cache import failed: {import_result.stderr}"

    # Step 6: M2 reuses cache at zero oracle cost (with sidecar JSON report)
    m2_json = project / "m2.json"
    r2 = run_husks_cli(
        "run", str(design), "--site", str(m2), "--reuse-only", "--stub", "--verbose",
        "--report-json", str(m2_json),
        cwd=project
    )
    assert r2.returncode == 0, f"M2 run failed: {r2.stderr}"
    assert "◆ generate" in r2.stdout or "cached" in r2.stdout.lower()
    assert "$0.0000" in r2.stdout or "$0.00" in r2.stdout
    assert m2_json.exists(), "M2 did not produce JSON report"

    # Step 7: M3 independently re-realizes (with sidecar JSON report)
    m3 = project / "m3"
    m3_json = project / "m3.json"
    r3 = run_husks_cli(
        "run", str(design), "--site", str(m3), "--stub", "--verbose",
        "--report-json", str(m3_json),
        cwd=project
    )
    assert r3.returncode == 0, f"M3 run failed: {r3.stderr}"
    assert "■ generate" in r3.stdout or "generate" in r3.stdout
    assert m3_json.exists(), "M3 did not produce JSON report"

    # Step 8: Validate JSON report structure
    for name, json_path in [("m1", m1_json), ("m2", m2_json), ("m3", m3_json)]:
        data = json.loads(json_path.read_text())
        assert "status" in data, f"{name} JSON missing status"
        assert "nodes" in data or "rules" in data, f"{name} JSON missing nodes/rules"

    # Step 9: Status shows realization state for each site
    for site_name, site_path in [("m1", m1), ("m2", m2), ("m3", m3)]:
        status_result = run_husks_cli(
            "status", str(site_path), "--verbose",
            cwd=project
        )
        assert status_result.returncode == 0, f"status --verbose failed for {site_name}: {status_result.stderr}"
        assert "core-bootstrap" in status_result.stdout

    # Step 10: Compare sites to prove three-machine equivalence
    # (compare now reads .traces/report.json from each site automatically)
    cmp = run_husks_cli(
        "compare",
        str(m1),
        str(m2),
        str(m3),
        "--json",
        cwd=project
    )
    assert cmp.returncode == 0, f"compare failed: {cmp.stderr}"

    cmp_data = json.loads(cmp.stdout)
    assert cmp_data["equivalent"] is True, "Three-machine sites not equivalent"

    # Verify M2 reuse proof
    m2_data = json.loads(m2_json.read_text())
    # M2 should have zero oracle calls or zero cost
    if "oracle_calls" in m2_data:
        assert m2_data["oracle_calls"] == 0, "M2 made oracle calls despite reuse-only"
    if "cost" in m2_data:
        cost = m2_data["cost"]
        if isinstance(cost, dict):
            assert cost.get("paid", 0) == 0.0, "M2 paid oracle cost"
        else:
            assert cost == 0.0, "M2 paid oracle cost"


@pytest.mark.beta
def test_beta100_status_command(tmp_path):
    """
    Beta 100: status command shows current site realization state.

    Status is local and minimal - shows what's in the site, not theory.
    """
    project = tmp_path / "beta-demo"

    # Init and run to create a realized site
    run_husks_cli("init", str(project))
    design = project / "core-bootstrap.json"
    site = project / "site1"

    run_result = run_husks_cli(
        "run", str(design), "--site", str(site), "--stub",
        cwd=project
    )
    assert run_result.returncode == 0

    # Status should work without --verbose (summary output)
    status_quiet = run_husks_cli("status", str(site), cwd=project)
    assert status_quiet.returncode == 0
    assert "core-bootstrap" in status_quiet.stdout
    assert "sealed" in status_quiet.stdout

    # Status with --verbose shows full view
    status_v = run_husks_cli(
        "status", str(site), "--verbose",
        cwd=project
    )
    assert status_v.returncode == 0
    assert "core-bootstrap" in status_v.stdout

    # Status with --json
    status_j = run_husks_cli(
        "status", str(site), "--json",
        cwd=project
    )
    assert status_j.returncode == 0
    status_data = json.loads(status_j.stdout)
    assert status_data["name"] == "core-bootstrap"
    assert status_data["state"] == "sealed"
    assert "root" in status_data
    assert "husk" in status_data


@pytest.mark.beta
def test_beta100_check_silent_on_pass(tmp_path):
    """
    Beta 100: check should be silent on success unless --verbose or --json.
    """
    project = tmp_path / "beta-demo"
    run_husks_cli("init", str(project))
    design = project / "core-bootstrap.json"

    # Check without flags should be silent
    check_result = run_husks_cli("check", str(design), cwd=project)
    assert check_result.returncode == 0
    assert check_result.stdout.strip() == "", "check should be silent on success"

    # With --verbose, should show DAG
    check_v = run_husks_cli("check", str(design), "--verbose", cwd=project)
    assert check_v.returncode == 0
    assert len(check_v.stdout) > 100  # Should have substantial output

    # With --json, should emit JSON
    check_j = run_husks_cli("check", str(design), "--json", cwd=project)
    assert check_j.returncode == 0
    data = json.loads(check_j.stdout)
    assert "command" in data


@pytest.mark.beta
def test_beta100_init_creates_spec_files(tmp_path):
    """
    Beta 100: init should create spec files needed by core-bootstrap.
    """
    project = tmp_path / "beta-demo"
    run_husks_cli("init", str(project))

    # Should create spec directory with CSE specs
    spec_dir = project / "spec"
    assert spec_dir.exists(), "spec/ directory not created"
    assert (spec_dir / "CSE-v1.md").exists(), "CSE-v1.md not created"
    assert (spec_dir / "CSE-v2.md").exists(), "CSE-v2.md not created"

    # Should create other standard files
    assert (project / "core-bootstrap.json").exists()
    assert (project / ".gitignore").exists()
    assert (project / "CLAUDE.md").exists()


@pytest.mark.beta
def test_beta100_verbose_and_json_mutually_exclusive(tmp_path):
    """
    Beta 100: --verbose and --json should be mutually exclusive.
    """
    project = tmp_path / "beta-demo"
    run_husks_cli("init", str(project))
    design = project / "core-bootstrap.json"

    # check with both flags should fail with usage error
    result = run_husks_cli("check", str(design), "--verbose", "--json", cwd=project)
    assert result.returncode != 0, "--verbose and --json should be mutually exclusive"
    assert "mutually exclusive" in result.stderr.lower() or "error" in result.stderr.lower()

    # run with both flags should also fail
    site = project / "site1"
    result = run_husks_cli("run", str(design), "--site", str(site), "--verbose", "--json", "--stub", cwd=project)
    assert result.returncode != 0, "run with --verbose and --json should fail"
    assert "mutually exclusive" in result.stderr.lower() or "error" in result.stderr.lower()
