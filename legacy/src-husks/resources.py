#- resources.py — locate bundled data regardless of install mode.
#
# Wheel installs ship the skill under husks/_resources/
# (see [tool.hatch.build.targets.wheel.force-include]).
# Editable / source checkouts don't materialize _resources/, so we fall back
# to the canonical repo-root location (skills/husks).
#
# Conformance vectors are externalized to husks-conformance; see setup.py
# for the fallback chain.

from pathlib import Path

_PKG = Path(__file__).resolve().parent       # .../husks
_REPO = _PKG.parents[1]                       # src/husks -> src -> repo root


def skill_dir() -> Path:
    """Directory holding the husks SKILL.md for Claude Code."""
    packaged = _PKG / "_resources" / "skill"
    return packaged if packaged.exists() else (_REPO / "skills" / "husks")


def skill_is_packaged() -> bool:
    """True on a wheel install (skill lives in site-packages, must be copied
    into a project rather than symlinked)."""
    return (_PKG / "_resources" / "skill").exists()


def templates_dir() -> Path:
    """Directory holding setup templates for husks init."""
    packaged = _PKG / "_resources" / "templates"
    return packaged if packaged.exists() else (_REPO / "examples" / "templates")
