#- resources.py — locate bundled data regardless of install mode.
#
# Wheel installs ship the conformance vectors and the skill under
# husks/_resources/ (see [tool.hatch.build.targets.wheel.force-include]).
# Editable / source checkouts don't materialize _resources/, so we fall back
# to the canonical repo-root locations (spec/conformance, skills/husks).

from pathlib import Path

_PKG = Path(__file__).resolve().parent       # .../husks
_REPO = _PKG.parents[1]                       # src/husks → src → repo root (source only)


def conformance_dir():
    """Directory holding demo/adversarial/malformed conformance vectors."""
    packaged = _PKG / "_resources" / "conformance"
    return packaged if packaged.exists() else (_REPO / "spec" / "conformance")


def skill_dir():
    """Directory holding the husks SKILL.md for Claude Code."""
    packaged = _PKG / "_resources" / "skill"
    return packaged if packaged.exists() else (_REPO / "skills" / "husks")


def skill_is_packaged():
    """True on a wheel install (skill lives in site-packages, must be copied
    into a project rather than symlinked)."""
    return (_PKG / "_resources" / "skill").exists()
