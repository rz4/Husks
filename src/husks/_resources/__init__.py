from pathlib import Path

_PKG = Path(__file__).resolve().parent


def conformance_dir() -> Path:
    """Return the conformance vectors directory."""
    bundled = _PKG / "conformance"
    if bundled.exists():
        return bundled
    # Editable install: fall back to spec/conformance/ in repo
    repo = _PKG.parents[2] / "spec" / "conformance"
    if repo.exists():
        return repo
    raise FileNotFoundError(
        "Conformance vectors not found. Install husks or "
        "set HUSKS_CONFORMANCE_DIR."
    )
