#- cli.py — command-line interface for Husks plans
#
# Usage:
#   python -m husks.cli check plan.json
#   python -m husks.cli show  plan.json
#   python -m husks.cli run   plan.json [--site /tmp/my-build] [--model ...]
#   python -m husks.cli run   plan.json --stub   (no LLM, placeholder outputs)

import argparse
import json
import sys

from husks.plan import check, show, run, from_json


def main():
    p = argparse.ArgumentParser(prog="husks", description="Husks plan CLI")
    sub = p.add_subparsers(dest="cmd")

    # check
    c = sub.add_parser("check", help="Validate a plan (exit 1 if errors)")
    c.add_argument("plan", help="Path to plan JSON file")

    # show
    s = sub.add_parser("show", help="Pretty-print a plan")
    s.add_argument("plan", help="Path to plan JSON file")

    # run
    r = sub.add_parser("run", help="Check, compile, and execute a plan")
    r.add_argument("plan", help="Path to plan JSON file")
    r.add_argument("--site", help="Override site directory")
    r.add_argument("--model", help="LLM model for oracle rules",
                   default="anthropic/claude-haiku-4-5-20251001")
    r.add_argument("--stub", action="store_true",
                   help="Use stub oracle (no LLM, placeholder outputs)")

    args = p.parse_args()

    if args.cmd is None:
        p.print_help()
        sys.exit(1)

    plan = from_json(args.plan)

    if args.cmd == "check":
        errs = check(plan)
        if errs:
            for e in errs:
                print(f"  error: {e}", file=sys.stderr)
            sys.exit(1)
        else:
            print("ok")

    elif args.cmd == "show":
        errs = check(plan)
        if errs:
            print("warnings:", file=sys.stderr)
            for e in errs:
                print(f"  - {e}", file=sys.stderr)
        show(plan)

    elif args.cmd == "run":
        overrides = {}
        if args.site:
            overrides["site"] = args.site

        if not args.stub:
            # live oracle: kernel + LLM
            import hy  # noqa: F401
            from husks.kernel import live_oracle, set_oracle_model
            set_oracle_model(args.model)
            overrides["oracle_backend"] = live_oracle
            overrides["oracle_model"] = args.model

        S = run(plan, **overrides)
        # summary
        print(json.dumps({
            "status": S["status"],
            "fuel_remaining": S["fuel"],
            "site": S["site"],
        }, indent=2))


if __name__ == "__main__":
    main()
