"""Argparse and dispatch."""

import argparse
import sys

from husks.designs.ir import from_json

from husks.cli.helpers import EXIT_OK, EXIT_BUILD_FAIL, EXIT_USAGE, resolve_design
from husks.cli.cmd import (
    _cmd_check, _cmd_run, _cmd_run_hy, _cmd_status,
    _cmd_explain, _cmd_history, _cmd_doctor, _cmd_compare,
    _cmd_cache_export, _cmd_cache_import,
)


def _get_version() -> str:
    try:
        from importlib.metadata import version as pkg_version
        return pkg_version("husks")
    except Exception:
        return "0.1.0"


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
    from husks.utils.console import BOLD, DIM, RESET

    desc = parser.description or ""

    positionals = []
    optionals = []
    subcommands = []

    for action in parser._actions:
        if action.help == argparse.SUPPRESS:
            continue
        if isinstance(action, _StyledHelpAction):
            continue
        if isinstance(action, argparse._SubParsersAction):
            for ca in action._choices_actions:
                subcommands.append((ca.metavar, ca.help or ""))
            continue
        if action.option_strings:
            optionals.append(action)
        else:
            positionals.append(action)

    # Compute column width from all left-column entries
    all_lefts = [_flag_str(a) for a in positionals + optionals]
    all_lefts += [name for name, _ in subcommands]
    col = max((len(s) for s in all_lefts), default=14) + 2
    col = max(col, 18)

    lines = [
        f"  {BOLD}{parser.prog}{RESET}",
        f"  {DIM}{desc}{RESET}",
    ]

    if positionals:
        lines.append(f"\n  {BOLD}arguments{RESET}")
        for action in positionals:
            fs = _flag_str(action)
            lines.append(f"    {fs:<{col}}{DIM}{action.help or ''}{RESET}")

    if optionals:
        lines.append(f"\n  {BOLD}options{RESET}")
        for action in optionals:
            fs = _flag_str(action)
            lines.append(f"    {fs:<{col}}{DIM}{action.help or ''}{RESET}")

    if subcommands:
        lines.append(f"\n  {BOLD}commands{RESET}")
        for name, help_text in subcommands:
            lines.append(f"    {name:<{col}}{DIM}{help_text}{RESET}")

    # Build usage line
    usage_parts = [parser.prog]
    if subcommands:
        usage_parts.append("<command>")
    if optionals:
        usage_parts.append("[options]")
    for action in positionals:
        name = action.metavar or action.dest
        if action.nargs in ("?", "*"):
            usage_parts.append(f"[{name}]")
        elif action.nargs == "+":
            usage_parts.append(f"<{name}> [...]")
        else:
            usage_parts.append(f"<{name}>")

    lines.append("")
    lines.append(f"  {DIM}{'─' * 45}{RESET}")
    lines.append(f"  {DIM}{' '.join(usage_parts)}{RESET}")

    print("\n".join(lines))


def _sub_parser(sub, name, **kwargs):
    """Create a subparser with styled help instead of stock argparse help."""
    kwargs.setdefault("description", kwargs.get("help", ""))
    kwargs["add_help"] = False
    p = sub.add_parser(name, **kwargs)
    p.add_argument("-h", "--help", action=_StyledHelpAction, help=argparse.SUPPRESS)
    return p


def _print_help() -> None:
    from husks.utils.console import BOLD, DIM, CYAN, RESET, render_banner

    ver = _get_version()

    logo = render_banner("hydrating", [
        f"{BOLD}husks{RESET} {DIM}{ver}{RESET}",
        f"{DIM}A small build system for nondeterministic work.{RESET}",
        "",
        "",
        "",
    ])

    def _group(name: str) -> str:
        return f"\n  {BOLD}{name}{RESET}"

    def _cmd(name: str, desc: str) -> str:
        return f"    {name:<18s}{DIM}{desc}{RESET}"

    lines = [
        logo,
        _group("design"),
        _cmd("init", "Scaffold a new project"),
        _cmd("check", "Validate a design"),
        _group("build"),
        _cmd("run", "Execute a design into a site"),
        _cmd("status", "Inspect site state"),
        _cmd("cache export", "Export site cache for transfer"),
        _cmd("cache import", "Import cache into a site"),
        _group("verify"),
        _cmd("compare", "Equivalence across sites (three-machine proof with 3+)"),
        _cmd("doctor", "Diagnose the local environment"),
        _group("inspect"),
        _cmd("explain", "Navigate the residue tree"),
        _cmd("history", "Show convergence across runs"),
        "",
        f"  {DIM}{'─' * 45}{RESET}",
        f"  {DIM}--color <mode>   auto · always · never{RESET}",
        f"  {DIM}-q, --quiet      Suppress output{RESET}",
        f"  {DIM}--version        Print version{RESET}",
        "",
        f"  {DIM}husks <command> --help for details{RESET}",
    ]

    print("\n".join(lines))


def main():
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

    sub = p.add_subparsers(dest="cmd")

    # init
    i = _sub_parser(sub, "init", help="Scaffold a new project")
    i.add_argument("target", nargs="?", default=".",
                   help="Target directory (default: .)")
    i.add_argument("template", nargs="?", default="core-bootstrap",
                   help="Project template (default: core-bootstrap)")
    i.add_argument("--hy", action="store_true",
                   help="Also emit bootstrap.hy (Hy design equivalent)")
    i.add_argument("--force", action="store_true",
                   help="Overwrite existing files")
    i.add_argument("--verbose", "-v", action="store_true",
                   help="Show detailed scaffolding output")

    # check
    c = _sub_parser(sub, "check", help="Validate a design")
    c.add_argument("design", nargs="?", default=None,
                   help="Path to design file (.json or .hy). Defaults to design.json.")
    c.add_argument("--verbose", "-v", action="store_true",
                   help="Show full design details after validation (replaces old 'show')")
    c.add_argument("--json", action="store_true", dest="json_output",
                   help="Output categorized check results as JSON")

    # run
    r = _sub_parser(sub, "run", help="Execute a design into a site")
    r.add_argument("design", nargs="?", default=None,
                   help="Path to design file (.json or .hy). Defaults to design.json.")
    r.add_argument("--site", help="Override site directory")
    r.add_argument("--model", help="LLM model for oracle rules",
                   default="anthropic/claude-haiku-4-5-20251001")
    r.add_argument("--stub", action="store_true",
                   help="Use stub oracle (no LLM, placeholder outputs)")
    r.add_argument("--reuse-only", action="store_true",
                   help="Only use cached results, never call oracle (Beta Gate D5)")
    r.add_argument("--hy", action="store_true",
                   help="Use original Hy kernel backend instead of Python")
    r.add_argument("--json", action="store_true", dest="json_output",
                   help="Output full Report as JSON instead of text")
    r.add_argument("--soft-fail", action="store_true",
                   help="Exit 0 even when the build halts")
    r.add_argument("--verbose", "-v", action="store_true",
                   help="Verbose output (full trace + detailed report)")
    r.add_argument("--report-json", metavar="PATH",
                   help="Write JSON report to file (sidecar; may be used with --verbose)")

    # status
    st_cmd = _sub_parser(sub, "status", help="Inspect site state")
    st_cmd.add_argument("site", help="Site directory path")
    st_cmd.add_argument("--verbose", action="store_true",
                        help="Show detailed DAG with freshness states")
    st_cmd.add_argument("--json", action="store_true", dest="json_output",
                        help="Output as JSON")
    st_cmd.add_argument("--fail-if-dirty", action="store_true",
                        help="Exit 4 if any artifact is modified")
    st_cmd.add_argument("--fail-if-stale", action="store_true",
                        help="Exit 4 if any rule is stale")

    # explain
    e = _sub_parser(sub, "explain", help="Navigate the residue tree")
    e.add_argument("subject", nargs="?", default=None,
                   help="Design file path (.json/.hy), or rule/artifact name")
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
    h = _sub_parser(sub, "history", help="Show convergence across runs")
    h.add_argument("design", nargs="?", default=None,
                   help="Path to design file (.json or .hy). Defaults to design.json.")
    h.add_argument("rule", nargs="?", default=None,
                   help="Rule name (omit for summary of all rules)")
    h.add_argument("--site", help="Override site directory")
    h.add_argument("-n", type=int, default=5,
                   help="Number of recent entries to show (default: 5)")

    # doctor
    doc = _sub_parser(sub, "doctor", help="Diagnose the local environment")
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
    doc.add_argument("--verbose", "-v", action="store_true",
                     help="Verbose output")

    # compare (Beta Gate C6/C7)
    cmp = _sub_parser(sub, "compare", help="Equivalence across sites (three-machine proof with 3+)")
    cmp.add_argument("sites", nargs="+",
                     help="Site directories to compare (2 or more)")
    cmp.add_argument("--json", action="store_true", dest="json_output",
                     help="Output comparison result as JSON")
    cmp.add_argument("--roots-only", action="store_true",
                     help="Compare build roots only (skip output hash checks)")
    cmp.add_argument("--hashes-only", action="store_true",
                     help="Compare output hashes only (skip root checks)")

    # cache (Beta Gate G1/D5) - nested subcommands
    cache_parser = _sub_parser(sub, "cache", help="Cache management commands")
    cache_sub = cache_parser.add_subparsers(dest="cache_cmd", required=True)

    # cache export
    cache_exp = _sub_parser(cache_sub, "export", help="Pack site cache for transfer")
    cache_exp.add_argument("file", help="Path to write .tar.gz archive")
    cache_exp.add_argument("--site", required=True, help="Site directory containing cache")
    cache_exp.add_argument("--json", action="store_true", dest="json_output",
                           help="Output result as JSON")

    # cache import
    cache_imp = _sub_parser(cache_sub, "import", help="Unpack cache into a site")
    cache_imp.add_argument("file", help="Path to .tar.gz archive")
    cache_imp.add_argument("--site", required=True, help="Site directory to import into")
    cache_imp.add_argument("--no-merge", action="store_true",
                           help="Clear existing cache before import (default: merge)")
    cache_imp.add_argument("--json", action="store_true", dest="json_output",
                           help="Output result as JSON")

    args = p.parse_args()

    # --help / -h
    if args.help:
        _print_help()
        sys.exit(EXIT_OK)

    # --version
    if args.version:
        print(f"husks {_get_version()}")
        sys.exit(EXIT_OK)

    if args.cmd is None:
        _print_help()
        sys.exit(EXIT_USAGE)

    # Validate mutually exclusive flags
    if args.cmd in ("run", "check"):
        verbose = getattr(args, 'verbose', False)
        json_output = getattr(args, 'json_output', False)
        if verbose and json_output:
            print("error: --verbose and --json are mutually exclusive", file=sys.stderr)
            sys.exit(EXIT_USAGE)

    # ── init ──────────────────────────────────────────────────
    if args.cmd == "init":
        from husks.setup import init
        emit_hy = getattr(args, 'hy', False)
        verbose = getattr(args, 'verbose', False)
        sys.exit(init(args.target, template=args.template, emit_hy=emit_hy, claude_code=True, force=args.force, verbose=verbose))

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
    is_hy = design_path.endswith(".hy")

    if args.cmd == "run" and is_hy:
        _cmd_run_hy(args)
        return

    if is_hy:
        print(f"error: '{args.cmd}' does not support .hy designs (only 'run' does)",
              file=sys.stderr)
        sys.exit(EXIT_USAGE)

    # Beta Gate F/G: Catch design loading errors and emit JSON when --json specified
    try:
        design = from_json(design_path)
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
        # Blocker #3: run requires --site at CLI layer
        if not args.site:
            print("error: run requires --site", file=sys.stderr)
            sys.exit(EXIT_USAGE)
        _cmd_run(args, design)

    elif args.cmd == "history":
        _cmd_history(args, design)


if __name__ == "__main__":
    main()
