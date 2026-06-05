"""L2-seal test configuration -- sys.path setup and temp site fixtures."""

import os
import shutil
import sys
import uuid
from pathlib import Path

import pytest

# Add @site/src/ to sys.path so `import kernel`, `import forms`, `import seal` work.
_SITE_SRC = str(Path(__file__).resolve().parent.parent.parent / "src")
if _SITE_SRC not in sys.path:
    sys.path.insert(0, _SITE_SRC)


@pytest.fixture
def tmp_site(tmp_path):
    """Create a temporary site directory, yield its str path."""
    site = tmp_path / "site"
    site.mkdir()
    yield str(site)


@pytest.fixture
def tmp_store(tmp_site):
    """Fresh Store over tmp_site with fuel=10."""
    from seal import fresh_store
    return fresh_store(tmp_site, fuel=10)
