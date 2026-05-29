"""All _cmd_* command functions."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from husks.designs.ir import check, check_categorized, show, run
from husks.cli.helpers import EXIT_OK, EXIT_BUILD_FAIL, EXIT_USAGE, EXIT_MISSING_DEP


# ── run (Hy) ──────────────────────────────────────────────────────────

def _cmd_run_hy(args):
    """Execute a .hy design file directly."""
    design_path = str(Path(args.design).resolve())

    # Suppress console trace in JSON mode or non-verbose default mode
    if args.json_output or not args.verbose:
        from husks.utils import trace as T_pre
        T_pre.clear_listeners()

    # Configure oracle backend before executing the .hy file
    if args.stub:
        # Replace live_oracle in the module so the .hy file picks up the stub
        import husks.oracle as _omod
        from husks.build.eval import default_oracle_backend
        _omod.live_oracle = default_oracle_backend
    else:
        from husks.oracle import set_oracle_model
        set_oracle_model(args.model)

    # Execute the .hy design
    try:
        import hy  # noqa: F401
        import runpy
        runpy.run_path(design_path, run_name="__main__")
    except ImportError:
        print("error: hy is not installed (pip install hy)", file=sys.stderr)
        sys.exit(EXIT_MISSING_DEP)
    except Exception as e:
        print(f"error: {e}", file=sys.stderr)
        sys.exit(EXIT_BUILD_FAIL)

    # Retrieve the Store captured by build()
    import husks.build.run as _brun
    S = _brun._last_store
    if S is None:
        print("error: .hy design did not call build()", file=sys.stderr)
        sys.exit(EXIT_BUILD_FAIL)

    # Build Report
    from husks.report import assemble, render_text, render_concise, render_json
    from husks.utils import trace as T

    report = assemble(S, T, {})
    if args.json_output:
        print(render_json(report))
    elif args.verbose:
        print(render_text(report))
    else:
        print(render_concise(report))

    if S.get("status") == "halted" and not args.soft_fail:
        sys.exit(EXIT_BUILD_FAIL)


# ── check ─────────────────────────────────────────────────────────

def _cmd_check(args, design):
    if args.json_output:
        result = check_categorized(design)
        print(json.dumps(result, indent=2))
        sys.exit(EXIT_OK if result["ok"] else EXIT_BUILD_FAIL)

    if args.verbose:
        # Validate then show full design details
        errs = check(design)
        if errs:
            print("warnings:", file=sys.stderr)
            for e in errs:
                print(f"  - {e}", file=sys.stderr)
        show(design)
        if errs:
            sys.exit(EXIT_BUILD_FAIL)
    else:
        # Structured per-category output
        result = check_categorized(design)
        for cat_name, cat in result["categories"].items():
            sym = "\u2713" if cat["ok"] else "\u2717"
            print(f"  {sym} {cat_name}")
            for err in cat["errors"]:
                print(f"    {err}")
        if result["ok"]:
            print("\nok")
        else:
            sys.exit(EXIT_BUILD_FAIL)


# ── run ───────────────────────────────────────────────────────────

def _cmd_run(args, design):
    """Run a design, producing JSON error output on setup/validation failures when --json specified."""
    overrides = {}
    if args.site:
        overrides["site"] = args.site

    # Beta Gate D5: Pass reuse-only flag
    if args.reuse_only:
        overrides["cache_reuse_only"] = True

    if not args.stub:
        if args.hy:
            from husks.designs.hy import hy_kernel_backend
            kern = hy_kernel_backend()
            kern["set_oracle_model"](args.model)
            overrides["oracle_backend"] = kern["live_oracle"]
        else:
            from husks.oracle import live_oracle, set_oracle_model
            set_oracle_model(args.model)
            overrides["oracle_backend"] = live_oracle
        overrides["oracle_model"] = args.model

    # Suppress console trace in JSON mode or non-verbose default mode
    if args.json_output or not args.verbose:
        from husks.utils import trace as T_pre
        T_pre.clear_listeners()

    # Beta Gate F/G: Catch setup/validation failures and emit JSON errors when --json specified
    try:
        S = run(design, **overrides)
    except ValueError as e:
        # Design validation, missing site_inputs, reuse-only cache miss, etc.
        if args.json_output:
            error_report = {
                "status": "error",
                "error_type": "setup_failure",
                "error": str(e),
                "build": design.get("name", "unknown"),
                "site": overrides.get("site") or design.get("site", "unknown"),
            }
            print(json.dumps(error_report, indent=2))
        else:
            print(f"error: {e}", file=sys.stderr)
        sys.exit(EXIT_BUILD_FAIL)
    except FileNotFoundError as e:
        # Missing files, site directories, etc.
        if args.json_output:
            error_report = {
                "status": "error",
                "error_type": "file_not_found",
                "error": str(e),
                "build": design.get("name", "unknown"),
            }
            print(json.dumps(error_report, indent=2))
        else:
            print(f"error: {e}", file=sys.stderr)
        sys.exit(EXIT_BUILD_FAIL)
    except Exception as e:
        # Unexpected errors
        if args.json_output:
            error_report = {
                "status": "error",
                "error_type": "unexpected",
                "error": str(e),
                "error_class": type(e).__name__,
                "build": design.get("name", "unknown"),
            }
            print(json.dumps(error_report, indent=2))
        else:
            print(f"error: {e}", file=sys.stderr)
        sys.exit(EXIT_BUILD_FAIL)

    # Build Report
    from husks.report import assemble, render_text, render_concise, render_json
    from husks.utils import trace as T

    report = assemble(S, T, design)
    if args.json_output:
        print(render_json(report))
    elif args.verbose:
        print(render_text(report))
    else:
        print(render_concise(report))

    if S.get("status") == "halted" and not args.soft_fail:
        sys.exit(EXIT_BUILD_FAIL)
