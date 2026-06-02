"""All _cmd_* command functions."""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

from husks.designs.ir import check, check_categorized, show, run
from husks.cli.helpers import EXIT_OK, EXIT_BUILD_FAIL, EXIT_USAGE, EXIT_MISSING_DEP
from husks.cli.residue import CliResidue, CliNode
from husks.utils.console import is_tty, cursor_up, CLEAR_DOWN


# ── Live frame emitter ──────────────────────────────────────────────

class LiveFrameEmitter:
    """Live animated frame emitter for ``run``.

    Subscribes to trace events and maintains a lightweight snapshot of the
    DAG.  On each event the whole motif frame is re-rendered in-place (TTY)
    or key frames are printed sequentially (pipe).

    The emitter tracks per-node log lines (oracle prompt previews, token
    counts, tool calls) that are passed to ``render_dag`` via the
    ``log_lines`` parameter so they appear inline below the running node.
    """

    def __init__(self, design: dict, *, verbose: bool = False, site: str | None = None):
        self.design = design
        self.rules = {r["name"]: r for r in design.get("rules", [])}
        self.verbose = verbose
        self.site = site

        # Node tracking
        self.node_states: dict[str, str] = {
            r["name"]: "unrealized" for r in design.get("rules", [])
        }
        self.node_start_times: dict[str, float] = {}
        self.node_elapsed: dict[str, float] = {}

        # Per-node log lines shown below the running node
        self.log_lines: dict[str, list[str]] = {}

        # Oracle live tracking (for in-progress updates)
        self.oracle_start_times: dict[str, float] = {}
        self.oracle_tokens_in: dict[str, int] = {}
        self.oracle_tokens_out: dict[str, int] = {}

        # Build start time
        self.build_t0: float | None = None

        # Frame tracking for in-place overwrite
        self._last_frame_lines = 0
        self.is_tty = is_tty()

    def notify(self, event: dict) -> None:
        """Dispatch trace events (TraceListener protocol)."""
        etype = event.get("event")

        if etype == "build_start":
            self.build_t0 = time.time()
            self._emit_frame()

        elif etype == "rule_start":
            name = event.get("rule")
            if name and name in self.node_states:
                self.node_states[name] = "running"
                self.node_start_times[name] = time.time()
                self.log_lines[name] = []
                self._emit_frame()

        elif etype == "oracle_start":
            name = event.get("rule")
            if name and name in self.log_lines:
                # Track oracle start for live elapsed display
                self.oracle_start_times[name] = time.time()
                self.oracle_tokens_in[name] = 0
                self.oracle_tokens_out[name] = 0

                # Show prompt preview (truncated from right, not left)
                prompt = event.get("prompt_preview", "")
                if prompt:
                    short = prompt.replace("\n", " ")
                    if len(short) > 42:
                        short = short[:40] + ".."
                    self.log_lines[name].append(short)

                self._emit_frame()

        elif etype == "oracle_done":
            name = event.get("rule")
            if name and name in self.log_lines:
                ti = event.get("tokens_in", 0)
                to = event.get("tokens_out", 0)
                cost = event.get("cost_usd", 0.0)
                elapsed = event.get("elapsed", 0.0)

                # Update with final values
                parts = []
                if elapsed > 0:
                    parts.append(f"{elapsed:.2f}s")
                if ti or to:
                    parts.append(f"{ti} in")
                    parts.append(f"{to} out")
                if cost > 0:
                    parts.append(f"${cost:.4f}")
                if parts:
                    self.log_lines[name].append(" \u00b7 ".join(parts))

                # Clean up tracking
                self.oracle_start_times.pop(name, None)
                self.oracle_tokens_in.pop(name, None)
                self.oracle_tokens_out.pop(name, None)

                self._emit_frame()

        elif etype == "tool_call":
            name = event.get("rule")
            if name and name in self.log_lines:
                tool = event.get("tool", "?")
                # Show tool calls during oracle execution
                self.log_lines[name].append(f"\u2192 {tool}")
                self._emit_frame()

        elif etype == "tool_result":
            name = event.get("rule")
            if name and name in self.log_lines:
                preview = event.get("result_preview", "")
                if preview and self.verbose:
                    # Only show detailed results in verbose mode
                    short = preview[:50]
                    if len(preview) > 50:
                        short += ".."
                    self.log_lines[name].append(f"  {short}")
                self._emit_frame()

        elif etype == "rule_done":
            name = event.get("rule")
            if name and name in self.node_states:
                self.node_states[name] = "sealed"
                if name in self.node_start_times:
                    self.node_elapsed[name] = time.time() - self.node_start_times[name]
                self.log_lines.pop(name, None)
                self._emit_frame()

        elif etype == "rule_sealed":
            name = event.get("rule")
            if name and name in self.node_states:
                self.node_states[name] = "cached"
                self.log_lines.pop(name, None)
                self._emit_frame()

        elif etype == "rule_halted":
            name = event.get("rule")
            if name and name in self.node_states:
                self.node_states[name] = "failed"
                if name in self.node_start_times:
                    self.node_elapsed[name] = time.time() - self.node_start_times[name]
                self.log_lines.pop(name, None)
                self._emit_frame()

    # -- frame rendering --

    def _build_residue(self) -> CliResidue:
        """Build a lightweight CliResidue snapshot for the current state."""
        nodes: list[CliNode] = []
        for rule_name, state in self.node_states.items():
            rule = self.rules.get(rule_name, {})

            rule_inputs = set(rule.get("inputs", []))
            children = []
            for other_name, other_rule in self.rules.items():
                other_outputs = set(other_rule.get("outputs", []))
                if rule_inputs & other_outputs:
                    children.append(other_name)

            # Live elapsed for running nodes
            duration = None
            if state == "running" and rule_name in self.node_start_times:
                duration = time.time() - self.node_start_times[rule_name]
            elif rule_name in self.node_elapsed:
                duration = self.node_elapsed[rule_name]

            node = CliNode(
                name=rule_name,
                kind=rule.get("kind", "action"),
                state=state,
                children=children,
                fuel_budget=rule.get("fuel"),
                duration=duration,
            )
            nodes.append(node)

        # Reorder: target first
        target_name = self.design.get("target") or self.design.get("targets", [None])[0]
        if target_name and nodes:
            idx = next((i for i, n in enumerate(nodes) if n.name == target_name), 0)
            if idx > 0:
                nodes.insert(0, nodes.pop(idx))

        # Compute live fuel used (count sealed/running nodes that had fuel)
        fuel_used = 0
        for n in nodes:
            if n.state in ("sealed", "running") and n.fuel_budget:
                fuel_used += 1  # approximate

        return CliResidue(
            command="run",
            design_name=self.design.get("name", "unknown"),
            site=self.site or "<executing>",
            status="hydrating",
            target=target_name,
            fuel_budget=self.design.get("fuel", 0),
            fuel_used=fuel_used,
            nodes=nodes,
            passes=[],
            fails=[],
        )

    def _emit_frame(self) -> None:
        """Render and emit the current frame."""
        from husks.cli.view import render_dag

        # Add live elapsed time for running oracles to log_lines
        for name, start_time in list(self.oracle_start_times.items()):
            if name in self.log_lines:
                elapsed = time.time() - start_time
                # Update or append live progress line
                progress = f"running {elapsed:.1f}s"
                # Replace last line if it's a progress line, otherwise append
                if self.log_lines[name] and self.log_lines[name][-1].startswith("running "):
                    self.log_lines[name][-1] = progress
                else:
                    self.log_lines[name].append(progress)

        residue = self._build_residue()
        frame = render_dag(residue, verbose=False, log_lines=self.log_lines)

        if self.is_tty:
            # Overwrite previous frame in-place
            if self._last_frame_lines > 0:
                sys.stdout.write(cursor_up(self._last_frame_lines) + CLEAR_DOWN)
            sys.stdout.write(frame + "\n")
            sys.stdout.flush()
            self._last_frame_lines = frame.count("\n") + 1
        else:
            # Pipe mode: only emit on significant state changes
            # (build_start and build_end are handled; emit all for now)
            pass  # suppress intermediate frames when piped


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
        # Blocker #8: Add provenance hashes
        trace = None
        if rule_usage:
            trace = CliTrace(
                backend=rule_usage.get("backend", "unknown"),
                model=rule_usage.get("model"),
                config_hash=rule_usage.get("config_hash"),
                prompt_hash=rule_usage.get("prompt_hash"),
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

    # Compute fuel_used from node-level fuel consumption, not Store delta
    fuel_used = sum(n.fuel for n in nodes if n.fuel is not None)

    # Beta 100: Extract oracle_calls from report for sealed runs
    oracle_calls = 0
    from husks.report import assemble
    report_data = assemble(S, T, design)
    oracle_calls = report_data.get("oracle_calls", 0)

    # Compute husk hash (SHA256 of the .husk file)
    import hashlib
    import os
    husk_hash = None
    site_path = S.get("site")
    if site_path:
        husk_file = os.path.join(site_path, f"{design_name}.husk")
        if os.path.isfile(husk_file):
            with open(husk_file, 'rb') as f:
                husk_hash = hashlib.sha256(f.read()).hexdigest()

    return CliResidue(
        command="run",
        design_name=design_name,
        site=S.get("site"),
        cse_path=cse_path,
        status=S.get("status", "unknown"),
        root=S.get("root"),
        husk_hash=husk_hash,
        target=target_name,
        fuel_budget=design.get("fuel", 0),
        fuel_used=fuel_used,
        oracle_calls=oracle_calls,
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
    """Check command - validate design transport only.

    Silent on success unless --verbose or --json provided.
    """
    from husks.cli.surface import emit_residue

    # Step 1: Validate design
    result = check_categorized(design)
    if not result["ok"]:
        # Validation failed - show errors
        if args.json_output:
            print(json.dumps(result, indent=2))
        else:
            for cat_name, cat in result["categories"].items():
                sym = "\u2713" if cat["ok"] else "\u2717"
                print(f"  {sym} {cat_name}")
                for err in cat["errors"]:
                    print(f"    {err}")
        sys.exit(EXIT_BUILD_FAIL)

    # Step 2: Validation passed
    if args.json_output or args.verbose:
        # Emit residue when requested
        residue = collect_dry_residue(design)
        output = emit_residue(residue, json_mode=args.json_output, verbose=args.verbose)
        print(output)
    # Otherwise silent on success

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
        from husks.oracle.backend import run_oracle
        overrides["oracle_backend"] = run_oracle
        overrides["oracle_backend_name"] = getattr(args, "backend", "litellm")
        if args.hy:
            from husks.designs.hy import hy_kernel_backend
            kern = hy_kernel_backend()
            kern["set_oracle_model"](args.model)
            overrides["oracle_backend"] = kern["live_oracle"]
        elif overrides["oracle_backend_name"] == "litellm":
            from husks.oracle import set_oracle_model
            set_oracle_model(args.model)
        overrides["oracle_model"] = args.model

    # Suppress old Console listener; attach LiveFrameEmitter for non-JSON runs
    from husks.utils import trace as T_pre
    T_pre.clear_listeners()

    live_emitter = None
    if not args.json_output and not getattr(args, 'quiet', False):
        live_emitter = LiveFrameEmitter(
            design, verbose=args.verbose, site=overrides.get("site"),
        )
        T_pre.add_listener(live_emitter)

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

    # Blocker #1: Handle sidecar JSON report (--report-json)
    report_json_path = getattr(args, 'report_json', None)

    # Write sidecar JSON report if requested
    if report_json_path:
        from husks.report import assemble, render_json
        report = assemble(S, T, design)
        report_json = render_json(report)
        try:
            Path(report_json_path).write_text(report_json)
        except Exception as e:
            print(f"error: failed to write --report-json to {report_json_path}: {e}",
                  file=sys.stderr)
            sys.exit(EXIT_BUILD_FAIL)

    # Always write report into site for compare to find
    from husks.report import assemble, render_json
    if report_json_path:
        # Report already assembled above for sidecar; reuse it
        site_report = report
    else:
        report = assemble(S, T, design)
        site_report = report
    site_report_path = Path(S["site"]) / ".traces" / "report.json"
    site_report_path.parent.mkdir(parents=True, exist_ok=True)
    site_report_path.write_text(render_json(site_report))

    # Determine primary output mode
    if args.json_output:
        # JSON to stdout (reuse already-assembled report)
        report_json = render_json(report)
        print(report_json)
    else:
        # Visual output: use residue→surface→view
        from husks.cli.surface import emit_residue

        # Overwrite live emitter's last frame with authoritative final frame
        if live_emitter and live_emitter.is_tty and live_emitter._last_frame_lines > 0:
            sys.stdout.write(cursor_up(live_emitter._last_frame_lines) + CLEAR_DOWN)

        residue = collect_hydrated_residue(S, T, design)
        output = emit_residue(residue, json_mode=False, verbose=args.verbose)
        print(output)

    # Preserve exit code logic
    if S.get("status") == "halted" and not args.soft_fail:
        sys.exit(EXIT_BUILD_FAIL)


# ── verify ─────────────────────────────────────────────────────────

def _cmd_verify(args):
    """Verify a .husk artifact in a site by recomputing its root hash."""
    from husks.core import recompute_root

    site = Path(args.site)
    if not site.is_dir():
        print(f"error: site directory not found: {site}", file=sys.stderr)
        sys.exit(EXIT_USAGE)

    # Auto-detect .husk file or use --name
    name = getattr(args, "name", None)
    if name:
        husk_path = site / f"{name}.husk"
    else:
        husks = list(site.glob("*.husk"))
        if len(husks) == 0:
            print(f"error: no .husk files found in {site}", file=sys.stderr)
            sys.exit(EXIT_BUILD_FAIL)
        if len(husks) > 1 and not name:
            names = ", ".join(h.stem for h in husks)
            print(f"error: multiple .husk files found ({names}); use --name to select one",
                  file=sys.stderr)
            sys.exit(EXIT_USAGE)
        husk_path = husks[0]

    if not husk_path.is_file():
        print(f"error: husk file not found: {husk_path}", file=sys.stderr)
        sys.exit(EXIT_BUILD_FAIL)

    husk_bytes = husk_path.read_bytes()
    root = recompute_root(husk_bytes, str(site))

    json_mode = getattr(args, "json_output", False)
    if json_mode:
        result = {
            "status": "verified",
            "husk": str(husk_path),
            "site": str(site),
            "root": root,
        }
        print(json.dumps(result, indent=2))
    else:
        print(f"verified: {husk_path.name}")
        print(f"  root: {root}")
        print(f"  site: {site}")

    sys.exit(EXIT_OK)
