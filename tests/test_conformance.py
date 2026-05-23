"""
test_conformance.py — Golden-vector falsifier for CSE v1.

The gate passes when this test reproduces the build-root from
demo.husk + demo.site/ using only husks.core (stdlib-only reader).

Runnable standalone: python tests/test_conformance.py
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from husks.core import recompute_root, verify

SPEC_DIR = os.path.join(os.path.dirname(__file__), "..", "spec", "conformance")
HUSK_PATH = os.path.join(SPEC_DIR, "demo.husk")
ROOT_PATH = os.path.join(SPEC_DIR, "demo.root")
SITE_DIR = os.path.join(SPEC_DIR, "demo.site")


def _load_expected_root():
    with open(ROOT_PATH, "r") as f:
        return f.read().strip()


def _load_husk():
    with open(HUSK_PATH, "rb") as f:
        return f.read()


def test_build_root():
    """The core reader reproduces the committed build-root."""
    husk_bytes = _load_husk()
    expected = _load_expected_root()
    actual = recompute_root(husk_bytes, SITE_DIR)
    assert actual == expected, (
        f"build-root mismatch:\n"
        f"  expected: {expected}\n"
        f"  actual:   {actual}"
    )


def test_verify():
    """verify() returns True for the committed golden vector."""
    husk_bytes = _load_husk()
    expected = _load_expected_root()
    assert verify(husk_bytes, SITE_DIR, expected)


def test_verify_rejects_wrong_root():
    """verify() returns False when root is tampered."""
    husk_bytes = _load_husk()
    wrong = "0" * 64
    assert not verify(husk_bytes, SITE_DIR, wrong)


def test_site_files_exact():
    """Site files have exactly the expected byte content."""
    expected = {
        "greeting.txt": b"Hello, world!\n",
        "config.txt":   b"mode=demo\n",
        "hello.txt":    b"Hello from demo!\n",
        "result.txt":   b"Combined: Hello from demo!\n",
    }
    for name, content in expected.items():
        path = os.path.join(SITE_DIR, name)
        with open(path, "rb") as f:
            actual = f.read()
        assert actual == content, f"{name}: expected {len(content)} bytes, got {len(actual)}"


if __name__ == "__main__":
    test_build_root()
    test_verify()
    test_verify_rejects_wrong_root()
    test_site_files_exact()
    print("All conformance tests PASSED")
