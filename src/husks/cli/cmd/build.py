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

    Maps all rules to 'unrealized' state since no execution has happened.
    Builds target-rooted tree from dependencies.
    """
    rules = design.get("rules", [])
    rules_by_name = {r["name"]: r for r in rules}

    # Build dependency map (rule -> inputs it depends on)
    deps = {}
    for rule in rules:
        rule_inputs = set(rule.get("inputs", []))
        deps[rule["name"]] = []
        # Find rules that produce these inputs
        for other in rules:
            other_outputs = set(other.get("outputs", []))
            if rule_inputs & other_outputs:  # Intersection
                deps[rule["name"]].append(other["name"])

    # Build nodes with children
    nodes = []
    for rule in rules:
        node = CliNode(
            name=rule["name"],
            kind=rule.get("kind", "action"),
            state="unrealized",  # All nodes are unrealized in check mode
            children=deps.get(rule["name"], []),
            fuel_budget=rule.get("fuel"),
        )
        nodes.append(node)

    # Reorder: target first, then dependencies
    target_name = design.get("target") or design.get("targets", [None])[0]
    if target_name:
        target_idx = next((i for i, n in enumerate(nodes) if n.name == target_name), 0)
        if target_idx > 0:
            nodes.insert(0, nodes.pop(target_idx))

    # Beta 100: Add cse_path and target
    target_name = design.get("target") or design.get("targets", [None])[0]

    return CliResidue(
        command="check",
        design_name=design.get("name", "unknown"),
        site=None,
        cse_path="none",  # No CSE for dry check
        status="dry",  # Internal status (mapped to "checked" in view)
        target=target_name,
        fuel_budget=design.get("fuel", 0),
        nodes=nodes,
        passes=["checks"],
        fails=[],
    )


def collect_hydrated_residue(S: dict, T, design: dict) -> CliResidue:
    """Collect hydrated residue from a completed build run.

    Extracts node facts from Store (S), Trace (T), and usage data.
    Maps trace events to unified state vocabulary.
    Builds target-rooted tree.

    Beta 100: Adds cse_path, target, outputs with hashes, and trace info.
    """
    from husks.cli.residue import map_trace_state, CliOutput, CliTrace

    rules = design.get("rules", [])
    rules_by_name = {r["name"]: r for r in rules}
    usage = S.get("usage", {})
    by_rule = usage.get("by_rule", {})

    # Build dependency map
    deps = {}
    for rule in rules:
        rule_inputs = set(rule.get("inputs", []))
        deps[rule["name"]] = []
        for other in rules:
            other_outputs = set(other.get("outputs", []))
            if rule_inputs & other_outputs:
                deps[rule["name"]].append(other["name"])

    # Build trace event lookup from _node_events
    # _node_events is a list of tuples: (name, status, elapsed)
    # where status is "fired", "reused", or "failed"
    trace_events = {}
    for name, status, elapsed in T._node_events:
        trace_events[name] = {
            "status": status,
            "elapsed": elapsed,
        }

    nodes = []
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

        # Beta 100: Collect outputs with hashes
        outputs = []
        for output_path in rule.get("outputs", []):
            output_hash = None
            for artifact_path, artifact_info in T._artifacts.items():
                if artifact_path == output_path:
                    output_hash = artifact_info.get("hash")
                    break
            outputs.append(CliOutput(path=output_path, sha256=output_hash))

        # Keep legacy output_hash for compatibility (first output)
        output_hash = outputs[0].sha256 if outputs else None

        # Extract duration
        duration = event["elapsed"] if event else None

        # Extract diagnosis (from general events for halted rules)
        diagnosis = None
        if state == "failed":
            for evt in T._events:
                if evt.get("event") == "rule_halted" and evt.get("rule") == rule_name:
                    diagnosis = evt.get("reason")
                    break

        # Beta 100: Build trace info for oracle/action nodes
        trace = None
        if rule_usage:
            trace = CliTrace(
                backend=rule_usage.get("backend", "unknown"),
                model=rule_usage.get("model"),
                input_tokens=rule_usage.get("tokens_in", 0),
                output_tokens=rule_usage.get("tokens_out", 0),
                elapsed_s=duration,
                cost_usd=rule_usage.get("cost_usd", 0.0),
                cache_source="local" if cached else None,
            )

        node = CliNode(
            name=rule_name,
            kind=rule.get("kind", "action"),
            state=state,
            children=deps.get(rule_name, []),
            fuel=rule_usage.get("fuel_consumed"),
            fuel_budget=rule.get("fuel"),
            cost=rule_usage.get("cost_usd"),
            cache=cached,
            output_hash=output_hash,
            duration=duration,
            diagnosis=diagnosis,
            outputs=outputs,
            trace=trace,
        )
        nodes.append(node)

    # Reorder: target first
    target_name = design.get("target") or design.get("targets", [None])[0]
    if target_name:
        target_idx = next((i for i, n in enumerate(nodes) if n.name == target_name), 0)
        if target_idx > 0:
            nodes.insert(0, nodes.pop(target_idx))

    # Compute summary categories
    has_cached = any(n.cache for n in nodes)
    has_failed = any(n.state == "failed" for n in nodes)

    passes = []
    fails = []

    if not has_failed:
        passes.append("run")
    else:
        fails.append("run")

    if has_cached:
        passes.append("cache")

    # Beta 100: Find CSE husk path
    design_name = design.get("name", "unknown")
    cse_path = f"{design_name}.husk"  # Standard naming
    target_name = design.get("target") or design.get("targets", [None])[0]

    return CliResidue(
        command="run",
        design_name=design_name,
        site=S.get("site"),
        cse_path=cse_path,
        status=S.get("status", "unknown"),
        root=S.get("root"),
        target=target_name,
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

    # Suppress console trace (we use residue→surface→view instead)
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

    # Suppress console trace (we use residue→surface→view instead)
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
    from husks.utils import trace as T

    # Beta 100: For --json, use full report schema (compare-runs compatible)
    # For visual output, use residue→surface→view architecture
    if args.json_output:
        from husks.report import assemble, render_json
        report = assemble(S, T, design)
        print(render_json(report))
    else:
        # Visual output: use residue→surface→view
        from husks.cli.surface import emit_residue
        residue = collect_hydrated_residue(S, T, design)
        output = emit_residue(residue, json_mode=False, verbose=args.verbose)
        print(output)

    # Preserve exit code logic
    if S.get("status") == "halted" and not args.soft_fail:
        sys.exit(EXIT_BUILD_FAIL)
