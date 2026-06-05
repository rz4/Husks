"""L2-seal test configuration -- temp site fixtures."""

import pytest


@pytest.fixture
def tmp_site(tmp_path):
    """Create a temporary site directory, yield its str path."""
    site = tmp_path / "site"
    site.mkdir()
    yield str(site)


@pytest.fixture
def tmp_store(tmp_site):
    """Fresh Store over tmp_site with fuel=10."""
    from husks.seal import fresh_store
    return fresh_store(tmp_site, fuel=10)
