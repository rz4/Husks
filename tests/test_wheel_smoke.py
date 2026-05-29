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

        # Beta Hardening Task 7: Run canonical beta seed three-machine proof
        # Copy canonical beta_seed from repo (it's in examples/beta_seed/)
        beta_seed_src = repo_root / "examples" / "beta_seed"
        beta_seed_dir = Path(tmpdir) / "beta_seed"
        shutil.copytree(beta_seed_src, beta_seed_dir)

        design_file = beta_seed_dir / "design.json"

        # Machine 1: Build with stub oracle
        m1_site = Path(tmpdir) / "m1_site"
        m1_site.mkdir()

        m1_result = subprocess.run(
            [str(venv_python), "-m", "husks.cli", "run", str(design_file),
             "--site", str(m1_site), "--stub", "--json"],
            capture_output=True,
            text=True,
            timeout=30,
        )

        assert m1_result.returncode == 0, (
            f"M1 run failed:\n"
            f"stdout: {m1_result.stdout}\n"
            f"stderr: {m1_result.stderr}"
        )

        m1_report_file = Path(tmpdir) / "m1.json"
        m1_report_file.write_text(m1_result.stdout)

        # Export cache from M1
        cache_file = Path(tmpdir) / "cache.tar.gz"
        export_result = subprocess.run(
            [str(venv_python), "-m", "husks.cli", "cache", "export",
             str(cache_file), "--site", str(m1_site)],
            capture_output=True,
            text=True,
            timeout=30,
        )

        assert export_result.returncode == 0, (
            f"Cache export failed:\n"
            f"stdout: {export_result.stdout}\n"
            f"stderr: {export_result.stderr}"
        )
        assert cache_file.exists(), "Cache file should be created"

        # Machine 2: Import cache and reuse
        m2_site = Path(tmpdir) / "m2_site"
        m2_site.mkdir()

        import_result = subprocess.run(
            [str(venv_python), "-m", "husks.cli", "cache", "import",
             str(cache_file), "--site", str(m2_site)],
            capture_output=True,
            text=True,
            timeout=30,
        )

        assert import_result.returncode == 0, (
            f"Cache import failed:\n"
            f"stdout: {import_result.stdout}\n"
            f"stderr: {import_result.stderr}"
        )

        m2_result = subprocess.run(
            [str(venv_python), "-m", "husks.cli", "run", str(design_file),
             "--site", str(m2_site), "--reuse-only", "--json"],
            capture_output=True,
            text=True,
            timeout=30,
        )

        assert m2_result.returncode == 0, (
            f"M2 run failed:\n"
            f"stdout: {m2_result.stdout}\n"
            f"stderr: {m2_result.stderr}"
        )

        m2_report_file = Path(tmpdir) / "m2.json"
        m2_report_file.write_text(m2_result.stdout)

        # Machine 3: Independent build
        m3_site = Path(tmpdir) / "m3_site"
        m3_site.mkdir()

        m3_result = subprocess.run(
            [str(venv_python), "-m", "husks.cli", "run", str(design_file),
             "--site", str(m3_site), "--stub", "--json"],
            capture_output=True,
            text=True,
            timeout=30,
        )

        assert m3_result.returncode == 0, (
            f"M3 run failed:\n"
            f"stdout: {m3_result.stdout}\n"
            f"stderr: {m3_result.stderr}"
        )

        m3_report_file = Path(tmpdir) / "m3.json"
        m3_report_file.write_text(m3_result.stdout)

        # Compare the three runs
        compare_result = subprocess.run(
            [str(venv_python), "-m", "husks.cli", "compare-runs",
             str(m1_report_file), str(m2_report_file), str(m3_report_file), "--json"],
            capture_output=True,
            text=True,
            timeout=30,
        )

        assert compare_result.returncode == 0, (
            f"compare-runs failed:\n"
            f"stdout: {compare_result.stdout}\n"
            f"stderr: {compare_result.stderr}"
        )

        comparison = json.loads(compare_result.stdout)
        assert comparison["reports"] == 3, "Should compare 3 reports"
        assert comparison["equivalent"] is True, (
            f"Three-machine proof should pass\n"
            f"Violations: {comparison.get('violations', [])}"
        )

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
