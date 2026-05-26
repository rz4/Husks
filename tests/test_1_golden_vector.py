"""
test_1_golden_vector.py -- Golden-vector falsifier for CSE v1.

The gate passes when this test reproduces the build-root from
demo.husk + demo.site/ using only husks.core (stdlib-only reader).
"""

import os

from conftest import SPEC_DIR, DEMO_HUSK, DEMO_ROOT, DEMO_SITE, load_demo
from husks.core import recompute_root, verify


def test_build_root():
    """The core reader reproduces the committed build-root."""
    husk_bytes, expected = load_demo()
    actual = recompute_root(husk_bytes, DEMO_SITE)
    assert actual == expected, (
        f"build-root mismatch:\n"
        f"  expected: {expected}\n"
        f"  actual:   {actual}"
    )


def test_verify():
    """verify() returns True for the committed golden vector."""
    husk_bytes, expected = load_demo()
    assert verify(husk_bytes, DEMO_SITE, expected)


def test_verify_rejects_wrong_root():
    """verify() returns False when root is tampered."""
    husk_bytes, _ = load_demo()
    wrong = "0" * 64
    assert not verify(husk_bytes, DEMO_SITE, wrong)


def test_site_files_exact():
    """Site files have exactly the expected byte content."""
    expected = {
        "greeting.txt": b"Hello, world!\n",
        "config.txt":   b"mode=demo\n",
        "hello.txt":    b"Hello from demo!\n",
        "result.txt":   b"Combined: Hello from demo!\n",
    }
    for name, content in expected.items():
        path = os.path.join(DEMO_SITE, name)
        with open(path, "rb") as f:
            actual = f.read()
        assert actual == content, f"{name}: expected {len(content)} bytes, got {len(actual)}"
