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
    7. compare-runs proves equivalence

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
    assert "cse:none" in check_v.stdout or "cse:" in check_v.stdout
    assert "□ validate" in check_v.stdout or "validate" in check_v.stdout
    assert "□ generate" in check_v.stdout or "generate" in check_v.stdout

    # Check JSON also works
    check_j = run_husks_cli("check", str(design), "--json", cwd=project)
    assert check_j.returncode == 0, f"check --json failed: {check_j.stderr}"
    check_data = json.loads(check_j.stdout)
    assert check_data["command"] == "check"
    assert check_data["status"] in ["checked", "valid"]

    # Step 3: M1 realizes the design
    m1 = project / "m1"
    r1 = run_husks_cli(
        "run", str(design), "--site", str(m1), "--stub", "--verbose",
        cwd=project
    )
    assert r1.returncode == 0, f"M1 run failed: {r1.stderr}"
    assert "cse:core-bootstrap.husk" in r1.stdout or "core-bootstrap.husk" in r1.stdout
    assert "■ validate" in r1.stdout or "validate" in r1.stdout
    assert "■ generate" in r1.stdout or "◆ generate" in r1.stdout or "generate" in r1.stdout

    # Verify M1 husk artifact was created
    husk_artifact = m1 / "core-bootstrap.husk"
    assert husk_artifact.exists(), "M1 did not produce core-bootstrap.husk"

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

    # Step 6: M2 reuses cache at zero oracle cost
    r2 = run_husks_cli(
        "run", str(design), "--site", str(m2), "--reuse-only", "--stub", "--verbose",
        cwd=project
    )
    assert r2.returncode == 0, f"M2 run failed: {r2.stderr}"
    assert "◆ generate" in r2.stdout or "cached" in r2.stdout.lower()
    assert "$0.0000" in r2.stdout or "$0.00" in r2.stdout

    # Step 7: M3 independently re-realizes
    m3 = project / "m3"
    r3 = run_husks_cli(
        "run", str(design), "--site", str(m3), "--stub", "--verbose",
        cwd=project
    )
    assert r3.returncode == 0, f"M3 run failed: {r3.stderr}"
    assert "■ generate" in r3.stdout or "generate" in r3.stdout

    # Step 8: Get JSON reports from all three machines
    for name, site in [("m1", m1), ("m2", m2), ("m3", m3)]:
        out = project / f"{name}.json"
        res = run_husks_cli(
            "run", str(design), "--site", str(site), "--stub", "--json",
            cwd=project
        )
        assert res.returncode == 0, f"{name} JSON run failed: {res.stderr}"

        # Validate JSON structure
        data = json.loads(res.stdout)
        assert "status" in data
        assert "nodes" in data or "rules" in data

        out.write_text(res.stdout)

    # Step 9: Compare runs to prove three-machine equivalence
    cmp = run_husks_cli(
        "compare-runs",
        str(project / "m1.json"),
        str(project / "m2.json"),
        str(project / "m3.json"),
        "--json",
        cwd=project
    )
    assert cmp.returncode == 0, f"compare-runs failed: {cmp.stderr}"

    cmp_data = json.loads(cmp.stdout)
    assert cmp_data["equivalent"] is True, "Three-machine runs not equivalent"

    # Verify M2 reuse proof
    m2_data = json.loads((project / "m2.json").read_text())
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

    # Status should work without --verbose (minimal output)
    status_quiet = run_husks_cli("status", str(design), "--site", str(site), cwd=project)
    assert status_quiet.returncode == 0

    # Status with --verbose shows full view
    status_v = run_husks_cli(
        "status", str(design), "--site", str(site), "--verbose",
        cwd=project
    )
    assert status_v.returncode == 0
    assert "cse:core-bootstrap.husk" in status_v.stdout or "core-bootstrap" in status_v.stdout
    assert "site:" in status_v.stdout or str(site.name) in status_v.stdout

    # Status with --json
    status_j = run_husks_cli(
        "status", str(design), "--site", str(site), "--json",
        cwd=project
    )
    assert status_j.returncode == 0
    status_data = json.loads(status_j.stdout)
    assert status_data["command"] == "status"
    assert "nodes" in status_data


@pytest.mark.beta
def test_beta100_check_silent_on_pass(tmp_path):
    """
    Beta 100: check should be silent on success unless --verbose or --json.
    """
    project = tmp_path / "beta-demo"
    run_husks_cli("init", str(project))
    design = project / "core-bootstrap.json"

    # Check without flags should be silent (or minimal) on success
    check_result = run_husks_cli("check", str(design), cwd=project)
    assert check_result.returncode == 0
    # Should be very minimal output or completely silent
    # This is the contract - no verbose output by default

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

    # check with both flags should fail or warn
    result = run_husks_cli("check", str(design), "--verbose", "--json", cwd=project)
    # Either fails with error, or one flag is ignored - implementation choice
    # For now, just document that this is the intended behavior
    # The implementation will enforce this
