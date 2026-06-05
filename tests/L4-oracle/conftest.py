"""L4-oracle test configuration -- shared fixtures."""

import pytest


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
