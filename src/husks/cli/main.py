"""Argparse and dispatch."""

import argparse
import sys

from husks.designs.ir import from_json, from_locke

from husks.cli.helpers import EXIT_OK, EXIT_BUILD_FAIL, EXIT_USAGE, EXIT_INTERNAL, resolve_design
from husks.cli.cmd import (
    _cmd_check, _cmd_run, _cmd_verify, _cmd_status,
    _cmd_explain, _cmd_history, _cmd_doctor, _cmd_compare,
    _cmd_cache_export, _cmd_cache_import,
)


def _get_version() -> str:
    """Get package version.

    C39: Raises exception instead of silent fallback to help diagnose broken installs.
    """
    try:
        from importlib.metadata import version as pkg_version
        return pkg_version("husks")
    except Exception as e:
        # C39: Non-silent failure - let caller handle
        raise RuntimeError(f"failed to get package version: {e}") from e


# -- Styled help rendering ---------------------------------------------------

_NO_VALUE_ACTIONS = (
    argparse._StoreTrueAction,
    argparse._StoreFalseAction,
    argparse._StoreConstAction,
    argparse._CountAction,
)


def _flag_str(action):
    """Build the left-column display string for an argparse action."""
    if not action.option_strings:
        return action.metavar or action.dest
    parts = sorted(action.option_strings, key=len)
    s = ", ".join(parts)
    if isinstance(action, _NO_VALUE_ACTIONS):
        return s
    if action.metavar:
        meta = action.metavar
    elif action.choices:
        meta = "{" + ",".join(str(c) for c in action.choices) + "}"
    else:
        meta = action.dest.upper()
    return f"{s} {meta}"


class _StyledHelpAction(argparse.Action):
    """Custom -h/--help action that renders our branded subcommand help."""

    def __init__(self, option_strings, dest=argparse.SUPPRESS,
                 default=argparse.SUPPRESS, help=None):
        super().__init__(option_strings=option_strings, dest=dest,
                         default=default, nargs=0, help=help)

    def __call__(self, parser, namespace, values, option_string=None):
        _print_subcommand_help(parser)
        parser.exit()


def _print_subcommand_help(parser):
    """Render branded help for a subcommand parser."""
    from husks.cli.surface import emit_subcommand_help
    print(emit_subcommand_help(parser))


def _sub_parser(sub, name, parents=None, **kwargs):
    """Create a subparser with styled help instead of stock argparse help.

    Parameters
    ----------
    parents : list, optional
        List of parent ArgumentParsers to inherit arguments from.
    """
    kwargs.setdefault("description", kwargs.get("help", ""))
    kwargs["add_help"] = False
    if parents:
        kwargs["parents"] = parents
    p = sub.add_parser(name, **kwargs)
    p.add_argument("-h", "--help", action=_StyledHelpAction, help=argparse.SUPPRESS)
    return p


def _print_help(*, animate: bool = False) -> None:
    from husks.cli.surface import emit_help
    ver = _get_version()
    result = emit_help(ver, animate=animate)
    if result is not None:
        print(result)


def main():
    # Create a parent parser with shared flags
    common_parser = argparse.ArgumentParser(add_help=False)
    common_parser.add_argument("-v", "--verbose", action="store_true",
                              help="Enable verbose output (show details)")

    p = argparse.ArgumentParser(prog="husks", description="Husks design CLI",
                                add_help=False)

    # Global options
    p.add_argument("-h", "--help", action="store_true", default=False,
                   help="Show help and exit")
    p.add_argument("--color", choices=["auto", "always", "never"], default="auto",
                   help="Color output mode")
    p.add_argument("--quiet", "-q", action="store_true",
                   help="Suppress non-essential output")
    p.add_argument("--version", action="store_true",
                   help="Print version and exit")
    p.add_argument("--version-json", action="store_true",
                   help="Print version info as JSON and exit")

    sub = p.add_subparsers(dest="cmd")

    # init
    i = _sub_parser(sub, "init", parents=[common_parser], help="Scaffold a new project")
    i.add_argument("target", nargs="?", default=".",
                   help="Target directory (default: .)")
    i.add_argument("template", nargs="?", default="core-bootstrap",
                   help="Project template (default: core-bootstrap)")
    i.add_argument("--force", action="store_true",
                   help="Overwrite existing files")

    # check
    c = _sub_parser(sub, "check", help="Validate a design")
    c.add_argument("design", nargs="?", default=None,
                   help="Path to design file (.locke or .json). Defaults to design.locke.")
    # C25: Use mutually exclusive group for --verbose and --json
    c_output = c.add_mutually_exclusive_group()
    c_output.add_argument("--verbose", "-v", action="store_true",
                          help="Show full design details after validation (replaces old 'show')")
    c_output.add_argument("--json", action="store_true", dest="json_output",
                          help="Output categorized check results as JSON")

    # run
    r = _sub_parser(sub, "run", help="Execute a design into a site")
    r.add_argument("design", nargs="?", default=None,
                   help="Path to design file (.locke or .json). Defaults to design.locke.")
    r.add_argument("--site", help="Site directory (default: /tmp/husks-<design-name>)")
    r.add_argument("--model", help="LLM model for oracle rules",
                   default="anthropic/claude-haiku-4-5-20251001")
    r.add_argument("--stub", action="store_true",
                   help="Use stub oracle (no LLM, placeholder outputs)")
    r.add_argument("--backend", choices=["litellm", "claude-code"],
                   default="litellm", help="Oracle backend (default: litellm)")
    r.add_argument("--reuse-only", action="store_true",
                   help="Only use cached results, never call oracle (Beta Gate D5)")
    r.add_argument("--soft-fail", action="store_true",
                   help="Exit 0 even when the build halts")
    # C25: Use mutually exclusive group for --verbose and --json
    r_output = r.add_mutually_exclusive_group()
    r_output.add_argument("--verbose", "-v", action="store_true",
                          help="Verbose output (full trace + detailed report)")
    r_output.add_argument("--json", action="store_true", dest="json_output",
                          help="Output full Report as JSON instead of text")
    r.add_argument("--report-json", metavar="PATH",
                   help="Write JSON report to file (sidecar; may be used with --verbose)")

    # status
    st_cmd = _sub_parser(sub, "status", parents=[common_parser], help="Inspect site state")
    st_cmd.add_argument("site", help="Site directory path")
    st_cmd.add_argument("--json", action="store_true", dest="json_output",
                        help="Output as JSON")
    st_cmd.add_argument("--fail-if-dirty", action="store_true",
                        help="Exit 4 if any artifact is modified")
    st_cmd.add_argument("--fail-if-stale", action="store_true",
                        help="Exit 4 if any rule is stale")

    # explain
    e = _sub_parser(sub, "explain", parents=[common_parser], help="Navigate the residue tree")
    e.add_argument("subject", nargs="?", default=None,
                   help="Design file path (.json/.locke), or rule/artifact name")
    # Phase 5: Navigator mode flags
    e.add_argument("--node", help="Select node in the residue tree")
    e.add_argument("--aperture", type=int, choices=[0, 1, 2, 3], default=1,
                   help="Detail level: 0=node, 1=output, 2=seal, 3=trace (default: 1)")
    e.add_argument("--interactive", action="store_true",
                   help="Enable interactive navigation (Phase 6)")
    # Legacy mode flags
    e.add_argument("--graph", action="store_true",
                   help=argparse.SUPPRESS)  # backwards-compat no-op
    e.add_argument("--diff", action="store_true",
                   help="Show differences between sealed and current artifacts")
    e.add_argument("--seal", metavar="SUBJECT",
                   help="Show seal material for a rule, artifact, or root")
    e.add_argument("--format", choices=["text", "mermaid", "dot", "json"],
                   default="text", dest="graph_format",
                   help="Output format for --graph (default: text)")
    e.add_argument("--artifact", dest="artifact", action="append", default=[],
                   help="Specific artifact to include in diff (can be repeated)")
    e.add_argument("--site", help="Site directory")
    e.add_argument("--json", action="store_true", dest="json_output",
                   help="Output as JSON")

    # history
    h = _sub_parser(sub, "history", parents=[common_parser], help="Show convergence across runs")
    h.add_argument("design", nargs="?", default=None,
                   help="Path to design file (.locke or .json). Defaults to design.locke.")
    h.add_argument("rule", nargs="?", default=None,
                   help="Rule name (omit for summary of all rules)")
    h.add_argument("--site", help="Override site directory")
    h.add_argument("-n", type=int, default=5,
                   help="Number of recent entries to show (default: 5)")

    # doctor
    doc = _sub_parser(sub, "doctor", parents=[common_parser], help="Diagnose the local environment")
    doc.add_argument("--json", action="store_true", dest="json_output",
                     help="Output as JSON")
    doc.add_argument("--selftest", action="store_true",
                     help="Run frozen conformance vectors")
    doc.add_argument("--conformance", action="store_true",
                     help="Run external reader conformance gate")
    doc.add_argument("--live", action="store_true",
                     help="Check live oracle readiness (API key, litellm, oracle ping, dev tools)")
    doc.add_argument("--reader", dest="reader_cmd", default=None,
                     help='Reader command for --conformance, e.g. "python my_reader.py"')
    doc.add_argument("--stamp-dir", default=None,
                     help="Write VERIFIED stamp here on conformance pass")
    doc.add_argument("--no-cross-check", action="store_false", dest="cross_check",
                     help="Disable JS cross-check (with --conformance)")

    # compare (Beta Gate C6/C7)
    cmp = _sub_parser(sub, "compare", parents=[common_parser], help="Equivalence across sites (three-machine proof with 3+)")
    cmp.add_argument("sites", nargs="+",
                     help="Site directories to compare (2 or more)")
    cmp.add_argument("--json", action="store_true", dest="json_output",
                     help="Output comparison result as JSON")
    cmp.add_argument("--roots-only", action="store_true",
                     help="Compare build roots only (skip output hash checks)")
    cmp.add_argument("--hashes-only", action="store_true",
                     help="Compare output hashes only (skip root checks)")
    cmp.add_argument("--diff", action="store_true",
                     help="Show unified diff of generated files that differ")

    # verify
    v = _sub_parser(sub, "verify", parents=[common_parser], help="Recompute .husk root hash in a site")
    v.add_argument("site", help="Site directory containing .husk file")
    v.add_argument("--name", help="Build name (auto-detected if only one .husk in site)")
    v.add_argument("--json", action="store_true", dest="json_output",
                   help="Output as JSON")

    # cache (Beta Gate G1/D5) - nested subcommands
    cache_parser = _sub_parser(sub, "cache", parents=[common_parser], help="Cache management commands")
    cache_sub = cache_parser.add_subparsers(dest="cache_cmd", required=True)

    # cache export
    cache_exp = _sub_parser(cache_sub, "export", parents=[common_parser], help="Pack site cache for transfer")
    cache_exp.add_argument("file", help="Path to write .tar.gz archive")
    cache_exp.add_argument("--site", required=True, help="Site directory containing cache")
    cache_exp.add_argument("--json", action="store_true", dest="json_output",
                           help="Output result as JSON")

    # cache import
    cache_imp = _sub_parser(cache_sub, "import", parents=[common_parser], help="Unpack cache into a site")
    cache_imp.add_argument("file", help="Path to .tar.gz archive")
    cache_imp.add_argument("--site", required=True, help="Site directory to import into")
    cache_imp.add_argument("--no-merge", action="store_true",
                           help="Clear existing cache before import (default: merge)")
    cache_imp.add_argument("--json", action="store_true", dest="json_output",
                           help="Output result as JSON")

    args = p.parse_args()

    # --help / -h (full speed, no animation)
    if args.help:
        _print_help(animate=False)
        sys.exit(EXIT_OK)

    # --version or --version-json
    if args.version or args.version_json:
        try:
            version = _get_version()
        except RuntimeError as e:
            # C39: Show version error clearly
            print(f"error: {e}", file=sys.stderr)
            sys.exit(EXIT_INTERNAL)

        # C40: Support --version-json for machine-readable version info
        if args.version_json:
            from husks.core import CSE_VERSION
            import json
            version_info = {
                "husks_version": version,
                "cse_wire_version": CSE_VERSION.decode('utf-8'),
                "seal_format_version": 1,
                "schema_version": "1.0",
            }
            print(json.dumps(version_info, indent=2))
        else:
            print(f"husks {version}")
        sys.exit(EXIT_OK)

    if args.cmd is None:
        _print_help(animate=True)
        sys.exit(EXIT_USAGE)

    # C25: Mutually exclusive flags now handled by argparse groups

    # C27, C28: Validate oracle-related flag combinations
    if args.cmd == "run":
        stub = getattr(args, 'stub', False)
        model = getattr(args, 'model', None)

        # C27: --reuse-only + --stub is allowed (reuse cached stub outputs)
        # No validation needed - they work together

        # C28: Warn when --model is passed with --stub
        if stub and model and model != "anthropic/claude-haiku-4-5-20251001":
            print("warning: --model is ignored when --stub is used (no LLM calls)", file=sys.stderr)

    # ── init ──────────────────────────────────────────────────
    if args.cmd == "init":
        from husks.setup import init
        verbose = getattr(args, 'verbose', False)
        sys.exit(init(args.target, template=args.template, claude_code=True, force=args.force, verbose=verbose))

    # ── status (may or may not need a design) ────────────────
    if args.cmd == "status":
        _cmd_status(args)
        return

    # ── explain (multiple modes) ─────────────────────────────
    if args.cmd == "explain":
        _cmd_explain(args)
        return

    # ── doctor ───────────────────────────────────────────────
    if args.cmd == "doctor":
        _cmd_doctor(args)
        return

    # ── compare (Beta Gate C6/C7) ────────────────────────────
    if args.cmd == "compare":
        _cmd_compare(args)
        return

    # ── verify ───────────────────────────────────────────────
    if args.cmd == "verify":
        _cmd_verify(args)
        return

    # ── cache commands (Beta Gate G1/D5) ──────────────────────────
    if args.cmd == "cache":
        if args.cache_cmd == "export":
            _cmd_cache_export(args)
        elif args.cache_cmd == "import":
            _cmd_cache_import(args)
        return

    # ── Commands that require a design ───────────────────────
    design_path = resolve_design(args)
    args.design = design_path
    is_locke = design_path.endswith(".locke")

    # Beta Gate F/G: Catch design loading errors and emit JSON when --json specified
    try:
        design = from_locke(design_path) if is_locke else from_json(design_path)
    except Exception as e:
        json_mode = getattr(args, 'json_output', False)
        if json_mode:
            import json
            error_report = {
                "status": "error",
                "error_type": "design_load_failure",
                "error": str(e),
                "design_path": design_path,
            }
            print(json.dumps(error_report, indent=2))
        else:
            print(f"error loading design: {e}", file=sys.stderr)
        sys.exit(EXIT_USAGE)

    if args.cmd == "check":
        _cmd_check(args, design)

    elif args.cmd == "run":
        # Auto-generate site from design name if --site not provided
        if not args.site:
            design_name = design.get("name", "unnamed")
            args.site = f"/tmp/husks-{design_name}"
        _cmd_run(args, design)

    elif args.cmd == "history":
        _cmd_history(args, design)


def _cli_entry():
    """C36: Top-level exception handler wrapper for main().

    Catches uncaught exceptions and converts them to EXIT_INTERNAL with
    a one-line error message. Full traceback is shown only under --verbose.
    """
    try:
        main()
    except KeyboardInterrupt:
        # C35: Handle Ctrl-C gracefully
        print("\nInterrupted", file=sys.stderr)
        sys.exit(130)  # Standard Unix exit code for SIGINT
    except SystemExit:
        # Let explicit sys.exit() calls pass through
        raise
    except Exception as e:
        # Check if --verbose was passed (best effort - may not be available)
        verbose = "--verbose" in sys.argv or "-v" in sys.argv

        if verbose:
            # Show full traceback under --verbose
            import traceback
            print("Internal error:", file=sys.stderr)
            traceback.print_exc()
        else:
            # Concise error message otherwise
            error_type = type(e).__name__
            print(f"error: {error_type}: {e}", file=sys.stderr)
            print("(run with --verbose for full traceback)", file=sys.stderr)

        sys.exit(EXIT_INTERNAL)


if __name__ == "__main__":
    _cli_entry()
