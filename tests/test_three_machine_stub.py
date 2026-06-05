"""Three-machine stub integration test.

Exercises the full CLI pipeline on a stub oracle:
  1. check <design.locke>     -- validates design
  2. run --stub (M1)          -- fresh build
  3. cache export M1          -- export cache bundle
  4. cache import to M2       -- import cache to M2 site
  5. run --reuse-only (M2)    -- cache-only rebuild
  6. run --stub (M3)          -- independent fresh build
  7. compare M1 M2 M3 --json  -- asserts proof.satisfied == True
"""

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = str(REPO_ROOT / "src")

STUB_PROOF_PATH = REPO_ROOT / "examples" / "stub-proof" / "stub-proof.json"

# Fallback constant if the example file is missing (e.g. in a partial checkout).
MINIMAL_DESIGN = """\
{
  "name": "stub-proof",
  "fuel": 10,
  "target": "validate",
  "rules": [
    {
      "name": "generate",
      "kind": "oracle",
      "inputs": [],
      "outputs": ["output.txt"],
      "prompt": "Write output.",
      "tools": ["write-file"],
      "fuel": 5
    },
    {
      "name": "validate",
      "kind": "action",
      "inputs": ["output.txt"],
      "outputs": ["result.txt"],
      "run": "cp output.txt result.txt"
    }
  ]
}
"""


def _load_design() -> str:
    """Load the stub-proof design, preferring the canonical example file."""
    if STUB_PROOF_PATH.exists():
        return STUB_PROOF_PATH.read_text()
    return MINIMAL_DESIGN


def _run_cli(*args, check=True, **kwargs):
    """Run the husks CLI as a subprocess with PYTHONPATH=src."""
    env = {**os.environ, "PYTHONPATH": SRC_DIR}
    cmd = [sys.executable, "-c", "from husks.cli import main; main()", *args]
    result = subprocess.run(
        cmd, env=env,
        capture_output=True, text=True,
        timeout=60,
        **kwargs,
    )
    if check and result.returncode != 0:
        raise subprocess.CalledProcessError(
            result.returncode, cmd,
            output=result.stdout, stderr=result.stderr,
        )
    return result


@pytest.fixture
def design_file(tmp_path):
    """Write the stub-proof design to a temp file."""
    p = tmp_path / "stub-proof.json"
    p.write_text(_load_design())
    return str(p)


def test_check(design_file):
    """check validates the design without error."""
    result = _run_cli("check", design_file, "--json")
    assert result.returncode == 0


def test_three_machine_stub_proof(design_file, tmp_path):
    """Full three-machine proof: M1 fresh, M2 reuse-only, M3 fresh, compare."""
    m1 = str(tmp_path / "m1")
    m2 = str(tmp_path / "m2")
    m3 = str(tmp_path / "m3")
    cache_bundle = str(tmp_path / "cache.tar.gz")

    # M1: fresh stub build
    _run_cli("run", design_file, "--stub", "--site", m1)

    # Export M1 cache
    _run_cli("cache", "export", m1, cache_bundle)

    # Import cache into M2
    os.makedirs(m2, exist_ok=True)
    _run_cli("cache", "import", cache_bundle, m2)

    # M2: reuse-only build (should succeed from cache)
    _run_cli("run", design_file, "--reuse-only", "--site", m2)

    # M3: independent fresh stub build
    _run_cli("run", design_file, "--stub", "--site", m3)

    # Compare all three: proof should be satisfied
    result = _run_cli("compare", m1, m2, m3, "--json")
    out = json.loads(result.stdout)

    assert out["equivalent"] is True, f"Sites not equivalent: {out}"
    assert "proof" in out, f"No proof section in compare output: {out}"
    assert out["proof"]["satisfied"] is True, (
        f"Three-machine proof not satisfied: {out['proof']}"
    )

    # Verify oracle-specific evidence checks
    checks = {c["label"]: c["ok"] for c in out["proof"]["checks"]}
    assert checks.get("M1 fired oracles") is True, (
        f"M1 should show fired oracles: {checks}"
    )
    assert checks.get("M2 cache reuse") is True, (
        f"M2 should show cache reuse: {checks}"
    )
    assert checks.get("M3 fired oracles") is True, (
        f"M3 should show fired oracles: {checks}"
    )
