#- cli.py — command-line interface for Husks designs
#
# Usage:
#   python -m husks check design.json
#   python -m husks show  design.json
#   python -m husks run   design.json [--site /tmp/my-build] [--model ...]
#   python -m husks run   design.json --stub   (no LLM, placeholder outputs)
#   python -m husks run   design.json --hy     (use original Hy backend)

import argparse
import json
import sys
from pathlib import Path

from husks.designs.ir import check, show, run, from_json
from husks.designs.convergence import read_history, convergence_summary
from husks.utils.console import _shorthash


def main():
    p = argparse.ArgumentParser(prog="husks", description="Husks design CLI")
    sub = p.add_subparsers(dest="cmd")

    # check
    c = sub.add_parser("check", help="Validate a design (exit 1 if errors)")
    c.add_argument("design", help="Path to design JSON file")

    # show
    s = sub.add_parser("show", help="Pretty-print a design")
    s.add_argument("design", help="Path to design JSON file")

    # run
    r = sub.add_parser("run", help="Check, compile, and execute a design")
    r.add_argument("design", help="Path to design JSON file")
    r.add_argument("--site", help="Override site directory")
    r.add_argument("--model", help="LLM model for oracle rules",
                   default="anthropic/claude-haiku-4-5-20251001")
    r.add_argument("--stub", action="store_true",
                   help="Use stub oracle (no LLM, placeholder outputs)")
    r.add_argument("--hy", action="store_true",
                   help="Use original Hy kernel backend instead of Python")
    r.add_argument("--json", action="store_true", dest="json_output",
                   help="Output full Report as JSON instead of text")

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

    # history
    h = sub.add_parser("history", help="Show convergence history for rules")
    h.add_argument("design", help="Path to design JSON file")
    h.add_argument("rule", nargs="?", default=None,
                   help="Rule name (omit for summary of all rules)")
    h.add_argument("--site", help="Override site directory")
    h.add_argument("-n", type=int, default=5,
                   help="Number of recent entries to show (default: 5)")

    args = p.parse_args()

    if args.cmd is None:
        p.print_help()
        sys.exit(1)

    # commands that take no design file — dispatch before from_json()
    if args.cmd == "selftest":
        from husks.setup import selftest
        sys.exit(0 if selftest(conformance=args.conformance) else 1)

    if args.cmd == "init":
        from husks.setup import init
        sys.exit(init(args.target, claude_code=not args.no_claude_code, force=args.force))

    design = from_json(args.design)

    if args.cmd == "check":
        errs = check(design)
        if errs:
            for e in errs:
                print(f"  error: {e}", file=sys.stderr)
            sys.exit(1)
        else:
            print("ok")

    elif args.cmd == "show":
        errs = check(design)
        if errs:
            print("warnings:", file=sys.stderr)
            for e in errs:
                print(f"  - {e}", file=sys.stderr)
        show(design)

    elif args.cmd == "run":
        overrides = {}
        if args.site:
            overrides["site"] = args.site

        if not args.stub:
            if args.hy:
                # Hy kernel backend (original .hy files)
                from husks.designs.hy import hy_kernel_backend
                kern = hy_kernel_backend()
                kern["set_oracle_model"](args.model)
                overrides["oracle_backend"] = kern["live_oracle"]
            else:
                # Python kernel backend (default)
                from husks.oracle import live_oracle, set_oracle_model
                set_oracle_model(args.model)
                overrides["oracle_backend"] = live_oracle
            overrides["oracle_model"] = args.model

        S = run(design, **overrides)

        # Build Report
        from husks.report import assemble, render_text, render_json
        from husks.utils import trace as T
        from husks.oracle.llm import get_usage

        report = assemble(S, T, design, get_usage())
        if args.json_output:
            print(render_json(report))
        else:
            print(render_text(report))

    elif args.cmd == "history":
        site = args.site or design.get("site")
        if not site:
            print("error: no site directory. Use --site or set 'site' in design.",
                  file=sys.stderr)
            sys.exit(1)

        if args.rule:
            # detailed history for one rule
            entries = read_history(site, args.rule)
            if not entries:
                print(f"  no history for '{args.rule}' in {site}")
                sys.exit(0)
            recent = entries[-args.n:]
            print(f"\n  history: {args.rule}  ({len(entries)} total, showing last {len(recent)})")
            print(f"  {'─' * 72}")
            print(f"  {'run_id':<12s} {'fuel':>4s} {'prompt':>6s} {'sat':>5s} {'reads':>5s} {'output hash':<12s}")
            print(f"  {'─' * 72}")
            for e in recent:
                rid = e.get("run_id", "?")[:10]
                fuel = str(e.get("fuel_consumed", "?"))
                pl = e.get("prompt_length")
                prompt = str(pl) if pl is not None else "–"
                sat = e.get("satisfaction")
                sat_str = "true" if sat is True else ("false" if sat is False else "–")
                reads = str(len(e.get("traced_reads", [])))
                hashes = e.get("output_hashes", [])
                ohash = _shorthash(hashes[0]) if hashes else "–"
                print(f"  {rid:<12s} {fuel:>4s} {prompt:>6s} {sat_str:>5s} {reads:>5s} {ohash:<12s}")
            print(f"  {'─' * 72}")

            # convergence summary
            cs = convergence_summary(args.rule, site, n=args.n)
            print(f"\n  convergence: {cs['classification']}")
            if cs["fuel_trend"]:
                print(f"    fuel:   {cs['fuel_trend']}")
            if cs["prompt_trend"]:
                print(f"    prompt: {cs['prompt_trend']}")
            if cs["output_stable"] is not None:
                print(f"    output: {'stable' if cs['output_stable'] else 'varying'}")
            print()
        else:
            # summary for all rules
            rules = design.get("rules", [])
            print(f"\n  convergence history summary  (site: {site})")
            print(f"  {'─' * 60}")
            for r in rules:
                rname = r["name"]
                entries = read_history(site, rname)
                if not entries:
                    print(f"  {rname:<24s} no history")
                    continue
                n = min(args.n, len(entries))
                cs = convergence_summary(rname, site, n=n)
                print(f"  {rname:<24s} {len(entries)} runs  {cs['classification']}")
            print(f"  {'─' * 60}\n")


if __name__ == "__main__":
    main()
