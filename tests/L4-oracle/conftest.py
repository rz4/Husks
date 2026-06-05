"""L4-oracle test configuration -- sys.path setup and shared fixtures."""

import sys
from pathlib import Path

import pytest

_SITE_SRC = str(Path(__file__).resolve().parent.parent.parent / "src")
if _SITE_SRC not in sys.path:
    sys.path.insert(0, _SITE_SRC)


@pytest.fixture
def tmp_site(tmp_path):
    """Temporary site directory."""
    site = tmp_path / "site"
    site.mkdir()
    return site


@pytest.fixture
def tmp_store(tmp_site):
    """Minimal Store dict for oracle testing (no full L2 dependency)."""
    return {"site": str(tmp_site), "readonly-dirs": []}
