"""Argparse and dispatch."""

import argparse
import sys

from husks.designs.ir import from_json

from husks.cli.helpers import EXIT_OK, EXIT_BUILD_FAIL, EXIT_USAGE
from husks.cli.commands import (
    _cmd_check, _cmd_run, _cmd_run_hy, _cmd_status, _cmd_diff,
    _cmd_explain, _cmd_graph, _cmd_history, _cmd_gate, _cmd_doctor,
)


def main():
    p = argparse.ArgumentParser(prog="husks", description="Husks design CLI")

    # Global options
    p.add_argument("--color", choices=["auto", "always", "never"], default="auto",
                   help="Color output mode")
    p.add_argument("--quiet", "-q", action="store_true",
                   help="Suppress non-essential output")
    p.add_argument("--version", action="store_true",
                   help="Print version and exit")

    sub = p.add_subparsers(dest="cmd")

    # check
    c = sub.add_parser("check", help="Validate a design (exit 1 if errors)")
    c.add_argument("design", help="Path to design file (.json or .hy)")
    c.add_argument("--verbose", "-v", action="store_true",
                   help="Show full design details after validation (replaces old 'show')")
    c.add_argument("--json", action="store_true", dest="json_output",
                   help="Output categorized check results as JSON")

    # run
    r = sub.add_parser("run", help="Check, compile, and execute a design")
    r.add_argument("design", help="Path to design file (.json or .hy)")
    r.add_argument("--site", help="Override site directory")
    r.add_argument("--model", help="LLM model for oracle rules",
                   default="anthropic/claude-haiku-4-5-20251001")
    r.add_argument("--stub", action="store_true",
                   help="Use stub oracle (no LLM, placeholder outputs)")
    r.add_argument("--hy", action="store_true",
                   help="Use original Hy kernel backend instead of Python")
    r.add_argument("--json", action="store_true", dest="json_output",
                   help="Output full Report as JSON instead of text")
    r.add_argument("--soft-fail", action="store_true",
                   help="Exit 0 even when the build halts")
    r.add_argument("--verbose", "-v", action="store_true",
                   help="Verbose output (full trace + detailed report)")

    # status
    st_cmd = sub.add_parser("status", help="Show freshness state of a built site")
    st_cmd.add_argument("design", nargs="?", default=None,
                        help="Path to design JSON file (optional)")
    st_cmd.add_argument("--site", help="Site directory")
    st_cmd.add_argument("--json", action="store_true", dest="json_output",
                        help="Output as JSON")
    st_cmd.add_argument("--fail-if-dirty", action="store_true",
                        help="Exit 4 if any artifact is modified")
    st_cmd.add_argument("--fail-if-stale", action="store_true",
                        help="Exit 4 if any rule is stale")

    # diff
    d = sub.add_parser("diff", help="Show differences between sealed and current artifacts")
    d.add_argument("design", nargs="?", default=None,
                   help="Path to design JSON file (optional)")
    d.add_argument("artifact", nargs="*", default=[],
                   help="Specific artifacts to diff (default: all)")
    d.add_argument("--site", help="Site directory")
    d.add_argument("--json", action="store_true", dest="json_output",
                   help="Output as JSON")

    # explain
    e = sub.add_parser("explain", help="Explain a rule or artifact")
    e.add_argument("subject", help="Rule name or artifact path")
    e.add_argument("--site", help="Site directory (required)")
    e.add_argument("--json", action="store_true", dest="json_output",
                   help="Output as JSON")

    # graph
    g = sub.add_parser("graph", help="Render the dependency graph")
    g.add_argument("design", help="Path to design file (.json or .hy)")
    g.add_argument("--format", choices=["text", "mermaid", "dot", "json"],
                   default="text", dest="graph_format",
                   help="Output format (default: text)")
    g.add_argument("--site", help="Site directory (for freshness overlay)")

    # history
    h = sub.add_parser("history", help="Show convergence history for rules")
    h.add_argument("design", help="Path to design file (.json or .hy)")
    h.add_argument("rule", nargs="?", default=None,
                   help="Rule name (omit for summary of all rules)")
    h.add_argument("--site", help="Override site directory")
    h.add_argument("-n", type=int, default=5,
                   help="Number of recent entries to show (default: 5)")

    # gate
    gt = sub.add_parser("gate", help="Run the conformance gate against a CSE reader")
    gt.add_argument("reader_cmd", help='Reader command, e.g. "python my_reader.py"')
    gt.add_argument("--stamp-dir", default=None,
                    help="Write VERIFIED stamp here on pass")
    gt.add_argument("--no-cross-check", action="store_false", dest="cross_check",
                    help="Disable JS cross-check")
    gt.add_argument("--json", action="store_true", dest="json_output",
                    help="Output as JSON")
    gt.add_argument("--verbose", "-v", action="store_true",
                    help="Verbose output")

    # doctor
    doc = sub.add_parser("doctor", help="Check environment and dependencies")
    doc.add_argument("--json", action="store_true", dest="json_output",
                     help="Output as JSON")

    # selftest
    st = sub.add_parser("selftest", help="Verify engine against frozen conformance vectors")
    st.add_argument("--conformance", help="Path to conformance vector directory")

    # init
    i = sub.add_parser("init", help="Wire a project to drive Husks from Claude Code")
    i.add_argument("target", nargs="?", default=".",
                   help="Target directory (default: .)")
    i.add_argument("--no-claude-code", action="store_true",
                   help="Skip Claude Code skill hookup")
    i.add_argument("--force", action="store_true",
                   help="Overwrite existing skill symlink and CLAUDE.md")

    args = p.parse_args()

    # --version
    if args.version:
        try:
            from importlib.metadata import version as pkg_version
            print(f"husks {pkg_version('husks')}")
        except Exception:
            print("husks (version unknown)")
        sys.exit(EXIT_OK)

    if args.cmd is None:
        p.print_help()
        sys.exit(EXIT_USAGE)

    # ── Commands that take no design file ─────────────────────
    if args.cmd == "selftest":
        from husks.setup import selftest
        sys.exit(EXIT_OK if selftest(conformance=args.conformance) else EXIT_BUILD_FAIL)

    if args.cmd == "init":
        from husks.setup import init
        sys.exit(init(args.target, claude_code=not args.no_claude_code, force=args.force))

    if args.cmd == "doctor":
        _cmd_doctor(args)
        return

    if args.cmd == "gate":
        _cmd_gate(args)
        return

    # ── Commands that may or may not need a design ────────────
    if args.cmd == "status":
        _cmd_status(args)
        return

    if args.cmd == "diff":
        _cmd_diff(args)
        return

    if args.cmd == "explain":
        _cmd_explain(args)
        return

    # ── Commands that require a design ────────────────────────
    design_path = args.design
    is_hy = design_path.endswith(".hy")

    if args.cmd == "run" and is_hy:
        _cmd_run_hy(args)
        return

    if is_hy:
        print(f"error: '{args.cmd}' does not support .hy designs (only 'run' does)",
              file=sys.stderr)
        sys.exit(EXIT_USAGE)

    design = from_json(design_path)

    if args.cmd == "check":
        _cmd_check(args, design)

    elif args.cmd == "run":
        _cmd_run(args, design)

    elif args.cmd == "graph":
        _cmd_graph(args, design)

    elif args.cmd == "history":
        _cmd_history(args, design)


if __name__ == "__main__":
    main()
