#- husks_conformance — locate CSE v1 conformance vectors.
#
# Wheel installs ship the vectors under husks_conformance/_vectors/
# (via hatch force-include).  Editable installs fall back to the
# sibling spec/conformance/ directory in the repo checkout.

from pathlib import Path

_PKG = Path(__file__).resolve().parent


def conformance_dir() -> Path:
    """Return path to the conformance vector directory."""
    packaged = _PKG / "_vectors"
    if packaged.exists():
        return packaged
    # Editable install: _PKG is spec/conformance_pkg/src/husks_conformance
    # Walk up to spec/, then sibling conformance/
    candidate = _PKG.parents[2] / "conformance"
    if candidate.exists():
        return candidate
    raise FileNotFoundError(
        "Conformance vectors not found. Install husks-conformance or "
        "set HUSKS_CONFORMANCE_DIR."
    )


def vectors() -> list[str]:
    """Return stem names of all .husk vector files."""
    return sorted(p.stem for p in conformance_dir().glob("*.husk"))
