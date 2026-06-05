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
    >>> result = run_husks_cli("cache", "export", "--output", "cache.tgz", "--json")
    """
    # Set absolute PYTHONPATH to include src/ directory
    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    src_path = os.path.join(repo_root, "src")

    env = os.environ.copy()
    if "PYTHONPATH" in env:
        env["PYTHONPATH"] = f"{src_path}{os.pathsep}{env['PYTHONPATH']}"
    else:
        env["PYTHONPATH"] = src_path

    cmd = [sys.executable, "-m", "husks.cli"] + list(args)

    try:
        result = subprocess.run(
            cmd,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=check,
            env=env,
        )
    except subprocess.TimeoutExpired as e:
        # Add useful context to timeout failures
        raise AssertionError(
            f"Command timed out after {timeout}s\n"
            f"Command: {' '.join(cmd)}\n"
            f"cwd: {cwd}\n"
            f"stdout: {e.stdout}\n"
            f"stderr: {e.stderr}"
        ) from e
    except subprocess.CalledProcessError as e:
        # Add useful context to check=True failures
        raise AssertionError(
            f"Command failed with exit code {e.returncode}\n"
            f"Command: {' '.join(cmd)}\n"
            f"cwd: {cwd}\n"
            f"stdout: {e.stdout}\n"
            f"stderr: {e.stderr}"
        ) from e

    return result


# ── Cache Test Fixtures ─────────────────────────────────────────────

import tempfile
import shutil
from pathlib import Path


@pytest.fixture
def cache_temp_site():
    """Create temporary site directory with automatic cleanup for cache tests."""
    tmpdir = tempfile.mkdtemp(prefix="test-cache-")
    try:
        site = Path(tmpdir) / "site"
        site.mkdir()
        yield {"tmpdir": tmpdir, "site": site}
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


@pytest.fixture
def cache_temp_site_with_input():
    """Create temporary site with input.txt file for cache tests."""
    tmpdir = tempfile.mkdtemp(prefix="test-cache-")
    try:
        site = Path(tmpdir) / "site"
        site.mkdir()
        (site / "input.txt").write_text("data\n")
        yield {"tmpdir": tmpdir, "site": site}
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


@pytest.fixture
def basic_stub_oracle():
    """Basic oracle that writes deterministic output for cache tests."""
    def oracle(S, rule_name, recipe, outputs):
        from husks.build.site import write_text, site_path
        write_text(site_path(S, outputs[0], write=True), "result\n")
        return {"tokens_in": 100, "tokens_out": 50, "cost_usd": 0.001, "fuel_steps": 1}
    return oracle


@pytest.fixture
def counting_oracle():
    """Oracle that increments counter each call for cache tests."""
    counter = {"n": 0}
    def oracle(S, rule_name, recipe, outputs):
        counter["n"] += 1
        from husks.build.site import write_text, site_path
        write_text(site_path(S, outputs[0], write=True), f"result {counter['n']}\n")
        return {"tokens_in": 100, "tokens_out": 50, "cost_usd": 0.001, "fuel_steps": 1}
    oracle.count = counter
    return oracle


@pytest.fixture
def expensive_oracle():
    """Oracle with high cost for testing usage tracking in cache tests."""
    def oracle(S, rule_name, recipe, outputs):
        from husks.build.site import write_text, site_path
        write_text(site_path(S, outputs[0], write=True), "expensive result\n")
        return {"tokens_in": 1000, "tokens_out": 500, "cost_usd": 0.10, "fuel_steps": 1}
    return oracle


def make_oracle_node(name="worker", inputs=None, outputs=None, prompt="Test", fuel=5):
    """Create a standard oracle rule node for cache testing.

    Args:
        name: Rule name
        inputs: List of input files (default: ["input.txt"])
        outputs: List of output files (default: ["output.txt"])
        prompt: Oracle prompt text
        fuel: Oracle fuel allocation

    Returns:
        Rule node for use with build()
    """
    from husks.build import rule, oracle
    return rule(
        name,
        inputs=inputs or ["input.txt"],
        outputs=outputs or ["output.txt"],
        recipe=oracle(prompt=prompt, fuel=fuel),
    )


def read_history(site, rule_name):
    """Read and parse history file for a rule in cache tests.

    Args:
        site: Site directory path
        rule_name: Name of the rule

    Returns:
        List of history records (parsed JSON objects)
    """
    import json
    history_file = Path(site) / ".traces" / f"{rule_name}.history.jsonl"
    if not history_file.exists():
        return []
    content = history_file.read_text().strip()
    if not content:
        return []
    return [json.loads(line) for line in content.split('\n')]
