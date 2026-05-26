"""
conftest.py -- Shared fixtures for Husks test suite.
"""

import os
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
