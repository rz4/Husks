"""All _cmd_* command functions."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from husks.cli.helpers import EXIT_OK, EXIT_USAGE
from husks.build.site import fresh_store
from husks.build.cache import cache_export, cache_import
from husks.utils.console import BOLD, DIM, RESET


def _cmd_cache_export(args):
    """Export cache to tarball (Beta Gate G1).

    Beta 100 Task A5: Non-committed builds have no servable cache entries
    because cache entries are staged in _pending and only promoted to
    servable on commit. cache_export skips _pending directories, so halted
    builds naturally export 0 entries.
    """
    site = args.site
    export_path = args.file

    # C29: Validate paths before creating store
    if not export_path.endswith('.tar.gz'):
        print(f"error: export path must end with .tar.gz: {export_path}", file=sys.stderr)
        sys.exit(EXIT_USAGE)

    if not Path(site).exists():
        print(f"error: site directory does not exist: {site}", file=sys.stderr)
        sys.exit(EXIT_USAGE)

    if not Path(site).is_dir():
        print(f"error: site path is not a directory: {site}", file=sys.stderr)
        sys.exit(EXIT_USAGE)

    # Create store to access cache
    S = fresh_store(site, fuel=1)

    # Export cache (skips _pending directories per Beta 100 Task A5)
    count = cache_export(S, export_path)

    if args.json_output:
        output = {
            "status": "exported",
            "site": site,
            "file": export_path,
            "entries": count,
        }
        print(json.dumps(output, indent=2))
    else:
        print(f"  exported {BOLD}{count}{RESET} entries {DIM}\u2192 {export_path}{RESET}")

    sys.exit(EXIT_OK)


def _cmd_cache_import(args):
    """Import cache from tarball (Beta Gate G1)."""
    site = args.site
    import_path = args.file
    merge = not args.no_merge

    # C29: Validate paths before creating store
    if not import_path.endswith('.tar.gz'):
        print(f"error: import path must end with .tar.gz: {import_path}", file=sys.stderr)
        sys.exit(EXIT_USAGE)

    if not Path(import_path).exists():
        print(f"error: import file does not exist: {import_path}", file=sys.stderr)
        sys.exit(EXIT_USAGE)

    if not Path(import_path).is_file():
        print(f"error: import path is not a file: {import_path}", file=sys.stderr)
        sys.exit(EXIT_USAGE)

    # Create store to access cache
    S = fresh_store(site, fuel=1)

    # Import cache
    count = cache_import(S, import_path, merge=merge)

    if args.json_output:
        output = {
            "status": "imported",
            "site": site,
            "file": import_path,
            "entries": count,
            "merge": merge,
        }
        print(json.dumps(output, indent=2))
    else:
        print(f"  imported {BOLD}{count}{RESET} entries {DIM}\u2192 {site}{RESET}")

    sys.exit(EXIT_OK)
