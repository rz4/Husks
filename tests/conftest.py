"""
conftest.py -- Shared fixtures for Husks test suite.
"""

import os
import sys
import subprocess
import pytest

SPEC_DIR = os.path.join(os.path.dirname(__file__), "..", "spec", "conformance")
DEMO_HUSK = os.path.join(SPEC_DIR, "demo.husk")
DEMO_ROOT = os.path.join(SPEC_DIR, "demo.root")
DEMO_SITE = os.path.join(SPEC_DIR, "demo.site")


def load_demo():
    """Load demo.husk bytes and expected root string."""
    with open(DEMO_HUSK, "rb") as f:
        husk_bytes = f.read()
    with open(DEMO_ROOT, "r") as f:
        root = f.read().strip()
    return husk_bytes, root


def make_site(tmpdir):
    """Create a site directory with known input files."""
    site = os.path.join(tmpdir, "site")
    os.makedirs(site, exist_ok=True)
    with open(os.path.join(site, "input.txt"), "wb") as f:
        f.write(b"hello\n")
    return site


def run_husks_cli(*args, cwd=None, timeout=30, check=False):
    """Run husks CLI command via subprocess (Beta Gate G3).

    Shared helper for CLI tests using absolute PYTHONPATH and timeouts.
    Ensures tests use the same subprocess pattern and avoid direct pytest imports.

    Parameters
    ----------
    *args : str
        CLI arguments (e.g., "run", "design.json", "--json")
    cwd : str, optional
        Working directory for command
    timeout : int
        Timeout in seconds (default 30)
    check : bool
        If True, raise CalledProcessError on non-zero exit

    Returns
    -------
    subprocess.CompletedProcess
        Result with returncode, stdout, stderr

    Examples
    --------
    >>> result = run_husks_cli("init", tmpdir)
    >>> result = run_husks_cli("run", "design.json", "--json", cwd=tmpdir)
    >>> result = run_husks_cli("compare", "site1", "site2", "--json")
    """
    cmd = [sys.executable, "-m", "husks.cli"] + list(args)
    result = subprocess.run(
        cmd,
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=check,
    )
    return result
