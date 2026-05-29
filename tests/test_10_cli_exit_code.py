"""
test_10_cli_exit_code.py -- CLI exit codes on halted vs committed builds.

A halted build must exit 1. A committed build must exit 0.
--soft-fail must exit 0 even on a halted build.
"""

import json
import os
import subprocess
import sys
import tempfile
import shutil


def _run_cli(*extra_args, design=None):
    """Invoke the CLI via subprocess and return (returncode, stdout, stderr)."""
    tmpdir = tempfile.mkdtemp(prefix="cli-exit-")
    try:
        site = os.path.join(tmpdir, "site")
        os.makedirs(site)

        # Create input file next to design.json for site_inputs resolution
        with open(os.path.join(tmpdir, "input.txt"), "w") as f:
            f.write("hello\n")

        if design is not None:
            design.setdefault("site", site)
            # Declare input.txt as a site_input (resolved relative to design file)
            design.setdefault("site_inputs", ["input.txt"])

        design_path = os.path.join(tmpdir, "design.json")
        with open(design_path, "w") as f:
            json.dump(design or {}, f)

        cmd = [
            sys.executable, "-m", "husks.cli", "run",
            design_path, "--site", site, "--stub",
        ] + list(extra_args)
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        return r.returncode, r.stdout, r.stderr
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_committed_build_exits_zero():
    """A simple action that succeeds should exit 0."""
    design = {
        "name": "ok-build",
        "fuel": 10,
        "target": "do-it",
        "rules": [
            {
                "name": "do-it",
                "kind": "action",
                "inputs": ["input.txt"],
                "outputs": ["out.txt"],
                "run": "cp input.txt out.txt",
            },
        ],
    }
    rc, out, err = _run_cli(design=design)
    assert rc == 0, f"committed build should exit 0, got {rc}\nstdout: {out}\nstderr: {err}"


def test_halted_build_exits_nonzero():
    """A build that halts (e.g. action exits nonzero) must exit 1."""
    design = {
        "name": "fail-build",
        "fuel": 10,
        "target": "fail-it",
        "rules": [
            {
                "name": "fail-it",
                "kind": "action",
                "inputs": ["input.txt"],
                "outputs": ["out.txt"],
                "run": "exit 1",
            },
        ],
    }
    rc, out, err = _run_cli(design=design)
    assert rc == 1, f"halted build should exit 1, got {rc}\nstdout: {out}\nstderr: {err}"


def test_halted_build_soft_fail_exits_zero():
    """--soft-fail must exit 0 even on a halted build."""
    design = {
        "name": "soft-fail-build",
        "fuel": 10,
        "target": "fail-it",
        "rules": [
            {
                "name": "fail-it",
                "kind": "action",
                "inputs": ["input.txt"],
                "outputs": ["out.txt"],
                "run": "exit 1",
            },
        ],
    }
    rc, out, err = _run_cli("--soft-fail", design=design)
    assert rc == 0, f"--soft-fail should exit 0, got {rc}\nstdout: {out}\nstderr: {err}"
