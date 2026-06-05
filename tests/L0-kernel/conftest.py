"""L0-kernel test configuration -- conformance vector loaders."""

from pathlib import Path

import pytest

# Conformance vector root (repo-level spec/conformance/).
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
CONFORMANCE_DIR = _REPO_ROOT / "spec" / "conformance"


@pytest.fixture
def conformance_dir():
    """Path to spec/conformance/."""
    return CONFORMANCE_DIR


def _load_vector(name: str) -> tuple[bytes, str, str]:
    """Load a conformance vector: (husk_bytes, site_dir, expected_root)."""
    husk_path = CONFORMANCE_DIR / f"{name}.husk"
    root_path = CONFORMANCE_DIR / f"{name}.root"
    site_path = CONFORMANCE_DIR / f"{name}.site"
    husk_bytes = husk_path.read_bytes()
    expected_root = root_path.read_text().strip()
    return husk_bytes, str(site_path), expected_root


@pytest.fixture(params=["demo", "unsorted", "adversarial"])
def valid_vector(request):
    """Parametrized fixture yielding (husk_bytes, site_dir, expected_root) for each valid vector."""
    return _load_vector(request.param)


@pytest.fixture
def demo_vector():
    return _load_vector("demo")


@pytest.fixture
def unsorted_vector():
    return _load_vector("unsorted")


@pytest.fixture
def adversarial_vector():
    return _load_vector("adversarial")


@pytest.fixture(params=["malformed-leadingzero", "malformed-truncated", "malformed-trailing"])
def malformed_vector(request):
    """Parametrized fixture yielding raw bytes of each malformed .husk file."""
    husk_path = CONFORMANCE_DIR / f"{request.param}.husk"
    return husk_path.read_bytes()
