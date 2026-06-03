"""All _cmd_* command functions."""

from __future__ import annotations

import json
import sys
import threading
import time
from pathlib import Path

from husks.designs.ir import check, check_categorized, show, run
from husks.cli.helpers import EXIT_OK, EXIT_BUILD_FAIL, EXIT_USAGE, EXIT_MISSING_DEP
from husks.cli.residue import CliResidue, CliNode, LogEntry
from husks.utils.console import is_tty, cursor_up, CLEAR_DOWN


# ── Helpers ─────────────────────────────────────────────────────────

def _tool_label(tool: str, args: dict, site_root: str | None = None) -> str:
    """Build a concise label for a tool call: ``tool relative/path``."""
    path = args.get("path", "")
    if path:
        # Strip site root or staging dir prefix to show site-relative path.
        # Staging dirs mirror site structure, so the relative part is the same.
        if site_root and path.startswith(site_root):
            path = path[len(site_root):]
        elif "/husks-stage-" in path:
            # Staging tmpdir: strip everything up to the staging root
            idx = path.index("/husks-stage-")
            rest = path[idx:]
            # Skip the staging dir name itself (next / after husks-stage-xxx)
            slash = rest.find("/", 1)
            path = rest[slash + 1:] if slash != -1 else rest
        return f"{tool} {path}"
    return tool


def _physical_rows(frame: str) -> int:
    """Count physical terminal rows occupied by *frame*.

    Accounts for long lines that wrap beyond terminal width.
    Each logical line occupies ``ceil(visible_width / cols)`` rows,
    with a minimum of 1 row per line.
    """
    import os
    import math
    try:
        cols = os.get_terminal_size().columns
    except (OSError, ValueError):
        cols = 80

    from husks.utils.console import _visible_len

    rows = 0
    for line in frame.split("\n"):
        vlen = _visible_len(line)
        rows += max(1, math.ceil(vlen / cols)) if vlen > 0 else 1
    return rows


def _word_wrap(text: str, *, width: int = 60, max_lines: int = 3) -> list[str]:
    """Wrap *text* on whitespace boundaries, returning at most *max_lines*."""
    words = text.split()
    lines: list[str] = []
    current: list[str] = []
    cur_len = 0

    for word in words:
        needed = (1 + len(word)) if current else len(word)
        if cur_len + needed > width and current:
            lines.append(" ".join(current))
            if len(lines) == max_lines:
                break
            current = [word]
            cur_len = len(word)
        else:
            current.append(word)
            cur_len += needed
    else:
        if current and len(lines) < max_lines:
            lines.append(" ".join(current))

    # Ellipsis if there's remaining text
    if len(lines) == max_lines and " ".join(words) != " ".join(
        w for l in lines for w in l.split()
    ):
        lines[-1] = lines[-1].rstrip()
        if len(lines[-1]) > width - 1:
            lines[-1] = lines[-1][: width - 1]
        lines[-1] += "\u2026"

    return lines


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

        # Per-node sub-terminal log buffers (list[LogEntry]).  Bounded to a
        # tail window so the frame stays within terminal height; the full
        # stream lives in the trace / report.
        self.logs: dict[str, list[LogEntry]] = {}
        self.tail_window = 16 if verbose else 8

        # Full action output buffer (stdout/stderr/tool) retained for
        # failure expansion.  Capped at ACTION_TAIL_MAX (200) to bound
        # memory, but much larger than the display tail window.
        self._action_full: dict[str, list[LogEntry]] = {}

        # Oracle live tracking (for in-progress updates)
        self.oracle_start_times: dict[str, float] = {}
        self.oracle_tokens_in: dict[str, int] = {}
        self.oracle_tokens_out: dict[str, int] = {}

        # Per-node cumulative metrics (updated on oracle_done/rule_done)
        self.node_fuel: dict[str, int] = {}
        self.node_cost: dict[str, float] = {}
        self.node_tokens_in: dict[str, int] = {}
        self.node_tokens_out: dict[str, int] = {}

        # Build start time
        self.build_t0: float | None = None

        # Frame tracking for in-place overwrite
        self._last_frame_lines = 0
        self.is_tty = is_tty()

        # Redraw throttle: high-frequency streams (action_output) coalesce to
        # at most one frame per interval; structural events force a redraw.
        self._min_interval = 0.05
        self._last_render = 0.0

        # Background refresh thread: periodically redraws the frame while
        # oracles are running so the "running X.Xs" counter stays live and
        # tool call activity is visible between blocking API calls.
        self._render_lock = threading.Lock()
        self._refresh_stop = threading.Event()
        self._refresh_thread: threading.Thread | None = None
        self._site_root: str | None = None

    # -- log buffer helpers --

    def _append_log(self, name: str, stream: str, text: str) -> None:
        """Append a line to *name*'s pane, trimming to the tail window."""
        buf = self.logs.setdefault(name, [])
        buf.append(LogEntry(stream, text))
        if len(buf) > self.tail_window:
            del buf[: len(buf) - self.tail_window]

    def _start_refresh(self) -> None:
        """Start the background refresh thread."""
        if self._refresh_thread is not None:
            return
        self._refresh_stop.clear()
        t = threading.Thread(target=self._refresh_worker, daemon=True)
        t.start()
        self._refresh_thread = t

    def _stop_refresh(self) -> None:
        """Stop the background refresh thread."""
        self._refresh_stop.set()
        if self._refresh_thread is not None:
            self._refresh_thread.join(timeout=1.0)
            self._refresh_thread = None

    def _refresh_worker(self) -> None:
        """Periodically redraw frames while oracles are running."""
        while not self._refresh_stop.wait(0.4):
            if self.oracle_start_times:
                self._emit_frame()

    def notify(self, event: dict) -> None:
        """Dispatch trace events (TraceListener protocol)."""
        etype = event.get("event")

        if etype == "build_start":
            self.build_t0 = time.time()
            # Capture site path for relativizing tool call paths
            site = event.get("site")
            if site:
                self._site_root = str(Path(site).resolve()) + "/"
            self._emit_frame(force=True)

        elif etype == "rule_start":
            name = event.get("rule")
            if name and name in self.node_states:
                self.node_states[name] = "running"
                self.node_start_times[name] = time.time()
                self.logs[name] = []
                self._action_full[name] = []
                self._emit_frame(force=True)

        elif etype == "oracle_start":
            name = event.get("rule")
            if name and name in self.logs:
                # Track oracle start for live elapsed display
                self.oracle_start_times[name] = time.time()
                self.oracle_tokens_in[name] = 0
                self.oracle_tokens_out[name] = 0

                # Show prompt preview word-wrapped (max 3 lines).
                # First line gets the → arrow (oracle stream),
                # continuation lines are plain dim (meta stream).
                prompt = event.get("prompt_preview", "")
                if prompt:
                    lines = _word_wrap(prompt.replace("\n", " "), width=60, max_lines=3)
                    for i, line in enumerate(lines):
                        self._append_log(name, "oracle" if i == 0 else "meta", line)

                # Start background refresh so the elapsed counter
                # and tool call activity stay live during blocking
                # API calls.
                self._start_refresh()
                self._emit_frame(force=True)

        elif etype == "oracle_done":
            name = event.get("rule")
            if name and name in self.logs:
                ti = event.get("tokens_in", 0)
                to = event.get("tokens_out", 0)
                cost = event.get("cost_usd", 0.0)
                elapsed = event.get("elapsed", 0.0)
                fuel_steps = event.get("fuel_steps", 1)

                # Reconcile final totals — tool_call events may have
                # incremented fuel during execution; oracle_done sets
                # the authoritative tokens/cost and corrects fuel.
                self.node_fuel[name] = fuel_steps
                self.node_cost[name] = cost
                self.node_tokens_in[name] = ti
                self.node_tokens_out[name] = to

                # Log provenance of the API call (YAML-style)
                if event.get("backend"):
                    self._append_log(name, "meta", f"backend: {event['backend']}")
                if event.get("model"):
                    self._append_log(name, "meta", f"model:   {event['model']}")
                if event.get("tools"):
                    self._append_log(name, "meta", f"tools:   {', '.join(event['tools'])}")
                if event.get("fuel") is not None:
                    self._append_log(name, "meta", f"fuel:    {event['fuel']}")
                if event.get("config_hash"):
                    self._append_log(name, "meta", f"config:  {event['config_hash'][:6]}")
                if event.get("prompt_hash"):
                    self._append_log(name, "meta", f"prompt:  {event['prompt_hash'][:6]}")

                self.oracle_start_times.pop(name, None)
                self.oracle_tokens_in.pop(name, None)
                self.oracle_tokens_out.pop(name, None)

                # Stop refresh thread when no oracles are running
                if not self.oracle_start_times:
                    self._stop_refresh()

                self._emit_frame(force=True)

        elif etype == "oracle_step":
            # Per-API-call token/cost update — fires after each LLM
            # round-trip so the node summary and footer update live.
            name = event.get("rule")
            if name:
                ti = event.get("tokens_in", 0)
                to = event.get("tokens_out", 0)
                cost = event.get("cost_usd", 0.0)
                self.node_tokens_in[name] = self.node_tokens_in.get(name, 0) + ti
                self.node_tokens_out[name] = self.node_tokens_out.get(name, 0) + to
                self.node_cost[name] = self.node_cost.get(name, 0.0) + cost
                self._emit_frame(force=True)

        elif etype == "tool_call":
            name = event.get("rule")
            if name and name in self.logs:
                tool = event.get("tool", "?")
                args = event.get("args", {})
                label = _tool_label(tool, args, self._site_root)
                self._append_log(name, "tool", label)
                # Each tool call is a fuel burn — increment fuel so
                # the node summary and footer update live.
                self.node_fuel[name] = self.node_fuel.get(name, 0) + 1
                self._emit_frame(force=True)

        elif etype == "tool_result":
            name = event.get("rule")
            if name and name in self.logs:
                preview = event.get("result_preview", "")
                if preview and self.verbose:
                    self._append_log(name, "meta", preview)
                self._emit_frame()

        elif etype == "action_output":
            # Streamed stdout/stderr from a shell action: the sub-terminal.
            name = event.get("rule")
            if name and name in self.logs:
                stream = event.get("stream", "stdout")
                line = event.get("line", "")
                self._append_log(name, stream, line)
                # Also retain in the full action buffer for failure expansion.
                buf = self._action_full.setdefault(name, [])
                buf.append(LogEntry(stream, line))
                if len(buf) > 200:
                    del buf[: len(buf) - 200]
                self._emit_frame()  # throttled

        elif etype == "rule_done":
            name = event.get("rule")
            if name and name in self.node_states:
                self.node_states[name] = "sealed"
                if name in self.node_start_times:
                    self.node_elapsed[name] = time.time() - self.node_start_times[name]
                # Seal closes the sub-terminal: the pane collapses.
                self.logs.pop(name, None)
                self._action_full.pop(name, None)
                self._emit_frame(force=True)

        elif etype == "rule_sealed":
            name = event.get("rule")
            if name and name in self.node_states:
                self.node_states[name] = "cached"
                self.logs.pop(name, None)
                self._emit_frame(force=True)

        elif etype == "rule_halted":
            name = event.get("rule")
            if name and name in self.node_states:
                self.node_states[name] = "failed"
                if name in self.node_start_times:
                    self.node_elapsed[name] = time.time() - self.node_start_times[name]
                # Failure expands the sub-terminal to the full action trace,
                # grouped: command first, then stderr (errors), then stdout (context).
                full = self._action_full.get(name, [])
                if full:
                    expanded: list[LogEntry] = []
                    tool_lines = [e for e in full if e.stream == "tool"]
                    err_lines = [e for e in full if e.stream == "stderr"]
                    out_lines = [e for e in full if e.stream == "stdout"]
                    expanded.extend(tool_lines)
                    expanded.extend(err_lines)
                    expanded.extend(out_lines)
                    self.logs[name] = expanded
                # Otherwise keep whatever tail was in the display buffer.
                self._emit_frame(force=True)

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

            # Per-node accumulated metrics from oracle_done events
            from husks.cli.residue import CliTrace
            trace = None
            node_ti = self.node_tokens_in.get(rule_name, 0)
            node_to = self.node_tokens_out.get(rule_name, 0)
            node_cost = self.node_cost.get(rule_name, 0.0)
            if node_ti or node_to or node_cost:
                trace = CliTrace(
                    input_tokens=node_ti,
                    output_tokens=node_to,
                    cost_usd=node_cost,
                    elapsed_s=duration,
                )

            node = CliNode(
                name=rule_name,
                kind=rule.get("kind", "action"),
                state=state,
                children=children,
                fuel=self.node_fuel.get(rule_name),
                fuel_budget=rule.get("fuel"),
                cost=node_cost if node_cost else None,
                duration=duration,
                trace=trace,
            )
            nodes.append(node)

        # Reorder: target first
        target_name = self.design.get("target") or self.design.get("targets", [None])[0]
        if target_name and nodes:
            idx = next((i for i, n in enumerate(nodes) if n.name == target_name), 0)
            if idx > 0:
                nodes.insert(0, nodes.pop(idx))

        # Compute live fuel used from accumulated per-node fuel
        fuel_used = sum(self.node_fuel.values())

        total_cost = sum(self.node_cost.values())

        return CliResidue(
            command="run",
            design_name=self.design.get("name", "unknown"),
            site=self.site or "<executing>",
            status="hydrating",
            target=target_name,
            fuel_budget=self.design.get("fuel", 0),
            fuel_used=fuel_used,
            cost=total_cost,
            nodes=nodes,
            passes=[],
            fails=[],
        )

    def _emit_frame(self, *, force: bool = False) -> None:
        """Render and emit the current frame.

        High-frequency callers (streamed output) pass ``force=False`` and are
        coalesced to at most one redraw per ``self._min_interval``; structural
        state changes pass ``force=True`` and always redraw.
        """
        now = time.time()
        if not force and (now - self._last_render) < self._min_interval:
            return
        self._last_render = now

        from husks.cli.surface import emit_residue

        residue = self._build_residue()
        frame = emit_residue(residue, verbose=False, log_lines=self.logs)

        with self._render_lock:
            if self.is_tty:
                # Overwrite previous frame in-place
                if self._last_frame_lines > 0:
                    sys.stdout.write(cursor_up(self._last_frame_lines) + CLEAR_DOWN)
                sys.stdout.write(frame + "\n")
                sys.stdout.flush()
                self._last_frame_lines = _physical_rows(frame)
            else:
                # Pipe mode: intermediate frames are suppressed; the authoritative
                # final frame is emitted by the run command.
                pass


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
                input_tokens=rule_usage.get("input_tokens", 0),
                output_tokens=rule_usage.get("output_tokens", 0),
                elapsed_s=duration,
                cost_usd=rule_usage.get("cost_usd", 0.0),
                cache_source="local" if cached else None,
                tools=rule.get("tools"),
                fuel=rule.get("fuel"),
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

        # Attach a digestible tail of streamed action output so the verbose
        # final frame can show what the sub-terminal showed live.
        try:
            tail = T.action_tail(rule_name)
        except AttributeError:
            tail = []
        if tail:
            out_lines = [t for s, t in tail if s == "stdout"]
            err_lines = [t for s, t in tail if s == "stderr"]
            if node.trace is None:
                # Show the shell command if available, otherwise generic label
                shell_cmd = rule.get("run")
                node.trace = CliTrace(backend=f"$ {shell_cmd}" if shell_cmd else "shell")
            if out_lines:
                node.trace.stdout = "\n".join(out_lines)
            if err_lines:
                node.trace.stderr = "\n".join(err_lines)

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

    # Compute fuel_used from Store: initial budget minus remaining fuel
    initial_fuel = design.get("fuel", 0)
    remaining_fuel = S.get("fuel", initial_fuel)
    fuel_used = max(0, initial_fuel - remaining_fuel)

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
        root=S.get("build-root"),
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
        if overrides["oracle_backend_name"] == "litellm":
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
