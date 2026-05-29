"""
test_wheel_smoke.py -- Beta Gate G4: Clean wheel install smoke test.

Validates that the Husks package can be built as a wheel, installed in a
clean virtual environment, and successfully run basic CLI commands.

This test catches packaging issues like:
- Missing files in the wheel (missing spec/, skills/, etc.)
- Missing dependencies
- Entry point registration problems
- Import errors in clean environments
"""

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


def test_wheel_build_and_install():
    """Beta Gate G4: Build wheel, install in clean venv, run smoke tests.

    This test:
    1. Builds a wheel distribution in a clean build directory
    2. Creates a fresh virtual environment
    3. Installs the wheel
    4. Runs basic CLI commands to verify functionality
    """
    repo_root = Path(__file__).parent.parent.resolve()
    tmpdir = tempfile.mkdtemp(prefix="wheel-smoke-")

    try:
        # ──────────────────────────────────────────────────────────
        # Step 1: Build wheel
        # ──────────────────────────────────────────────────────────
        dist_dir = Path(tmpdir) / "dist"
        dist_dir.mkdir()

        # Clean build (no editable install artifacts)
        build_result = subprocess.run(
            [sys.executable, "-m", "build", "--wheel", "--outdir", str(dist_dir)],
            cwd=str(repo_root),
            capture_output=True,
            text=True,
            timeout=60,
        )

        if build_result.returncode != 0:
            # If build module not available, skip test
            if "No module named" in build_result.stderr:
                import pytest
                pytest.skip("build module not installed (pip install build)")
                return

            raise AssertionError(
                f"Wheel build failed (exit {build_result.returncode}):\n"
                f"stdout: {build_result.stdout}\n"
                f"stderr: {build_result.stderr}"
            )

        # Find the built wheel
        wheels = list(dist_dir.glob("*.whl"))
        assert len(wheels) == 1, f"Expected 1 wheel, found {len(wheels)}: {wheels}"
        wheel_path = wheels[0]

        # ──────────────────────────────────────────────────────────
        # Step 2: Create fresh virtual environment
        # ──────────────────────────────────────────────────────────
        venv_dir = Path(tmpdir) / "venv"

        venv_result = subprocess.run(
            [sys.executable, "-m", "venv", str(venv_dir)],
            capture_output=True,
            text=True,
            timeout=30,
        )

        assert venv_result.returncode == 0, (
            f"venv creation failed:\n"
            f"stdout: {venv_result.stdout}\n"
            f"stderr: {venv_result.stderr}"
        )

        # Determine venv python path
        if sys.platform == "win32":
            venv_python = venv_dir / "Scripts" / "python.exe"
        else:
            venv_python = venv_dir / "bin" / "python"

        assert venv_python.exists(), f"venv python not found: {venv_python}"

        # ──────────────────────────────────────────────────────────
        # Step 3: Install wheel in clean venv
        # ──────────────────────────────────────────────────────────
        install_result = subprocess.run(
            [str(venv_python), "-m", "pip", "install", str(wheel_path)],
            capture_output=True,
            text=True,
            timeout=60,
        )

        assert install_result.returncode == 0, (
            f"Wheel install failed:\n"
            f"stdout: {install_result.stdout}\n"
            f"stderr: {install_result.stderr}"
        )

        # ──────────────────────────────────────────────────────────
        # Step 4: Smoke tests - verify CLI works
        # ──────────────────────────────────────────────────────────

        # Test 1: husks --version
        version_result = subprocess.run(
            [str(venv_python), "-m", "husks.cli", "--version"],
            capture_output=True,
            text=True,
            timeout=10,
        )

        assert version_result.returncode == 0, (
            f"husks --version failed:\n"
            f"stdout: {version_result.stdout}\n"
            f"stderr: {version_result.stderr}"
        )
        assert "husks" in version_result.stdout.lower(), (
            f"Version output should contain 'husks': {version_result.stdout}"
        )

        # Test 2: husks doctor (environment check)
        doctor_result = subprocess.run(
            [str(venv_python), "-m", "husks.cli", "doctor", "--json"],
            capture_output=True,
            text=True,
            timeout=10,
        )

        assert doctor_result.returncode == 0, (
            f"husks doctor failed:\n"
            f"stdout: {doctor_result.stdout}\n"
            f"stderr: {doctor_result.stderr}"
        )

        # Should return valid JSON
        doctor_output = json.loads(doctor_result.stdout)
        assert "checks" in doctor_output, "doctor --json should have 'checks' field"

        # Test 3: husks run with minimal design
        design_file = Path(tmpdir) / "minimal.json"
        design_file.write_text(json.dumps({
            "name": "smoke",
            "fuel": 5,
            "target": "out",
            "rules": [{
                "name": "out",
                "kind": "action",
                "outputs": ["out.txt"],
                "run": "echo smoke-test > out.txt"
            }]
        }))

        site_dir = Path(tmpdir) / "site"
        site_dir.mkdir()

        run_result = subprocess.run(
            [str(venv_python), "-m", "husks.cli", "run", str(design_file),
             "--site", str(site_dir), "--json"],
            capture_output=True,
            text=True,
            timeout=30,
        )

        assert run_result.returncode == 0, (
            f"husks run failed:\n"
            f"stdout: {run_result.stdout}\n"
            f"stderr: {run_result.stderr}"
        )

        # Should return valid JSON report
        report = json.loads(run_result.stdout)
        assert report["status"] == "committed", f"Build should commit, got {report['status']}"
        assert len(report["nodes"]) == 1, "Should have 1 node"
        assert report["nodes"][0]["name"] == "out"

        # Verify output file was created
        output_file = site_dir / "out.txt"
        assert output_file.exists(), "Output file should be created"
        assert "smoke-test" in output_file.read_text(), "Output file should contain expected content"

        # Task 8 (New): Test beta seed with stub oracle (full beta flow proof)
        beta_design_dir = Path(tmpdir) / "beta_design"
        beta_design_dir.mkdir()

        beta_design_file = beta_design_dir / "design.json"
        beta_design_file.write_text(json.dumps({
            "name": "beta-seed",
            "fuel": 20,
            "target": "validate",
            "site_inputs": ["prompt.txt"],
            "rules": [
                {
                    "name": "generate",
                    "kind": "oracle",
                    "inputs": ["prompt.txt"],
                    "outputs": ["response.txt"],
                    "prompt": "Read the prompt and provide a brief, factual answer.",
                    "tools": [],
                    "fuel": 8,
                },
                {
                    "name": "validate",
                    "kind": "action",
                    "inputs": ["response.txt"],
                    "outputs": ["validation.txt"],
                    "run": "python3 -c \"text = open('response.txt').read(); valid = len(text.strip()) > 0; open('validation.txt', 'w').write('PASS\\\\n' if valid else 'FAIL\\\\n')\"",
                },
            ],
        }))

        # site_inputs are relative to the design file directory
        (beta_design_dir / "prompt.txt").write_text("What is the capital of France?\n")

        beta_site_dir = Path(tmpdir) / "beta_site"
        beta_site_dir.mkdir()

        beta_run_result = subprocess.run(
            [str(venv_python), "-m", "husks.cli", "run", str(beta_design_file),
             "--site", str(beta_site_dir), "--stub", "--json"],
            capture_output=True,
            text=True,
            timeout=30,
        )

        assert beta_run_result.returncode == 0, (
            f"Beta seed run failed:\n"
            f"stdout: {beta_run_result.stdout}\n"
            f"stderr: {beta_run_result.stderr}"
        )

        # Verify beta report structure
        beta_report = json.loads(beta_run_result.stdout)
        assert beta_report["status"] == "committed", f"Beta build should commit, got {beta_report['status']}"
        assert beta_report["schema_version"] == "beta-1", "Should have beta-1 schema"
        assert "oracle_calls" in beta_report, "Report should include oracle_calls"
        assert "cache_hits" in beta_report, "Report should include cache_hits"
        assert "cached_nodes" in beta_report, "Report should include cached_nodes"
        assert beta_report["oracle_calls"] > 0, "Should have fired oracle with stub"
        assert beta_report["cache_hits"] == 0, "First run should have no cache hits"

        # Verify oracle node was executed
        oracle_nodes = [n for n in beta_report["nodes"] if n["kind"] == "oracle"]
        assert len(oracle_nodes) == 1, "Should have 1 oracle node"
        assert oracle_nodes[0]["state"] == "fired", "Oracle should have fired"

        # Verify validation passed
        validation_file = beta_site_dir / "validation.txt"
        assert validation_file.exists(), "Validation output should be created"
        assert "PASS" in validation_file.read_text(), "Validation should pass"

        # Test 4: Verify conformance vectors are included
        # The wheel should include spec/conformance/* as husks/_resources/conformance/*
        conformance_check = subprocess.run(
            [str(venv_python), "-c",
             "from husks.setup import _resolve_conformance; print(_resolve_conformance())"],
            capture_output=True,
            text=True,
            timeout=10,
        )

        assert conformance_check.returncode == 0, (
            f"Conformance resource check failed:\n"
            f"stdout: {conformance_check.stdout}\n"
            f"stderr: {conformance_check.stderr}"
        )

        # Test 5: doctor --selftest (uses conformance vectors)
        selftest_result = subprocess.run(
            [str(venv_python), "-m", "husks.cli", "doctor", "--selftest", "--json"],
            capture_output=True,
            text=True,
            timeout=10,
        )

        assert selftest_result.returncode == 0, (
            f"doctor --selftest failed:\n"
            f"stdout: {selftest_result.stdout}\n"
            f"stderr: {selftest_result.stderr}"
        )

        # Extract JSON from output (may have verbose output before JSON line)
        # The JSON is on the last non-empty line
        stdout_lines = [line for line in selftest_result.stdout.strip().split('\n') if line.strip()]
        json_line = stdout_lines[-1] if stdout_lines else "{}"

        selftest_output = json.loads(json_line)
        assert selftest_output.get("selftest") is True, (
            "Selftest should pass in clean install"
        )

        print("\n✓ Wheel smoke test: PASS")
        print(f"  Built: {wheel_path.name}")
        print(f"  Installed in clean venv: {venv_dir}")
        print(f"  All smoke tests passed")

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_wheel_includes_resources():
    """Verify that critical resources are included in wheel manifest.

    This test checks the wheel's RECORD file to ensure that:
    - Conformance vectors are included
    - Skill files are included
    - Core Python modules are included
    """
    repo_root = Path(__file__).parent.parent.resolve()
    tmpdir = tempfile.mkdtemp(prefix="wheel-manifest-")

    try:
        # Build wheel
        dist_dir = Path(tmpdir) / "dist"
        dist_dir.mkdir()

        build_result = subprocess.run(
            [sys.executable, "-m", "build", "--wheel", "--outdir", str(dist_dir)],
            cwd=str(repo_root),
            capture_output=True,
            text=True,
            timeout=60,
        )

        if build_result.returncode != 0:
            if "No module named" in build_result.stderr:
                import pytest
                pytest.skip("build module not installed")
                return
            raise AssertionError(f"Wheel build failed: {build_result.stderr}")

        # Extract and check RECORD
        wheels = list(dist_dir.glob("*.whl"))
        assert len(wheels) == 1
        wheel_path = wheels[0]

        # Use zipfile to read wheel contents
        import zipfile
        with zipfile.ZipFile(wheel_path, 'r') as whl:
            # Find RECORD file
            record_files = [name for name in whl.namelist() if name.endswith('RECORD')]
            assert len(record_files) == 1, f"Expected 1 RECORD, found {len(record_files)}"

            record_content = whl.read(record_files[0]).decode('utf-8')
            files_in_wheel = [line.split(',')[0] for line in record_content.strip().split('\n')]

            # Check critical files are present
            conformance_files = [f for f in files_in_wheel if '_resources/conformance' in f]
            assert len(conformance_files) > 0, (
                "Wheel should include conformance vectors in _resources/conformance/"
            )

            skill_files = [f for f in files_in_wheel if '_resources/skill' in f]
            assert len(skill_files) > 0, (
                "Wheel should include skill files in _resources/skill/"
            )

            # Check core modules
            assert any('husks/cli' in f for f in files_in_wheel), "Missing husks.cli module"
            assert any('husks/build' in f for f in files_in_wheel), "Missing husks.build module"
            assert any('husks/designs' in f for f in files_in_wheel), "Missing husks.designs module"

            print("\n✓ Wheel manifest check: PASS")
            print(f"  Conformance files: {len(conformance_files)}")
            print(f"  Skill files: {len(skill_files)}")
            print(f"  Total files in wheel: {len(files_in_wheel)}")

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)
