"""Shared CLI utilities."""

import sys
from pathlib import Path

# ── Exit codes ────────────────────────────────────────────────────

EXIT_OK = 0
EXIT_BUILD_FAIL = 1
EXIT_USAGE = 2
EXIT_MISSING_DEP = 3
EXIT_DIRTY_STALE = 4
EXIT_INTERNAL = 5

# ── Shared symbols ────────────────────────────────────────────────

_STATE_SYM = {"fresh": "\u2713", "stale": "\u25b8", "missing": "\u2717",
              "dirty": "!", "modified": "!", "failed": "\u2717"}


# ── CLI helpers ───────────────────────────────────────────────────

def resolve_design(args) -> str:
    """Return design path from args or default to design.json."""
    d = getattr(args, "design", None)
    if d:
        return d
    if Path("design.json").exists():
        return "design.json"
    print("error: no design file specified and design.json not found", file=sys.stderr)
    sys.exit(EXIT_USAGE)


def _load_manifest(args) -> tuple[dict, str]:
    """Resolve manifest and site from CLI args, exit on failure."""
    from husks.manifest import resolve_manifest, read_manifest

    site = getattr(args, "site", None)
    design = getattr(args, "design", None)

    if site and not design:
        manifest = read_manifest(site)
    else:
        manifest, site = resolve_manifest(design, site)

    if not site:
        print("error: no site directory. Use --site or provide a design.",
              file=sys.stderr)
        sys.exit(EXIT_USAGE)
    if not manifest:
        print(f"error: no build manifest in {site}/.traces/", file=sys.stderr)
        sys.exit(EXIT_BUILD_FAIL)
    return manifest, site
