"""
test_8_cross_language.py -- THE PROOF.

Gate: a second-language reader (Node.js) reproduces demo.root from
demo.husk -- the thesis demonstrated across languages, not asserted.

This is the strongest single piece of evidence the project can ship:
here is a husk, here is a verifier in a language the original engine
never knew, here is the matching hash.
"""

import os
import re
import subprocess

import pytest

from conftest import SPEC_DIR, DEMO_HUSK, DEMO_ROOT, DEMO_SITE, load_demo
from husks.core import encode, recompute_root
from husks.designs.transport import elaborate

VERIFY_JS = os.path.join(SPEC_DIR, "verify.mjs")


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


# -- Gate: JS reader reproduces demo.root --------------------------------------

class TestCrossLanguageVerification:
    """The thesis: a husk verifies under a reader the engine never knew."""

    @pytest.mark.alpha

    def test_js_reader_reproduces_demo_root(self):
        """The primary gate: JS reader computes the same root hash."""
        _, expected_root = load_demo()
        stdout, rc = _run_js_verifier(DEMO_HUSK, DEMO_SITE, expected_root)
        assert rc == 0, f"JS verifier failed: {stdout}"
        assert "PASS" in stdout

    @pytest.mark.alpha

    def test_js_root_matches_python_root(self):
        """JS and Python readers agree on the same root hash."""
        _, expected_root = load_demo()
        js_stdout, _ = _run_js_verifier(DEMO_HUSK, DEMO_SITE)
        js_root = js_stdout.split("\n")[0].strip()
        husk_bytes, _ = load_demo()
        py_root = recompute_root(husk_bytes, DEMO_SITE)
        assert js_root == py_root == expected_root

    @pytest.mark.alpha

    def test_js_rejects_wrong_root(self):
        """JS verifier returns nonzero for a wrong expected root."""
        wrong_root = "0" * 64
        _, rc = _run_js_verifier(DEMO_HUSK, DEMO_SITE, wrong_root)
        assert rc != 0

    @pytest.mark.alpha

    def test_js_computes_root_without_expected(self):
        """JS verifier outputs the root hash even without an expected value."""
        _, expected_root = load_demo()
        stdout, rc = _run_js_verifier(DEMO_HUSK, DEMO_SITE)
        assert rc == 0
        root = stdout.strip()
        assert root == expected_root


# -- Elaborated design also verifies cross-language ----------------------------

class TestElaboratedPlanCrossLanguage:
    """A design elaborated by Python verifies under the JS reader."""

    @pytest.mark.alpha

    def test_elaborate_encode_verify_js(self, tmp_path):
        """elaborate -> encode -> write .husk -> JS verifier PASS."""
        _, expected_root = load_demo()

        design = {
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

        husk_bytes = encode(elaborate(design))
        husk_path = str(tmp_path / "elaborated.husk")
        with open(husk_path, "wb") as f:
            f.write(husk_bytes)

        stdout, rc = _run_js_verifier(husk_path, DEMO_SITE, expected_root)
        assert rc == 0, f"JS verifier failed on elaborated design: {stdout}"
        assert "PASS" in stdout


# -- Multi-target cross-language verification ----------------------------------

class TestMultiTargetCrossLanguage:
    """Multi-target husks verify under the JS reader."""

    @pytest.mark.alpha

    def test_multi_target_js_verifier(self, tmp_path):
        """Build a multi-target design, verify with JS reader."""
        from husks.designs.ir import run

        site = str(tmp_path / "site")
        os.makedirs(site)
        inputs_dir = tmp_path / "inputs"
        inputs_dir.mkdir()
        with open(str(inputs_dir / "input.txt"), "w") as f:
            f.write("data\n")

        design = {
            "name": "multi-js",
            "fuel": 10,
            "targets": ["done-a", "done-b"],
            "site": site,
            "site_inputs": {"input.txt": str(inputs_dir / "input.txt")},
            "rules": [
                {
                    "name": "step",
                    "kind": "action",
                    "inputs": ["input.txt"],
                    "outputs": ["out.txt"],
                },
                {"name": "done-a", "kind": "commit", "value": "a-ok"},
                {"name": "done-b", "kind": "commit", "value": "b-ok"},
            ],
        }

        S = run(design)
        assert S["status"] == "committed"
        engine_root = S["build-root"]
        assert engine_root is not None

        husk_path = os.path.join(site, "multi-js.husk")
        assert os.path.isfile(husk_path)

        stdout, rc = _run_js_verifier(husk_path, site, engine_root)
        assert rc == 0, f"JS verifier failed on multi-target: {stdout}"
        assert "PASS" in stdout


# -- JS reader is independent --------------------------------------------------

class TestReaderIndependence:
    """The JS reader uses no Python code -- it is fully independent."""

    @pytest.mark.alpha

    def test_verify_mjs_exists(self):
        assert os.path.isfile(VERIFY_JS)

    @pytest.mark.alpha

    def test_verify_mjs_has_no_python_dependency(self):
        with open(VERIFY_JS, "r") as f:
            source = f.read()
        # No references to the original engine's language or package
        # (strip comments first — "husk" in the file description is fine)
        code_lines = [l for l in source.splitlines()
                       if l.strip() and not l.strip().startswith("//")]
        code_only = "\n".join(code_lines).lower()
        assert "python" not in code_only
        assert "pip" not in code_only
        # Uses only Node.js stdlib
        for imp in ["crypto", "fs", "path"]:
            assert imp in source
        # No npm/third-party imports (only "crypto", "fs", "path" allowed)
        imports = re.findall(r'from\s+"([^"]+)"', source)
        allowed = {"crypto", "fs", "path"}
        for mod in imports:
            assert mod in allowed, (
                f"verify.mjs imports '{mod}' -- only {allowed} allowed"
            )

    @pytest.mark.alpha

    def test_js_rejects_all_malformed_vectors(self):
        """JS reader must reject every rootless (malformed) vector."""
        for husk_path in sorted(
            p for p in os.listdir(SPEC_DIR)
            if p.endswith(".husk")
            and not os.path.exists(os.path.join(SPEC_DIR, p.replace(".husk", ".root")))
        ):
            full = os.path.join(SPEC_DIR, husk_path)
            stdout, rc = _run_js_verifier(full, SPEC_DIR)
            assert rc != 0, (
                f"JS reader accepted malformed vector {husk_path}: {stdout}"
            )

    @pytest.mark.alpha

    def test_verify_mjs_is_compact(self):
        """The reader should be small enough to audit by hand."""
        with open(VERIFY_JS, "r") as f:
            lines = [l for l in f.readlines()
                     if l.strip() and not l.strip().startswith("//")]
        # Design says ~40 lines; allow generous margin
        # (bounded-read guard + parser safety checks add ~20 lines)
        # P1-P4: Three critical validations (depth, digit-only, size cap) add ~30 lines
        assert len(lines) < 150, (
            f"verify.mjs is {len(lines)} non-blank non-comment lines; "
            f"should be compact enough to audit"
        )
