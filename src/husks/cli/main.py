"""Argparse and dispatch."""

import argparse
import sys

from husks.designs.ir import from_json

from husks.cli.helpers import EXIT_OK, EXIT_BUILD_FAIL, EXIT_USAGE, resolve_design
from husks.cli.commands import (
    _cmd_check, _cmd_run, _cmd_run_hy, _cmd_status,
    _cmd_explain, _cmd_history, _cmd_doctor,
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

    # init
    i = sub.add_parser("init", help="Create a runnable Husks project")
    i.add_argument("target", nargs="?", default=".",
                   help="Target directory (default: .)")
    i.add_argument("template", nargs="?", default="demo",
                   help="Project template (default: demo)")
    i.add_argument("--force", action="store_true",
                   help="Overwrite existing files")

    # check
    c = sub.add_parser("check", help="Validate a design (exit 1 if errors)")
    c.add_argument("design", nargs="?", default=None,
                   help="Path to design file (.json or .hy). Defaults to design.json.")
    c.add_argument("--verbose", "-v", action="store_true",
                   help="Show full design details after validation (replaces old 'show')")
    c.add_argument("--json", action="store_true", dest="json_output",
                   help="Output categorized check results as JSON")

    # run
    r = sub.add_parser("run", help="Check, compile, and execute a design")
    r.add_argument("design", nargs="?", default=None,
                   help="Path to design file (.json or .hy). Defaults to design.json.")
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

    # explain
    e = sub.add_parser("explain", help="Explain a rule, artifact, graph, diff, or seal")
    e.add_argument("subject", nargs="?", default=None,
                   help="Rule name or artifact path")
    e.add_argument("--graph", action="store_true",
                   help="Render the dependency graph")
    e.add_argument("--diff", action="store_true",
                   help="Show differences between sealed and current artifacts")
    e.add_argument("--seal", metavar="SUBJECT",
                   help="Show seal material for a rule, artifact, or root")
    e.add_argument("--format", choices=["text", "mermaid", "dot", "json"],
                   default="text", dest="graph_format",
                   help="Output format for --graph (default: text)")
    e.add_argument("design", nargs="?", default=None,
                   help="Design file (used with --graph)")
    e.add_argument("artifact", nargs="*", default=[],
                   help="Specific artifacts to diff (used with --diff)")
    e.add_argument("--site", help="Site directory")
    e.add_argument("--json", action="store_true", dest="json_output",
                   help="Output as JSON")

    # history
    h = sub.add_parser("history", help="Show convergence history for rules")
    h.add_argument("design", nargs="?", default=None,
                   help="Path to design file (.json or .hy). Defaults to design.json.")
    h.add_argument("rule", nargs="?", default=None,
                   help="Rule name (omit for summary of all rules)")
    h.add_argument("--site", help="Override site directory")
    h.add_argument("-n", type=int, default=5,
                   help="Number of recent entries to show (default: 5)")

    # doctor
    doc = sub.add_parser("doctor", help="Diagnose the local environment")
    doc.add_argument("--json", action="store_true", dest="json_output",
                     help="Output as JSON")
    doc.add_argument("--selftest", action="store_true",
                     help="Run frozen conformance vectors")
    doc.add_argument("--conformance", action="store_true",
                     help="Run external reader conformance gate")
    doc.add_argument("--live", action="store_true",
                     help="Check live oracle readiness (API key + test call)")
    doc.add_argument("--reader", dest="reader_cmd", default=None,
                     help='Reader command for --conformance, e.g. "python my_reader.py"')
    doc.add_argument("--stamp-dir", default=None,
                     help="Write VERIFIED stamp here on conformance pass")
    doc.add_argument("--no-cross-check", action="store_false", dest="cross_check",
                     help="Disable JS cross-check (with --conformance)")
    doc.add_argument("--verbose", "-v", action="store_true",
                     help="Verbose output")

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

    # ── init ──────────────────────────────────────────────────
    if args.cmd == "init":
        from husks.setup import init
        sys.exit(init(args.target, template=args.template, claude_code=True, force=args.force))

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

    design = from_json(design_path)

    if args.cmd == "check":
        _cmd_check(args, design)

    elif args.cmd == "run":
        _cmd_run(args, design)

    elif args.cmd == "history":
        _cmd_history(args, design)


if __name__ == "__main__":
    main()
