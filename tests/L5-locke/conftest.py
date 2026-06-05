"""L5-locke test configuration -- shared fixtures."""

import pytest


@pytest.fixture
def tmp_site(tmp_path):
    """Temporary site directory."""
    site = tmp_path / "site"
    site.mkdir()
    return site
