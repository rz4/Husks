"""All _cmd_* command functions."""

from __future__ import annotations

import json
import sys

from husks.cli.helpers import EXIT_OK


def _cmd_cache_export(args):
    """Export cache to tarball (Beta Gate G1).

    Beta 100 Task A5: Non-committed builds have no servable cache entries
    because cache entries are staged in _pending and only promoted to
    servable on commit. cache_export skips _pending directories, so halted
    builds naturally export 0 entries.
    """
    from husks.build.site import fresh_store
    from husks.build.cache import cache_export

    site = args.site
    export_path = args.file

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
        from husks.utils.console import BOLD, DIM, RESET
        print(f"  exported {BOLD}{count}{RESET} entries {DIM}\u2192 {export_path}{RESET}")

    sys.exit(EXIT_OK)


def _cmd_cache_import(args):
    """Import cache from tarball (Beta Gate G1)."""
    from husks.build.site import fresh_store
    from husks.build.cache import cache_import

    site = args.site
    import_path = args.file
    merge = not args.no_merge

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
        from husks.utils.console import BOLD, DIM, RESET
        print(f"  imported {BOLD}{count}{RESET} entries {DIM}\u2192 {site}{RESET}")

    sys.exit(EXIT_OK)
