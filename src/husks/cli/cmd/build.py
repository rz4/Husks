"""All _cmd_* command functions."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from husks.designs.ir import check, check_categorized, show, run
from husks.cli.helpers import EXIT_OK, EXIT_BUILD_FAIL, EXIT_USAGE, EXIT_MISSING_DEP
from husks.cli.residue import CliResidue, CliNode


# ── Residue collectors (Beta Gate 95) ────────────────────────────────

def collect_dry_residue(design: dict) -> CliResidue:
    """Collect dry residue for check command (design without site).

    Maps all rules to 'dry' state since no execution has happened.
    """
    nodes = []
    rules = design.get("rules", [])

    for rule in rules:
        node = CliNode(
            name=rule["name"],
            kind=rule.get("kind", "action"),
            state="dry",  # All nodes are dry in check mode
        )
        nodes.append(node)

    return CliResidue(
        command="check",
        design_name=design.get("name", "unknown"),
        site=None,
        status="dry",
        fuel_budget=design.get("fuel", 0),
        nodes=nodes,
    )


def collect_hydrated_residue(S: dict, T, design: dict) -> CliResidue:
    """Collect hydrated residue from a completed build run.

    Extracts node facts from Store (S), Trace (T), and usage data.
    Maps trace events to unified state vocabulary.
    """
    from husks.cli.residue import map_trace_state

    nodes = []
    rules = design.get("rules", [])
    usage = S.get("usage", {})
    by_rule = usage.get("by_rule", {})

    # Build trace event lookup from _node_events
    # _node_events is a list of tuples: (name, status, elapsed)
    # where status is "fired", "reused", or "failed"
    trace_events = {}
    for name, status, elapsed in T._node_events:
        trace_events[name] = {
            "status": status,
            "elapsed": elapsed,
        }

    for rule in rules:
        rule_name = rule["name"]
        rule_usage = by_rule.get(rule_name, {})
        event = trace_events.get(rule_name)

        # Determine state from trace event
        if event:
            trace_status = event["status"]
            # Check if node was cached (from usage data OR reused status)
            cached = rule_usage.get("cached", False) or (trace_status == "reused")

            # Map trace status to CLI state
            if trace_status == "failed":
                state = "failed"
            elif trace_status == "reused" or cached:
                state = "cached"
            elif trace_status == "fired":
                state = "sealed"
            else:
                state = "dry"
        else:
            state = "dry"  # Never executed
            cached = False

        # Extract output hash from artifacts
        output_hash = None
        if rule.get("outputs"):
            first_output = rule["outputs"][0]
            for output_path, artifact_info in T._artifacts.items():
                if output_path == first_output:
                    output_hash = artifact_info.get("hash")
                    break

        # Extract duration
        duration = event["elapsed"] if event else None

        # Extract diagnosis (from general events for halted rules)
        diagnosis = None
        if state == "failed":
            for evt in T._events:
                if evt.get("event") == "rule_halted" and evt.get("rule") == rule_name:
                    diagnosis = evt.get("reason")
                    break

        node = CliNode(
            name=rule_name,
            kind=rule.get("kind", "action"),
            state=state,
            fuel=rule_usage.get("fuel_consumed"),
            cost=rule_usage.get("cost_usd"),
            cache=cached,
            output_hash=output_hash,
            duration=duration,
            diagnosis=diagnosis,
        )
        nodes.append(node)

    # Compute summary
    passes = sum(1 for n in nodes if n.state in ("sealed", "cached"))
    fails = sum(1 for n in nodes if n.state == "failed")

    return CliResidue(
        command="run",
        design_name=design.get("name", "unknown"),
        site=S.get("site"),
        status=S.get("status", "unknown"),
        root=S.get("root"),
        fuel_budget=design.get("fuel", 0),
        fuel_used=design.get("fuel", 0) - S.get("fuel", 0),
        cost=usage.get("total_cost_usd", 0.0),
        nodes=nodes,
        passes=passes,
        fails=fails,
    )


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
    """Check command - validate design and optionally overlay site states.

    Beta Gate 95: Uses residue→surface→view architecture.
    """
    from husks.cli.surface import emit_residue
    from husks.cli.residue import map_manifest_state

    # Step 1: Validate design (keep existing validation logic)
    result = check_categorized(design)
    if not result["ok"]:
        # Validation failed - show errors in old format (not yet residue-based)
        if args.json_output:
            print(json.dumps(result, indent=2))
        else:
            for cat_name, cat in result["categories"].items():
                sym = "\u2713" if cat["ok"] else "\u2717"
                print(f"  {sym} {cat_name}")
                for err in cat["errors"]:
                    print(f"    {err}")
        sys.exit(EXIT_BUILD_FAIL)

    # Step 2: Validation passed - collect dry residue
    residue = collect_dry_residue(design)

    # Step 3: If --site provided, overlay freshness states from manifest
    site = getattr(args, 'site', None)
    if site:
        try:
            from husks.manifest import read_manifest, compute_rule_states
            manifest = read_manifest(site)
            if manifest:
                rule_states = compute_rule_states(site, manifest)
                # Update residue nodes with manifest states
                state_by_name = {rs["name"]: rs for rs in rule_states}
                for node in residue.nodes:
                    if node.name in state_by_name:
                        rs = state_by_name[node.name]
                        node.state = map_manifest_state(rs["state"])
                        node.stale_reason = rs.get("reason")
                # Update residue metadata
                residue.site = site
                residue.root = manifest.get("root")
                residue.status = "committed" if manifest.get("root") else "dry"
                # Update summary
                residue.passes = sum(1 for n in residue.nodes if n.state == "sealed")
                residue.fails = sum(1 for n in residue.nodes if n.state in ("stale", "failed"))
        except Exception:
            # Site not built or manifest missing - keep dry states
            pass

    # Step 4: Emit via surface layer
    output = emit_residue(residue, json_mode=args.json_output, verbose=args.verbose)
    print(output)

    # Exit with appropriate code
    sys.exit(EXIT_OK)


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

    # Build Report - Beta Gate 95: Use residue→surface→view architecture
    from husks.cli.surface import emit_residue
    from husks.utils import trace as T

    # Collect hydrated residue from completed build
    residue = collect_hydrated_residue(S, T, design)

    # Emit via surface layer
    output = emit_residue(residue, json_mode=args.json_output, verbose=args.verbose)
    print(output)

    # Preserve exit code logic
    if S.get("status") == "halted" and not args.soft_fail:
        sys.exit(EXIT_BUILD_FAIL)
