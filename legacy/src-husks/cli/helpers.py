"""Shared CLI utilities."""

import sys
from pathlib import Path

from husks.manifest import resolve_manifest, read_manifest

# ── Exit codes ────────────────────────────────────────────────────
# C21: Documented and frozen exit code contract
#
# Exit Code Contract (frozen):
#
#   Code  Name              Meaning
#   ────────────────────────────────────────────────────────────────
#   0     EXIT_OK           Success - build committed or command succeeded
#   1     EXIT_BUILD_FAIL   Build failed - halted, missing deps, or error
#   2     EXIT_USAGE        Usage error - invalid arguments or options
#   3     EXIT_MISSING_DEP  Missing dependency - LLM backend unavailable
#   4     EXIT_DIRTY_STALE  Status check - artifacts are dirty or stale
#   5     EXIT_INTERNAL     Internal error - unexpected failure
#
# All commands use these codes consistently. Exit code 0 means success;
# non-zero indicates failure with specific semantics.

EXIT_OK = 0
EXIT_BUILD_FAIL = 1
EXIT_USAGE = 2
EXIT_MISSING_DEP = 3
EXIT_DIRTY_STALE = 4
EXIT_INTERNAL = 5

EXIT_CODE_TABLE = """
Exit codes:
  0  Success - build committed or command succeeded
  1  Build failed - halted, missing deps, or error
  2  Usage error - invalid arguments or options
  3  Missing dependency - LLM backend unavailable
  4  Status check - artifacts are dirty or stale
  5  Internal error - unexpected failure
"""

# ── JSON output schema ────────────────────────────────────────────
# C38: Stable JSON schema version across all commands
JSON_SCHEMA_VERSION = "1.0"

def json_output(data: dict, *, command: str | None = None) -> dict:
    """Wrap command output with stable schema version.

    C38: All commands that output JSON should use this function to ensure
    consistent schema versioning.

    Parameters
    ----------
    data : dict
        Command-specific output data
    command : str, optional
        Command name (e.g., "run", "check", "status")

    Returns
    -------
    dict
        Output with top-level schema_version field
    """
    result = {
        "schema_version": JSON_SCHEMA_VERSION,
        **data
    }
    if command:
        result["command"] = command
    return result

# ── Shared symbols ────────────────────────────────────────────────

_STATE_SYM = {"fresh": "\u2713", "stale": "\u25b8", "missing": "\u2717",
              "dirty": "!", "modified": "!", "failed": "\u2717"}


# ── CLI helpers ───────────────────────────────────────────────────

def resolve_design(args) -> str:
    """Return design path from args or default to design.locke / design.json."""
    d = getattr(args, "design", None)
    if d:
        return d
    if Path("design.locke").exists():
        return "design.locke"
    if Path("design.json").exists():
        return "design.json"
    print("error: no design file specified and design.locke not found", file=sys.stderr)
    sys.exit(EXIT_USAGE)


def _load_manifest(args) -> tuple[dict, str]:
    """Resolve manifest and site from CLI args, exit on failure."""
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
