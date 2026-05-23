"""
Phase 6 gate tests — THE PROOF.

Gate: a second-language reader (Node.js) reproduces demo.root from
demo.husk — the thesis demonstrated across languages, not asserted.

This is the strongest single piece of evidence the project can ship:
here is a husk, here is a verifier in a language the original engine
never knew, here is the matching hash.
"""

import os
import subprocess
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from husks.core import encode, recompute_root
from husks.transport import elaborate

SPEC_DIR = os.path.join(os.path.dirname(__file__), "..", "spec", "conformance")
DEMO_HUSK = os.path.join(SPEC_DIR, "demo.husk")
DEMO_ROOT = os.path.join(SPEC_DIR, "demo.root")
DEMO_SITE = os.path.join(SPEC_DIR, "demo.site")
VERIFY_JS = os.path.join(SPEC_DIR, "verify.mjs")


def _load_demo():
    with open(DEMO_HUSK, "rb") as f:
        husk_bytes = f.read()
    with open(DEMO_ROOT, "r") as f:
        root = f.read().strip()
    return husk_bytes, root


def _run_js_verifier(husk_path, site_dir, expected_root=None):
    """Run the Node.js verifier and return (stdout, returncode)."""
    cmd = ["node", VERIFY_JS, husk_path, site_dir]
    if expected_root:
        cmd.append(expected_root)
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    return result.stdout.strip(), result.returncode


@pytest.fixture(autouse=True)
def _require_node():
    """Skip all tests if Node.js is not available."""
    try:
        subprocess.run(["node", "--version"], capture_output=True, timeout=5)
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pytest.skip("Node.js not available")


# ── Gate: JS reader reproduces demo.root ─────────────────────────

class TestCrossLanguageVerification:
    """The thesis: a husk verifies under a reader the engine never knew."""

    def test_js_reader_reproduces_demo_root(self):
        """The primary gate: JS reader computes the same root hash."""
        _, expected_root = _load_demo()
        stdout, rc = _run_js_verifier(DEMO_HUSK, DEMO_SITE, expected_root)
        assert rc == 0, f"JS verifier failed: {stdout}"
        assert "PASS" in stdout

    def test_js_root_matches_python_root(self):
        """JS and Python readers agree on the same root hash."""
        _, expected_root = _load_demo()
        js_stdout, _ = _run_js_verifier(DEMO_HUSK, DEMO_SITE)
        js_root = js_stdout.split("\n")[0].strip()
        husk_bytes, _ = _load_demo()
        py_root = recompute_root(husk_bytes, DEMO_SITE)
        assert js_root == py_root == expected_root

    def test_js_rejects_wrong_root(self):
        """JS verifier returns nonzero for a wrong expected root."""
        wrong_root = "0" * 64
        _, rc = _run_js_verifier(DEMO_HUSK, DEMO_SITE, wrong_root)
        assert rc != 0

    def test_js_computes_root_without_expected(self):
        """JS verifier outputs the root hash even without an expected value."""
        _, expected_root = _load_demo()
        stdout, rc = _run_js_verifier(DEMO_HUSK, DEMO_SITE)
        assert rc == 0
        root = stdout.strip()
        assert root == expected_root


# ── Elaborated plan also verifies cross-language ──────────────────

class TestElaboratedPlanCrossLanguage:
    """A plan elaborated by Python verifies under the JS reader."""

    def test_elaborate_encode_verify_js(self, tmp_path):
        """elaborate → encode → write .husk → JS verifier PASS."""
        _, expected_root = _load_demo()

        plan = {
            "name": "demo",
            "fuel": 10,
            "target": "combine",
            "site_inputs": ["config.txt", "greeting.txt"],
            "rules": [
                {
                    "name": "greet",
                    "kind": "action",
                    "inputs": ["config.txt", "greeting.txt"],
                    "outputs": ["hello.txt"],
                },
                {
                    "name": "combine",
                    "kind": "oracle",
                    "inputs": ["hello.txt"],
                    "outputs": ["result.txt"],
                    "prompt": "Combine the files.",
                    "tools": ["read-file", "write-file"],
                    "fuel": 3,
                },
            ],
        }

        husk_bytes = encode(elaborate(plan))
        husk_path = str(tmp_path / "elaborated.husk")
        with open(husk_path, "wb") as f:
            f.write(husk_bytes)

        stdout, rc = _run_js_verifier(husk_path, DEMO_SITE, expected_root)
        assert rc == 0, f"JS verifier failed on elaborated plan: {stdout}"
        assert "PASS" in stdout


# ── JS reader is independent ─────────────────────────────────────

class TestReaderIndependence:
    """The JS reader uses no Python code — it is fully independent."""

    def test_verify_mjs_exists(self):
        assert os.path.isfile(VERIFY_JS)

    def test_verify_mjs_has_no_python_dependency(self):
        with open(VERIFY_JS, "r") as f:
            source = f.read()
        # No references to the original engine's language or package
        assert "python" not in source.lower()
        assert "husks" not in source.lower()
        assert "pip" not in source.lower()
        # Uses only Node.js stdlib
        for imp in ["crypto", "fs", "path"]:
            assert imp in source
        # No npm/third-party imports (only "crypto", "fs", "path" allowed)
        import re
        imports = re.findall(r'from\s+"([^"]+)"', source)
        allowed = {"crypto", "fs", "path"}
        for mod in imports:
            assert mod in allowed, (
                f"verify.mjs imports '{mod}' — only {allowed} allowed"
            )

    def test_verify_mjs_is_compact(self):
        """The reader should be small enough to audit by hand."""
        with open(VERIFY_JS, "r") as f:
            lines = [l for l in f.readlines()
                     if l.strip() and not l.strip().startswith("//")]
        # Plan says ~40 lines; allow generous margin
        assert len(lines) < 100, (
            f"verify.mjs is {len(lines)} non-blank non-comment lines; "
            f"should be compact enough to audit"
        )
