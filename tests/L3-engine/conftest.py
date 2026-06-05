"""L3-engine test configuration -- sys.path setup and shared fixtures."""

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
    return str(site)


@pytest.fixture
def tmp_store(tmp_site):
    """Fresh Store with fuel=10 over tmp_site."""
    from seal import fresh_store
    return fresh_store(tmp_site, fuel=10)


def _noop_action(S):
    """Deterministic no-op action for testing."""
    pass
_noop_action._husks_cmd = "noop"


def _write_action(name, content):
    """Create an action that writes content to a named output."""
    def _action(S):
        from seal import site_path, write_text
        write_text(site_path(S, name, write=True), content)
    _action._husks_cmd = f"write-{name}"
    return _action
