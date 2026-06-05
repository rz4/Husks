"""L1-forms test configuration -- shared helpers."""

from pathlib import Path

import pytest

# Conformance vector root (repo-level spec/conformance/).
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
CONFORMANCE_DIR = _REPO_ROOT / "spec" / "conformance"


def _load_vector(name: str) -> tuple[bytes, str, str]:
    """Load a conformance vector: (husk_bytes, site_dir, expected_root)."""
    husk_bytes = (CONFORMANCE_DIR / f"{name}.husk").read_bytes()
    expected_root = (CONFORMANCE_DIR / f"{name}.root").read_text().strip()
    return husk_bytes, str(CONFORMANCE_DIR / f"{name}.site"), expected_root


@pytest.fixture
def demo_vector():
    return _load_vector("demo")


@pytest.fixture(params=["demo", "unsorted", "adversarial"])
def valid_vector(request):
    return _load_vector(request.param)
