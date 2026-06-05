"""L7 cli -- Argument parsing, command dispatch, rendering.

Merges main.py, helpers.py, console.py, contract.py, surface.py,
view.py, navigator.py, and cmd/ subpackage (build, inspect, validate,
compare, cache) from the liquid beta into a single hardened module.

Dependencies: locke (L5), report (L6), kernel (L0) + stdlib.
No husks.utils imports.  ANSI codes inlined.  No global mutable state
except module-level _IS_TTY detection (frozen at import).
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

# ── §1 Constants ─────────────────────────────────────────────────


def _version() -> str:
    """Resolve the installed package version, falling back to pyproject."""
    try:
        from importlib.metadata import PackageNotFoundError, version
        try:
            return version("husks")
        except PackageNotFoundError:
            pass
    except Exception:
        pass
    return "0+unknown"


# Exit codes (frozen contract)
EXIT_OK = 0
EXIT_BUILD_FAIL = 1
EXIT_USAGE = 2
EXIT_MISSING_DEP = 3
EXIT_DIRTY_STALE = 4
EXIT_INTERNAL = 5

# ANSI codes (suppressed when not TTY)
_IS_TTY = sys.stdout.isatty()

DIM    = "\033[2m" if _IS_TTY else ""
BOLD   = "\033[1m" if _IS_TTY else ""
RESET  = "\033[0m" if _IS_TTY else ""
GREEN  = "\033[32m" if _IS_TTY else ""
YELLOW = "\033[33m" if _IS_TTY else ""
RED    = "\033[31m" if _IS_TTY else ""
CYAN   = "\033[36m" if _IS_TTY else ""
BLUE   = "\033[34m" if _IS_TTY else ""
CLEAR_DOWN = "\033[J" if _IS_TTY else ""

# Right bound for visual layout
R = 81

# State glyphs and colors
STATE_GLYPHS = {"unrealized": "\u25a1", "sealed": "\u25a0", "cached": "\u25c6",
                "stale": "\u25b3", "failed": "\u2715", "running": "\u25c9"}
STATE_COLORS = {"unrealized": DIM, "sealed": GREEN, "cached": CYAN,
                "stale": YELLOW, "failed": RED, "running": CYAN}

# Diamond art
_DIAMOND = {
    "dry": [f"     {DIM}\u25c7{RESET}", f"    {DIM}\u2571 \u2572{RESET}",
            f"   {DIM}\u25c7   \u25c7{RESET}", f"    {DIM}\u2572 \u2571{RESET}",
            f"     {DIM}\u25c7{RESET}"],
    "hydrating": [f"     {CYAN}\u2b20{RESET}", f"    {CYAN}\u2571\u00b7\u2572{RESET}",
                  f"   {CYAN}\u25c6 \u00b7 \u25c6{RESET}", f"    {CYAN}\u2572\u00b7\u2571{RESET}",
                  f"     {CYAN}\u2b21{RESET}"],
    "sealed": [f"     {YELLOW}\u25c6{RESET}", f"    {YELLOW}\u2571 \u2572{RESET}",
               f"   {YELLOW}\u25c6 \u25c6 \u25c6{RESET}", f"    {YELLOW}\u2572 \u2571{RESET}",
               f"     {YELLOW}\u25c6{RESET}"],
    "failed": [f"     {RED}\u25c6{RESET}", f"    {RED}\u2571 \u2572{RESET}",
               f"   {RED}\u25c6 \u25c6 \u25c6{RESET}", f"    {RED}\u2572 \u2571{RESET}",
               f"     {RED}\u25c6{RESET}"],
    "white": [f"     {BOLD}\u25c6{RESET}", f"    {BOLD}\u2571 \u2572{RESET}",
              f"   {BOLD}\u25c6 \u25c6 \u25c6{RESET}", f"    {BOLD}\u2572 \u2571{RESET}",
              f"     {BOLD}\u25c6{RESET}"],
}
_DIAMOND_VIS = [6, 7, 8, 7, 6]


# ── §2 Helpers ───────────────────────────────────────────────────

def _visible_len(s: str) -> int:
    """Visible terminal-column width (strips ANSI)."""
    stripped = re.sub(r'\x1B\[[0-?]*[ -/]*[@-~]', '', s)
    return sum(2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1 for ch in stripped)


def _rpad(left: str, right: str, width: int) -> str:
    """Pad between left and right to fill width (ANSI-safe)."""
    if not right:
        return left
    gap = max(1, width - _visible_len(left) - _visible_len(right))
    return f"{left}{' ' * gap}{right}"


def _format_tokens(n: int) -> str:
    return str(n) if n < 1000 else f"{n / 1000:.1f}k"


def _truncate_right(text: str, max_width: int) -> str:
    text = text.replace("\t", "    ")
    return text if _visible_len(text) <= max_width else text[:max(1, max_width - 1)] + "\u2026"


def render_banner(stage: str, right_lines: list[str] | None = None) -> str:
    """5-line morphing diamond banner with right-aligned metadata."""
    art = _DIAMOND.get(stage, _DIAMOND["hydrating"])
    right = (right_lines or []) + [""] * 5
    max_vis = max(_DIAMOND_VIS)
    lines = []
    for i, (dline, vis) in enumerate(zip(art, _DIAMOND_VIS)):
        rtxt = right[i]
        if rtxt:
            gap = max_vis - vis + 2
            lines.append(f"{dline}{' ' * gap}{rtxt}")
        else:
            lines.append(dline)
    return "\n".join(lines)


def cursor_up(n: int) -> str:
    return f"\033[{n}A" if _IS_TTY and n > 0 else ""


def resolve_design(args) -> str:
    """Return design path from args or default to design.locke / design.json."""
    d = getattr(args, "design", None)
    if d:
        return d
    if Path("design.locke").exists():
        return "design.locke"
    if Path("design.json").exists():
        return "design.json"
    print("husks: no design file. Pass a .locke or .json path, or create design.locke in cwd.", file=sys.stderr)
    sys.exit(EXIT_USAGE)


# ── §3 View renderers ───────────────────────────────────────────

def render_output(*, preamble: str | None = None,
                  trace: list[str] | None = None,
                  footer: str | None = None) -> str:
    """Compose CLI output from three optional sections."""
    parts: list[str] = []
    if preamble is not None:
        parts.append(preamble)
    if trace is not None:
        parts.extend(trace)
    if trace is not None:
        parts.append(f"  {DIM}{'\u2500' * (R - 2)}{RESET}")
    elif footer is not None and preamble is None:
        parts.append(f"  {DIM}{'\u2500' * (R - 2)}{RESET}")
    if footer is not None:
        parts.append(footer)
    return "\n".join(parts)


def render_preamble(*, design_name: str, display_status: str,
                    diamond_stage: str, husk_hash: str | None = None,
                    root: str | None = None, site: str | None = None,
                    stage_label: str, fuel_budget: int = 0,
                    status_suffix: str = "") -> str:
    """Logo header + stage header + first divider."""
    state_colors = {"checked": DIM, "sealed": YELLOW, "failed": RED, "hydrating": CYAN}
    sc = state_colors.get(display_status, DIM)
    state_str = f"{sc}{display_status}{RESET}"
    is_sealed = display_status == "sealed"
    husk_color, root_color = (YELLOW if is_sealed else DIM), (GREEN if is_sealed else RED)

    right = [
        f"{BOLD}design{RESET}: {design_name}",
        f"{BOLD}state{RESET}:  {state_str}{status_suffix}",
        f"{BOLD}husk{RESET}:   {husk_color}{husk_hash}{RESET}" if husk_hash else "",
        f"{BOLD}root{RESET}:   {root_color}{root}{RESET}" if root else "",
        f"{BOLD}site{RESET}:   {site}" if site else "",
    ]
    parts = [render_banner(diamond_stage, right), ""]
    stage_left = f"  {BOLD}{stage_label}{RESET}"
    if fuel_budget and fuel_budget > 0:
        parts.append(_rpad(stage_left, f"\u26a1{fuel_budget}", R))
    else:
        parts.append(stage_left)
    parts.append(f"  {DIM}{'\u2500' * (R - 2)}{RESET}")
    return "\n".join(parts)


def render_motif_tree(nodes: list, *, verbose: bool = False) -> list[str]:
    """Render target-rooted tree with right-aligned metadata."""
    if not nodes:
        return []
    nodes_by_name = {n.name: n for n in nodes}
    lines: list[str] = []
    _render_motif_node(nodes[0], nodes_by_name, lines, "", verbose=verbose,
                       is_last=True, is_root=True)
    return lines


def _render_motif_node(node, nodes_by_name, lines, prefix, *,
                       verbose, is_last, is_root=False):
    glyph = STATE_GLYPHS.get(node.state, "\u25a1")
    color = STATE_COLORS.get(node.state, RESET)
    connector = "" if is_root else ("\u2514\u2500 " if is_last else "\u251c\u2500 ")
    full_prefix = prefix + connector
    base = "  "
    left = f"{base}{full_prefix}{color}{glyph}{RESET} {node.name}"
    kind_str = f"{DIM}{node.kind}{RESET}"
    left_vis = len(base) + len(full_prefix) + 1 + 1 + len(node.name)
    kind_gap = max(1, 22 - left_vis)
    left_with_kind = f"{left}{' ' * kind_gap}{kind_str}"

    right_parts = _node_right_parts(node)
    sep = f" {DIM}\u00b7{RESET} "
    right_str = sep.join(right_parts)
    lines.append(_rpad(left_with_kind, right_str, R) if right_str else left_with_kind.rstrip())

    if is_root:
        own_cont = ""
    elif is_last:
        own_cont = "   "
    else:
        own_cont = "\u2502  "
    inner_prefix = prefix + own_cont

    if verbose:
        indent = base + inner_prefix + "  "
        _render_verbose_details(node, lines, indent)

    children = [nodes_by_name[c] for c in getattr(node, 'children', []) if c in nodes_by_name]
    for i, child in enumerate(children):
        _render_motif_node(child, nodes_by_name, lines, inner_prefix,
                           verbose=verbose, is_last=(i == len(children) - 1))


def _node_right_parts(node) -> list[str]:
    if node.state == "unrealized":
        return [f"\u26a1{node.fuel_budget}"] if node.fuel_budget is not None else []
    parts = []
    has_trace = node.trace and (node.trace.input_tokens or node.trace.output_tokens)
    if has_trace:
        ti = node.trace.input_tokens or 0
        to = node.trace.output_tokens or 0
        cost = node.cost if node.cost is not None else (node.trace.cost_usd if node.trace else 0.0)
        parts += [f"{_format_tokens(ti)}in", f"{_format_tokens(to)}out", f"${cost:.4f}"]
    elif node.kind == "oracle":
        parts += [f"0in", f"0out", f"${node.cost or 0.0:.4f}"]
    elapsed = node.duration if node.duration is not None else 0.0
    parts.append(f"{elapsed:.1f}s")
    if node.cache:
        parts.append("\u26a10")
    elif node.fuel is not None:
        parts.append(f"\u26a1{node.fuel}")
    return parts


def _render_verbose_details(node, lines, indent):
    if node.outputs:
        for out in node.outputs:
            h = out.sha256[:6] if out.sha256 else "??????"
            lines.append(f"{indent}{DIM}{out.path}@{h}{RESET}")
    if node.trace:
        t = node.trace
        if t.backend:
            lines.append(f"{indent}{DIM}backend: {t.backend}{RESET}")
        if t.model:
            lines.append(f"{indent}{DIM}model:   {t.model}{RESET}")
    if node.stale_reason:
        lines.append(f"{indent}{DIM}stale:  {node.stale_reason}{RESET}")
    if node.diagnosis:
        lines.append(f"{indent}{RED}error:  {node.diagnosis}{RESET}")


def render_footer(*, left_text: str, right_text: str) -> str:
    return _rpad(f"  {left_text}", right_text, R)


# ── §4 Surface dispatch ─────────────────────────────────────────

STAGE_MAP = {"check": "design", "run": "build", "status": "status"}


def emit_residue(residue, *, json_mode: bool = False,
                 verbose: bool = False, quiet: bool = False) -> str:
    """Dispatch residue to JSON or visual output."""
    if quiet:
        return ""
    if json_mode:
        return _emit_json(residue)
    return _emit_visual(residue, verbose=verbose)


def _emit_visual(residue, *, verbose: bool = False) -> str:
    from husks.report import map_display_status
    display_status = map_display_status(residue.status, residue.command)
    diamond_stage = _diamond_stage(residue)
    stage_label = STAGE_MAP.get(residue.command, residue.command)
    preamble = render_preamble(
        design_name=residue.design_name, display_status=display_status,
        diamond_stage=diamond_stage, husk_hash=residue.husk_hash,
        root=residue.root, site=residue.site, stage_label=stage_label,
        fuel_budget=residue.fuel_budget)
    left = _footer_left(residue)
    right = _footer_right(residue)
    footer = render_footer(left_text=left, right_text=right)
    if residue.command == "status" and not verbose:
        return render_output(preamble=preamble, footer=footer)
    trace_lines = []
    if residue.site_inputs and residue.command == "check":
        trace_lines.append(f"  {DIM}site inputs:{RESET}")
        for local, source in sorted(residue.site_inputs.items()):
            if local == source:
                trace_lines.append(f"    {DIM}{local}{RESET}")
            else:
                trace_lines.append(f"    {DIM}{local} \u2190 {source}{RESET}")
        trace_lines.append("")
    trace_lines.extend(render_motif_tree(residue.nodes, verbose=verbose))
    return render_output(preamble=preamble, trace=trace_lines, footer=footer)


def _diamond_stage(residue) -> str:
    if residue.status == "dry" or residue.command == "check":
        return "dry"
    if residue.status == "hydrating":
        return "hydrating"
    if residue.status == "halted":
        return "failed"
    return "sealed"


def _footer_left(residue) -> str:
    if residue.command == "check":
        return "dry"
    if residue.command == "run":
        if residue.status == "committed":
            root_short = residue.root[:10] if residue.root else ""
            return f"committed: {root_short}" if root_short else "committed"
        if residue.status == "halted":
            failed = next((n.name for n in residue.nodes if n.state == "failed"), "")
            return f"halt: {failed}" if failed else "halted"
        return residue.status
    if residue.command in ("status", "history"):
        stale = [n for n in residue.nodes if n.state == "stale"]
        return f"stale: {stale[0].stale_reason}" if stale and stale[0].stale_reason else "sealed"
    return "passed"


def _footer_right(residue) -> str:
    if residue.command not in ("run", "status", "history"):
        return ""
    cost = residue.cost or 0.0
    fuel_used = residue.fuel_used or 0
    fuel_budget = residue.fuel_budget or 0
    sep = f" {DIM}\u00b7{RESET} "
    total_in = sum((n.trace.input_tokens or 0) for n in residue.nodes if n.trace)
    total_out = sum((n.trace.output_tokens or 0) for n in residue.nodes if n.trace)
    total_elapsed = sum(n.duration for n in residue.nodes if n.duration and n.duration > 0)
    parts = [f"{_format_tokens(total_in)}in", f"{_format_tokens(total_out)}out",
             f"${cost:.4f}", f"{total_elapsed:.1f}s"]
    if residue.command in ("status", "history"):
        parts.append(f"\u26a1{fuel_used}")
    else:
        parts.append(f"\u26a1{fuel_used}/{fuel_budget}")
    return sep.join(parts)


def _emit_json(residue) -> str:
    from husks.report import map_display_status
    status_display = map_display_status(residue.status, residue.command)
    output = {"command": residue.command, "name": residue.design_name,
              "site": residue.site, "status": status_display,
              "root": residue.root, "husk": residue.husk_hash,
              "fuel_budget": residue.fuel_budget, "fuel_used": residue.fuel_used,
              "cost": residue.cost, "nodes": [], "passes": residue.passes,
              "fails": residue.fails}
    if residue.site_inputs:
        output["site_inputs"] = residue.site_inputs
    for node in residue.nodes:
        nd = {"name": node.name, "kind": node.kind, "state": node.state,
              "cached": node.cache}
        if node.children: nd["children"] = node.children
        if node.fuel is not None: nd["fuel"] = node.fuel
        if node.fuel_budget is not None: nd["fuel_budget"] = node.fuel_budget
        if node.cost is not None: nd["cost"] = node.cost
        if node.diagnosis is not None: nd["diagnosis"] = node.diagnosis
        if node.stale_reason is not None: nd["stale_reason"] = node.stale_reason
        if node.duration is not None: nd["duration"] = node.duration
        if node.outputs:
            nd["outputs"] = [{"path": o.path, "sha256": o.sha256} for o in node.outputs]
        if node.trace:
            nd["tokens"] = {"input": node.trace.input_tokens or 0,
                            "output": node.trace.output_tokens or 0}
            if node.trace.backend is not None: nd["backend"] = node.trace.backend
            if node.trace.model is not None: nd["model"] = node.trace.model
        output["nodes"].append(nd)
    if residue.error_message:
        output["error"] = residue.error_message
    return json.dumps(output, indent=2)


def emit_help(version: str) -> str:
    """Render top-level husks --help output."""
    preamble = render_banner("white", [
        f"{BOLD}husks{RESET} {DIM}{version}{RESET}",
        f"{DIM}A small build system for nondeterministic work.{RESET}", "", "", ""])
    def _group(name): return f"\n  {BOLD}{name}{RESET}"
    def _cmd(name, desc): return f"    {name:<18s}{DIM}{desc}{RESET}"
    trace = [
        _group("design"), _cmd("check", "Validate a design"),
        _group("build"), _cmd("run", "Execute a design into a site"),
        _cmd("status", "Inspect site state"),
        _group("verify"), _cmd("verify", "Recompute .husk root hash in a site"),
        _cmd("compare", "Equivalence across sites"),
        _group("inspect"), _cmd("history", "Show convergence across runs"),
        _group("cache"), _cmd("cache export", "Pack cache for transfer"),
        _cmd("cache import", "Unpack cache into site"),
        _group("diagnostics"), _cmd("doctor", "Diagnose the local environment"),
        _cmd("tree", "Show working directory overview"),
        "", f"  {DIM}--color <mode>   auto \u00b7 always \u00b7 never{RESET}",
        f"  {DIM}-q, --quiet      Suppress output{RESET}",
        f"  {DIM}--version        Print version{RESET}"]
    footer_lines = [f"  {DIM}husks <command> --help for details{RESET}", "",
                    f"  {BOLD}Exit codes{RESET}",
                    f"    {DIM}0  Success{RESET}", f"    {DIM}1  Build failed{RESET}",
                    f"    {DIM}2  Usage error{RESET}", f"    {DIM}3  Missing dependency{RESET}",
                    f"    {DIM}4  Dirty/stale{RESET}", f"    {DIM}5  Internal error{RESET}"]
    return render_output(preamble=preamble, trace=trace, footer="\n".join(footer_lines))


# ── §5 Residue collectors ───────────────────────────────────────

def collect_dry_residue(design: dict):
    """Build CliResidue for check command (no execution)."""
    from husks.report import CliResidue, CliNode
    rules = design.get("rules", [])
    deps = {}
    for rule in rules:
        rule_inputs = set(rule.get("inputs", []))
        deps[rule["name"]] = []
        for other in rules:
            other_outputs = set(other.get("outputs", []))
            if rule_inputs & other_outputs:
                deps[rule["name"]].append(other["name"])
    nodes = [CliNode(name=r["name"], kind=r.get("kind", "action"), state="unrealized",
                     children=deps.get(r["name"], []), fuel_budget=r.get("fuel"))
             for r in rules]
    target_name = design.get("target") or (design.get("targets", [None])[0] if design.get("targets") else None)
    if target_name:
        idx = next((i for i, n in enumerate(nodes) if n.name == target_name), 0)
        if idx > 0: nodes.insert(0, nodes.pop(idx))
    si = design.get("site_inputs", {})
    if isinstance(si, list):
        si = {s: s for s in si}
    return CliResidue(command="check", design_name=design.get("name", "unknown"),
                      status="dry", target=target_name,
                      fuel_budget=design.get("fuel", 0), nodes=nodes, passes=["checks"],
                      site_inputs=si)


def collect_hydrated_residue(S: dict, design: dict):
    """Build CliResidue from completed build Store."""
    from husks.report import CliResidue, CliNode, CliTrace, CliOutput, map_trace_state, read_history
    from husks.seal import file_sig, site_path as _site_path
    import hashlib as _hl

    rules = design.get("rules", [])
    usage = S.get("usage", {})
    by_rule = usage.get("by_rule", {})
    trace_events = S.get("trace", [])

    # Read last history entry per rule for elapsed + output hashes.
    site = S.get("site", "")
    hist_map: dict[str, dict] = {}
    for rule in rules:
        entries = read_history(site, rule["name"])
        if entries:
            hist_map[rule["name"]] = entries[-1]

    # Build lookup maps
    deps = {}
    for rule in rules:
        rule_inputs = set(rule.get("inputs", []))
        deps[rule["name"]] = []
        for other in rules:
            other_outputs = set(other.get("outputs", []))
            if rule_inputs & other_outputs:
                deps[rule["name"]].append(other["name"])

    # Node events from trace
    node_done = {}
    halt_reasons = {}
    for ev in trace_events:
        evt = ev.get("event")
        if evt == "fired":
            node_done.setdefault(ev.get("rule"), "fired")
        elif evt == "sealed":
            node_done.setdefault(ev.get("rule"), "reused")
        elif evt == "rule-halted":
            node_done[ev.get("rule")] = "failed"
            halt_reasons[ev.get("rule")] = ev.get("error", "")

    nodes = []
    for rule in rules:
        rname = rule["name"]
        raw_state = node_done.get(rname, "")
        rule_usage = by_rule.get(rname, {})
        cached = rule_usage.get("cached", False) or raw_state == "reused"
        state = map_trace_state(raw_state, cached=cached, failed=(raw_state == "failed"))

        # Output hashes from history entry or live file_sig.
        hist = hist_map.get(rname, {})
        out_hashes = hist.get("output_hashes", [])
        rule_outputs = rule.get("outputs", [])
        outputs = []
        for i, o in enumerate(rule_outputs):
            h = out_hashes[i] if i < len(out_hashes) else None
            if not h and site:
                raw = file_sig(_site_path(S, o))
                h = raw.decode() if isinstance(raw, bytes) else None
            outputs.append(CliOutput(path=o, sha256=h))

        elapsed = hist.get("elapsed_s")
        trace = CliTrace(
            backend=rule_usage.get("backend"),
            model=rule_usage.get("model"),
            config_hash=rule_usage.get("config_hash"),
            prompt_hash=rule_usage.get("prompt_hash"),
            input_tokens=rule_usage.get("input_tokens", 0),
            output_tokens=rule_usage.get("output_tokens", 0),
            elapsed_s=elapsed,
            cost_usd=rule_usage.get("cost_usd", 0.0),
            cache_source="local" if cached else None,
        ) if rule_usage else None

        nd = CliNode(
            name=rname, kind=rule.get("kind", "action"), state=state,
            children=deps.get(rname, []),
            fuel=rule_usage.get("fuel_consumed"),
            fuel_budget=rule.get("fuel"),
            cost=rule_usage.get("cost_usd"),
            cache=cached, outputs=outputs, trace=trace,
            duration=elapsed, diagnosis=halt_reasons.get(rname),
        )
        nodes.append(nd)

    target_name = design.get("target") or (design.get("targets", [None])[0] if design.get("targets") else None)
    if target_name:
        idx = next((i for i, n in enumerate(nodes) if n.name == target_name), 0)
        if idx > 0: nodes.insert(0, nodes.pop(idx))

    initial_fuel = design.get("fuel", 0)
    fuel_used = max(0, initial_fuel - S.get("fuel", initial_fuel))
    design_name = design.get("name", "unknown")

    husk_hash = None
    site_path = S.get("site")
    if site_path:
        hp = Path(site_path) / f"{design_name}.husk"
        if hp.is_file():
            husk_hash = _hl.sha256(hp.read_bytes()).hexdigest()

    passes = ["run"] if S.get("status") == "committed" else []
    fails = ["run"] if S.get("status") == "halted" else []
    if any(n.cache for n in nodes): passes.append("cache")

    return CliResidue(
        command="run", design_name=design_name, site=S.get("site"),
        cse_path=f"{design_name}.husk", status=S.get("status", "unknown"),
        root=S.get("build-root"), husk_hash=husk_hash,
        target=target_name, fuel_budget=initial_fuel, fuel_used=fuel_used,
        cost=usage.get("total_cost_usd", 0.0), nodes=nodes,
        passes=passes, fails=fails)


# ── §7 Commands ──────────────────────────────────────────────────

def _cmd_check(args, design):
    from husks.locke import check_categorized
    result = check_categorized(design)
    if not result["ok"]:
        if args.json_output:
            print(json.dumps(result, indent=2))
        else:
            for cat_name, cat in result["categories"].items():
                sym = "\u2713" if cat["ok"] else "\u2717"
                print(f"  {sym} {cat_name}")
                for err in cat["errors"]:
                    print(f"    {err}")
        sys.exit(EXIT_BUILD_FAIL)
    if args.json_output or args.verbose:
        residue = collect_dry_residue(design)
        print(emit_residue(residue, json_mode=args.json_output, verbose=args.verbose))
    sys.exit(EXIT_OK)


def _cmd_run(args, design):
    from husks.locke import run as locke_run
    from husks.config import load_config, oracle_config_from_toml
    overrides = {}
    if args.unsafe:
        overrides["unsafe"] = True
    if args.site:
        overrides["site"] = args.site
    if args.reuse_only:
        overrides["cache_reuse_only"] = True
    if not args.stub and not args.reuse_only:
        try:
            from husks.oracle import run_oracle
            overrides["oracle_backend"] = run_oracle
            overrides["oracle_backend_name"] = getattr(args, "backend", "litellm")
        except ImportError:
            print("husks run: oracle backend unavailable (litellm not importable). "
                  "Reinstall husks, or: pip install litellm", file=sys.stderr)
            sys.exit(EXIT_MISSING_DEP)

        # Load .husks.toml and build oracle config
        oc = oracle_config_from_toml(load_config())
        # CLI --model overrides config file (only if not the argparse default)
        if args.model != "anthropic/claude-haiku-4-5-20251001":
            oc["model"] = args.model
        overrides["oracle_config"] = oc
    try:
        S = locke_run(design, **overrides)
    except ValueError as e:
        if args.json_output:
            print(json.dumps({"status": "error", "error_type": "setup_failure",
                              "error": str(e)}))
        else:
            print(f"husks run: {e}", file=sys.stderr)
        sys.exit(EXIT_BUILD_FAIL)
    except Exception as e:
        if args.json_output:
            print(json.dumps({"status": "error", "error_type": "unexpected",
                              "error": str(e)}))
        else:
            print(f"husks run: {e}", file=sys.stderr)
        sys.exit(EXIT_BUILD_FAIL)

    # Report
    report_json_path = getattr(args, 'report_json', None)
    if report_json_path or args.json_output:
        from husks.report import assemble, render_json
        report = assemble(S, S.get("trace", []), design)
        if report_json_path:
            Path(report_json_path).write_text(render_json(report))
        if args.json_output:
            print(render_json(report))
    elif args.verbose:
        residue = collect_hydrated_residue(S, design)
        print(emit_residue(residue, verbose=True))

    if S.get("status") == "halted" and not args.soft_fail:
        sys.exit(EXIT_BUILD_FAIL)


def _cmd_verify(args):
    from husks.kernel import recompute_root
    from husks.report import read_manifest
    site = Path(args.site)
    if not site.is_dir():
        print(f"husks: site not found: {site}", file=sys.stderr)
        sys.exit(EXIT_USAGE)
    name = getattr(args, "name", None)
    if name:
        hp = site / f"{name}.husk"
    else:
        husks = list(site.glob("*.husk"))
        if len(husks) == 0:
            print(f"husks verify: no .husk files in {site}", file=sys.stderr); sys.exit(EXIT_BUILD_FAIL)
        if len(husks) > 1:
            print(f"husks verify: multiple .husk files in {site}; use --name to pick one.", file=sys.stderr); sys.exit(EXIT_USAGE)
        hp = husks[0]
    if not hp.is_file():
        print(f"husks verify: husk not found: {hp}", file=sys.stderr); sys.exit(EXIT_BUILD_FAIL)
    try:
        root = recompute_root(hp.read_bytes(), str(site))
    except Exception as exc:
        if getattr(args, "json_output", False):
            print(json.dumps({"status": "failed", "husk": str(hp), "site": str(site),
                              "root": None, "errors": [f"husk parse error: {exc}"]}, indent=2))
        elif getattr(args, "verbose", False):
            print(f"FAILED: {hp.name}\n  husk parse error: {exc}")
        sys.exit(EXIT_BUILD_FAIL)

    # Cross-check: manifest root and site must agree.
    manifest = read_manifest(str(site))
    errors = []
    if manifest:
        manifest_root = manifest.get("root")
        manifest_site = manifest.get("site")
        if manifest_root and manifest_root != root:
            errors.append(f"root mismatch: recomputed {root[:16]}... != manifest {manifest_root[:16]}...")
        if manifest_site and not str(site).endswith(manifest_site) and manifest_site != str(site):
            errors.append(f"site mismatch: manifest says {manifest_site}, verifying {site}")
    else:
        errors.append(f"no manifest in {site}/.traces/")

    if errors:
        if getattr(args, "json_output", False):
            print(json.dumps({"status": "failed", "husk": str(hp), "site": str(site),
                              "root": root, "errors": errors}, indent=2))
        elif getattr(args, "verbose", False):
            print(f"FAILED: {hp.name}")
            for e in errors:
                print(f"  {e}")
        sys.exit(EXIT_BUILD_FAIL)

    if getattr(args, "json_output", False):
        print(json.dumps({"status": "verified", "husk": str(hp), "site": str(site), "root": root}, indent=2))
    elif getattr(args, "verbose", False):
        print(f"verified: {hp.name}\n  root: {root}\n  site: {site}")
    sys.exit(EXIT_OK)


def _build_site_residue(site: str):
    """Build a CliResidue for a site from its manifest and history.  Returns (residue, manifest) or None."""
    import hashlib as _hl
    from husks.report import (read_manifest, compute_rule_states, CliResidue, CliNode,
                        CliTrace as _CliTrace, read_history, map_manifest_state)
    manifest = read_manifest(site)
    if not manifest:
        return None, None
    states = compute_rule_states(site, manifest)
    rule_children = {r["name"]: r.get("children", []) for r in manifest.get("rules", [])}
    nodes = [CliNode(name=s["name"], kind=s["kind"],
                     state=map_manifest_state(s["state"]),
                     stale_reason=s["reason"],
                     children=rule_children.get(s["name"], [])) for s in states]
    has_stale = any(n.state == "stale" for n in nodes)

    husk_hash = None
    design_name = manifest.get("name", "?")
    hp = Path(site) / f"{design_name}.husk"
    if hp.is_file():
        husk_hash = _hl.sha256(hp.read_bytes()).hexdigest()

    total_cost, fuel_used = 0.0, 0
    report_path = Path(site) / ".traces" / "report.json"
    if report_path.is_file():
        try:
            rdata = json.loads(report_path.read_text())
            total_cost = rdata.get("cost", {}).get("paid", 0.0) or 0.0
            fobj = rdata.get("fuel", {})
            fuel_used = (fobj.get("start", 0) or 0) - (fobj.get("end", 0) or 0)
        except Exception:
            pass
    use_history_totals = (total_cost == 0.0 and fuel_used == 0)
    node_map = {n.name: n for n in nodes}
    for rule in manifest.get("rules", []):
        entries = read_history(site, rule["name"])
        if not entries:
            continue
        last = entries[-1]
        if use_history_totals:
            total_cost += last.get("cost_usd") or 0.0
            fuel_used += last.get("fuel_consumed") or 0
        n = node_map.get(rule["name"])
        if n:
            n.trace = _CliTrace(
                input_tokens=last.get("tokens_in") or 0,
                output_tokens=last.get("tokens_out") or 0,
                cost_usd=last.get("cost_usd") or 0.0,
                elapsed_s=last.get("elapsed_s"))
            n.duration = last.get("elapsed_s")
            if n.kind == "oracle":
                n.cost = last.get("cost_usd") or 0.0
                n.fuel = last.get("fuel_consumed") or 0
                if last.get("cached"):
                    n.cache = True
                    n.state = "cached"
                elif n.fuel > 0:
                    n.state = "fired"

    residue = CliResidue(
        command="status", design_name=design_name,
        status="stale" if has_stale else "sealed", site=site,
        root=manifest.get("root"), husk_hash=husk_hash,
        cost=total_cost, fuel_used=fuel_used, nodes=nodes,
        passes=[] if has_stale else ["site"], fails=["site"] if has_stale else [])
    return residue, manifest


def _cmd_status(args):
    site = args.site
    residue, manifest = _build_site_residue(site)
    if residue is None:
        print(f"husks: no manifest in {site}/.traces/ — has this site been built?", file=sys.stderr)
        sys.exit(EXIT_BUILD_FAIL)
    output = emit_residue(residue, json_mode=getattr(args, "json_output", False),
                          verbose=getattr(args, "verbose", False))
    print(output)
    if getattr(args, "fail_if_dirty", False) or getattr(args, "fail_if_stale", False):
        if residue.status == "stale": sys.exit(EXIT_DIRTY_STALE)



_TREND_ARROW = {"falling": "\u2193", "rising": "\u2191", "flat": "\u2500"}
_CLASS_COLOR = {"stable": GREEN, "converging": CYAN, "volatile": YELLOW,
                "prompt-loading": YELLOW, "no-data": DIM}


def _node_history_right_parts(node, cs: dict) -> list[str]:
    """Right-aligned metadata for a history tree node: classification + trends."""
    cls = cs.get("classification", "no-data")
    color = _CLASS_COLOR.get(cls, DIM)
    parts = [f"{color}{cls}{RESET}"]
    ft = cs.get("fuel_trend")
    pt = cs.get("prompt_trend")
    out_stable = cs.get("output_stable")
    if ft is not None:
        parts.append(f"fuel{_TREND_ARROW.get(ft, '?')}")
    if pt is not None:
        parts.append(f"prompt{_TREND_ARROW.get(pt, '?')}")
    if out_stable is not None:
        parts.append("out=stable" if out_stable else "out=varies")
    return parts


def render_history_tree(nodes: list, convergence: dict[str, dict]) -> list[str]:
    """Render motif tree with convergence trends on the right instead of cost/tokens."""
    if not nodes:
        return []
    nodes_by_name = {n.name: n for n in nodes}
    lines: list[str] = []
    _render_history_node(nodes[0], nodes_by_name, convergence, lines, "",
                         is_last=True, is_root=True)
    return lines


def _render_history_node(node, nodes_by_name, convergence, lines, prefix,
                         *, is_last, is_root=False):
    glyph = STATE_GLYPHS.get(node.state, "\u25a1")
    color = STATE_COLORS.get(node.state, RESET)
    connector = "" if is_root else ("\u2514\u2500 " if is_last else "\u251c\u2500 ")
    full_prefix = prefix + connector
    base = "  "
    left = f"{base}{full_prefix}{color}{glyph}{RESET} {node.name}"
    kind_str = f"{DIM}{node.kind}{RESET}"
    left_vis = len(base) + len(full_prefix) + 1 + 1 + len(node.name)
    kind_gap = max(1, 22 - left_vis)
    left_with_kind = f"{left}{' ' * kind_gap}{kind_str}"

    cs = convergence.get(node.name, {"classification": "no-data"})
    right_parts = _node_history_right_parts(node, cs)
    sep = f" {DIM}\u00b7{RESET} "
    right_str = sep.join(right_parts)
    lines.append(_rpad(left_with_kind, right_str, R) if right_str else left_with_kind.rstrip())

    if is_root:
        own_cont = ""
    elif is_last:
        own_cont = "   "
    else:
        own_cont = "\u2502  "
    inner_prefix = prefix + own_cont

    children = [nodes_by_name[c] for c in getattr(node, 'children', []) if c in nodes_by_name]
    for i, child in enumerate(children):
        _render_history_node(child, nodes_by_name, convergence, lines, inner_prefix,
                             is_last=(i == len(children) - 1))


def _cmd_history(args):
    from husks.report import convergence_summary, read_manifest
    site = args.site
    rule = getattr(args, "rule", None)
    n = getattr(args, "n", 5)
    json_mode = getattr(args, "json_output", False)
    if rule:
        cs = convergence_summary(rule, site, n=n)
        if json_mode:
            print(json.dumps(cs, indent=2))
        else:
            print(f"  {rule}: {cs['classification']}")
            print(f"    fuel:   {cs['fuel_trend'] or '--'}")
            print(f"    prompt: {cs['prompt_trend'] or '--'}")
            print(f"    output: {'stable' if cs['output_stable'] else 'varies'}")
    else:
        manifest = read_manifest(site)
        if not manifest:
            print(f"husks: no manifest in {site}/.traces/ — has this site been built?", file=sys.stderr); sys.exit(EXIT_BUILD_FAIL)
        convergence = {}
        for r in manifest.get("rules", []):
            convergence[r["name"]] = convergence_summary(r["name"], site, n=n)
        if json_mode:
            print(json.dumps(convergence, indent=2))
        else:
            residue, _ = _build_site_residue(site)
            if residue is None:
                print(f"husks: no manifest in {site}/.traces/ — has this site been built?", file=sys.stderr)
                sys.exit(EXIT_BUILD_FAIL)
            residue.command = "history"
            from husks.report import map_display_status
            display_status = map_display_status(residue.status, "status")
            diamond_stage = _diamond_stage(residue)
            preamble = render_preamble(
                design_name=residue.design_name, display_status=display_status,
                diamond_stage=diamond_stage, husk_hash=residue.husk_hash,
                root=residue.root, site=residue.site, stage_label="history")
            trace = render_history_tree(residue.nodes, convergence)
            footer = render_footer(left_text=_footer_left(residue),
                                   right_text=_footer_right(residue))
            print(render_output(preamble=preamble, trace=trace, footer=footer))


def _cmd_compare(args):
    from husks.report import compare_artifacts, read_history
    sites = args.sites
    if len(sites) < 2:
        print("husks compare: need at least 2 site directories.", file=sys.stderr); sys.exit(EXIT_USAGE)
    check_roots = not getattr(args, "hashes_only", False)
    check_hashes = not getattr(args, "roots_only", False)
    json_mode = getattr(args, "json_output", False)

    # Build site residues for visual output.
    residues = []
    for site in sites:
        r, _ = _build_site_residue(site)
        if r is None:
            print(f"husks: no manifest in {site}/.traces/ — has this site been built?", file=sys.stderr)
            sys.exit(EXIT_BUILD_FAIL)
        residues.append(r)

    # Pairwise artifact comparisons.
    # For three sites (M1, M2, M3):
    #   M1↔M2 = cache equivalence: root equality + all output hashes strict
    #   M1↔M3 = acceptance equivalence: root validity only, skip free outputs
    #   M2↔M3 = observational: same params as M1↔M3, not proof-bearing
    all_equiv = True
    results = []
    is_three = len(sites) == 3
    for i in range(len(sites)):
        for j in range(i + 1, len(sites)):
            if is_three and i == 0 and j == 1:
                ctype = "cache"
                r = compare_artifacts(
                    sites[i], sites[j],
                    check_root_equality=check_roots, check_root_validity=check_roots,
                    check_hashes=check_hashes, respect_free=False,
                )
            elif is_three:
                ctype = "realization" if (i == 0 and j == 2) else "observational"
                # Independent realization: compare non-free hashes only.
                # Root validity is checked per-site in _three_machine_checks.
                r = compare_artifacts(
                    sites[i], sites[j],
                    check_root_equality=False, check_root_validity=False,
                    check_hashes=check_hashes, respect_free=True,
                )
            else:
                ctype = "pairwise"
                r = compare_artifacts(
                    sites[i], sites[j],
                    check_root_equality=check_roots, check_root_validity=check_roots,
                    check_hashes=check_hashes, respect_free=False,
                )
            r["site_a"], r["site_b"] = sites[i], sites[j]
            r["comparison_type"] = ctype
            results.append(r)
            if not r["equivalent"]: all_equiv = False

    # Three-machine proof checks (when exactly 3 sites: M1, M2, M3).
    proof_checks = []
    if len(sites) == 3:
        proof_checks = _three_machine_checks(residues, results)

    proof_satisfied = all(c[1] for c in proof_checks if c[2]) if proof_checks else True

    if json_mode:
        out = {"equivalent": all_equiv, "comparisons": results}
        if proof_checks:
            out["proof"] = {"satisfied": proof_satisfied,
                            "checks": [{"label": c[0], "ok": c[1], "required": c[2]}
                                        for c in proof_checks]}
        print(json.dumps(out, indent=2))
    else:
        _render_compare_visual(residues, results, proof_checks, proof_satisfied)
    if proof_checks and not proof_satisfied:
        sys.exit(EXIT_BUILD_FAIL)
    if not all_equiv and not (proof_checks and proof_satisfied):
        sys.exit(EXIT_BUILD_FAIL)


def _three_machine_checks(residues, comparisons):
    """Run three-machine proof checks.  Returns list of (label, passed, required) tuples.
    Proof is satisfied when all required checks pass."""
    from husks.report import read_manifest
    from husks.kernel import recompute_root
    m1, m2, m3 = residues
    checks = []  # (label, passed, required)

    # Look up pairwise comparison results by site pair.
    def _pair(ra, rb):
        return next((r for r in comparisons
                     if {r["site_a"], r["site_b"]} == {ra.site, rb.site}), None)
    m1_m2 = _pair(m1, m2)
    m1_m3 = _pair(m1, m3)

    # Detect stub vs live: check oracle backend from manifest or history.
    is_stub = False
    for site in (m1.site, m3.site):
        mf = read_manifest(site)
        if mf and mf.get("oracle_backend") == "stub":
            is_stub = True
            break
    if not is_stub:
        # Fallback: check if all oracle nodes report zero cost (stub indicator)
        m1_oracles_pre = [n for n in m1.nodes if n.kind == "oracle"]
        if m1_oracles_pre and all((n.cost or 0.0) == 0.0 for n in m1_oracles_pre):
            is_stub = True

    # ── Required: structural invariants ───────────────────────
    husk_match = (m1.husk_hash is not None and m1.husk_hash == m2.husk_hash == m3.husk_hash)
    checks.append(("M1\u2194M2\u2194M3 husk identical", husk_match, True))

    root_match = (m1.root is not None and m1.root == m2.root)
    checks.append(("M1\u2194M2 root identical", root_match, True))

    # ── Required: per-site root validity ──────────────────────
    # Computed independently from pairwise comparisons.
    for label, res in [("M1", m1), ("M2", m2), ("M3", m3)]:
        valid = False
        if res.root and res.site:
            mf = read_manifest(res.site)
            if mf:
                design_name = mf.get("name", "")
                hp = Path(res.site) / f"{design_name}.husk"
                if hp.exists():
                    try:
                        recomp = recompute_root(hp.read_bytes(), res.site)
                        valid = (recomp == res.root)
                    except Exception:
                        pass
        checks.append((f"{label} root valid", valid, True))

    # ── Required: oracle evidence ─────────────────────────────
    m1_oracles = [n for n in m1.nodes if n.kind == "oracle"]
    m2_oracles = [n for n in m2.nodes if n.kind == "oracle"]
    m3_oracles = [n for n in m3.nodes if n.kind == "oracle"]
    has_oracles = bool(m1_oracles)

    checks.append(("M1 fired oracles",
                    any(n.state == "fired" and not n.cache for n in m1_oracles) if m1_oracles else False,
                    has_oracles))
    checks.append(("M2 cache reuse",
                    any(n.cache or n.state == "cached" for n in m2_oracles),
                    has_oracles))
    checks.append(("M3 fired oracles",
                    any(n.state == "fired" and not n.cache for n in m3_oracles) if m3_oracles else False,
                    has_oracles))

    # ── Required: M1↔M3 acceptance equivalence ───────────────
    # Independent realization must agree on exact outputs (free outputs skipped).
    m1_m3_equiv = m1_m3["equivalent"] if m1_m3 else False
    checks.append(("M1\u2194M3 acceptance equivalent", m1_m3_equiv, True))

    # ── Required (live only): cost/fuel comparability ─────────
    if not is_stub and has_oracles:
        # Read cost_tolerance from manifest if available, else default.
        ct_ratio = [0.5, 2.0]
        for site in (m1.site,):
            mf = read_manifest(site)
            if mf:
                ct = mf.get("cost_tolerance", {})
                if isinstance(ct, dict) and "ratio" in ct:
                    ct_ratio = ct["ratio"]
                    break
        c1, c3 = m1.cost or 0.0, m3.cost or 0.0
        if c1 > 0 and c3 > 0:
            ratio = c3 / c1
            cost_ok = ct_ratio[0] <= ratio <= ct_ratio[1]
        else:
            cost_ok = True  # Can't compare if one is zero
        checks.append(("M1\u2194M3 cost comparable", cost_ok, True))

        f1, f3 = m1.fuel_used or 0, m3.fuel_used or 0
        if f1 > 0 and f3 > 0:
            fuel_ratio = f3 / f1
            fuel_ok = ct_ratio[0] <= fuel_ratio <= ct_ratio[1]
        else:
            fuel_ok = (f1 == f3)  # Both zero or both nonzero
        checks.append(("M1\u2194M3 fuel comparable", fuel_ok, True))

    # ── Observational ─────────────────────────────────────────
    checks.append(("M1 paid cost", (m1.cost or 0.0) > 0, False))
    checks.append(("M2 zero oracle cost", (m2.cost or 0.0) == 0.0, False))
    checks.append(("M3 paid cost", (m3.cost or 0.0) > 0, False))

    # Root convergence between M1 and M3 is observational only.
    roots_match = m1_m3.get("details", {}).get("roots_match", False) if m1_m3 else False
    checks.append(("M1\u2194M3 root convergence", roots_match, False))

    return checks


def _render_compare_visual(residues, comparisons, proof_checks, proof_satisfied=True):
    """Render compare output: site cards, pairwise checks, proof."""
    sep = f"  {DIM}{'\u2500' * (R - 2)}{RESET}"
    roles = ["M1", "M2", "M3"] if len(residues) == 3 else [f"S{i+1}" for i in range(len(residues))]

    # Render each site card.
    from husks.report import map_display_status
    for i, res in enumerate(residues):
        ds = map_display_status(res.status, "status")
        diamond = _diamond_stage(res)
        preamble = render_preamble(
            design_name=res.design_name, display_status=ds,
            diamond_stage=diamond, husk_hash=res.husk_hash,
            root=res.root, site=(roles[i] if roles[i] == res.site else f"{roles[i]}  {res.site}"),
            stage_label="status")
        tree = render_motif_tree(res.nodes, verbose=True)
        left = _footer_left(res)
        right = _footer_right(res)
        footer = render_footer(left_text=left, right_text=right)
        print(render_output(preamble=preamble, trace=tree, footer=footer))
        print()

    # Pairwise equivalence checks.
    print(f"  {BOLD}equivalence{RESET}")
    print(sep)
    _CTYPE_LABEL = {"cache": "cache", "realization": "realization", "observational": "observational", "pairwise": ""}
    for r in comparisons:
        sa, sb = r["site_a"], r["site_b"]
        sym = f"{GREEN}\u2713{RESET}" if r["equivalent"] else f"{RED}\u2717{RESET}"
        ctype = r.get("comparison_type", "")
        suffix = f"  {DIM}({_CTYPE_LABEL.get(ctype, ctype)}){RESET}" if ctype and ctype in _CTYPE_LABEL and _CTYPE_LABEL[ctype] else ""
        label = f"{sa} \u2261 {sb}{suffix}"
        print(f"  {sym} {label}")
        free_skipped = r.get("details", {}).get("free_skipped", [])
        for fs in free_skipped:
            print(f"    {DIM}{fs} (free, skipped){RESET}")
        for d in r["differences"]:
            print(f"    {DIM}{d}{RESET}")
    print(sep)
    overall = all(r["equivalent"] for r in comparisons)
    overall_sym = f"{GREEN}\u2713{RESET}" if overall else f"{RED}\u2717{RESET}"
    print(f"  {overall_sym} {'equivalent' if overall else 'not equivalent'}")
    print()

    # Three-machine proof (if 3 sites).
    if proof_checks:
        print(f"  {BOLD}three-machine proof{RESET}")
        print(sep)
        required = [(l, ok) for l, ok, req in proof_checks if req]
        evidence = [(l, ok) for l, ok, req in proof_checks if not req]
        for label, ok in required:
            sym = f"{GREEN}\u2713{RESET}" if ok else f"{RED}\u2717{RESET}"
            print(f"  {sym} {label}")
        if evidence:
            print(f"  {DIM}evidence{RESET}")
            for label, ok in evidence:
                sym = f"{GREEN}\u2713{RESET}" if ok else f"{RED}\u2717{RESET}"
                print(f"  {sym} {DIM}{label}{RESET}")
        print(sep)
        ps = f"{GREEN}\u2713{RESET}" if proof_satisfied else f"{RED}\u2717{RESET}"
        print(f"  {ps} {'proof satisfied' if proof_satisfied else 'proof NOT satisfied'}")


def _find_layers_toml() -> Optional[Path]:
    """Locate layers.toml: cwd and parents, then near the husks package."""
    for base in (Path.cwd(), *Path.cwd().parents):
        cand = base / "layers.toml"
        if cand.is_file():
            return cand
    try:
        import husks
        pkg = Path(husks.__file__).resolve().parent
        for base in (pkg, *pkg.parents):
            cand = base / "layers.toml"
            if cand.is_file():
                return cand
    except Exception:
        pass
    return None


def _arch_check() -> dict:
    """Verify intra-package imports target a strictly lower layer.

    Returns a report dict: {status, layers_file, violations, unassigned,
    modules}.  status is 'ok', 'violations', or 'unavailable'.
    """
    import ast

    toml_path = _find_layers_toml()
    if toml_path is None:
        return {"status": "unavailable",
                "detail": "layers.toml not found (run from a source checkout)"}
    try:
        try:
            import tomllib as _toml
        except ModuleNotFoundError:
            import tomli as _toml  # type: ignore
        with open(toml_path, "rb") as fh:
            layers = _toml.load(fh).get("layers", {})
    except Exception as e:  # noqa: BLE001
        return {"status": "unavailable", "detail": f"cannot read {toml_path}: {e}"}

    try:
        import husks
        pkg_dir = Path(husks.__file__).resolve().parent
    except Exception as e:  # noqa: BLE001
        return {"status": "unavailable", "detail": f"cannot locate husks package: {e}"}

    def _module_imports(src: str) -> set[str]:
        out: set[str] = set()
        for node in ast.walk(ast.parse(src)):
            targets: list[str] = []
            if isinstance(node, ast.ImportFrom) and node.module and node.module.startswith("husks"):
                targets.append(node.module)
            elif isinstance(node, ast.Import):
                targets += [a.name for a in node.names if a.name.startswith("husks")]
            for t in targets:
                parts = t.split(".")
                out.add(".".join(parts[:2]) if len(parts) >= 2 else t)
        return out

    violations: list[dict] = []
    unassigned: list[str] = []
    present = sorted(p.stem for p in pkg_dir.glob("*.py") if p.stem != "__init__")
    for stem in present:
        mod = f"husks.{stem}"
        if mod not in layers:
            unassigned.append(mod)
            continue
        src_file = pkg_dir / f"{stem}.py"
        for dep in sorted(_module_imports(src_file.read_text())):
            if dep == mod or dep not in layers:
                continue
            if layers[dep] >= layers[mod]:
                violations.append({"module": mod, "module_layer": layers[mod],
                                   "imports": dep, "import_layer": layers[dep]})

    status = "ok" if not violations and not unassigned else "violations"
    return {"status": status, "layers_file": str(toml_path),
            "violations": violations, "unassigned": unassigned,
            "modules": {f"husks.{s}": layers.get(f"husks.{s}") for s in present}}


def _cmd_doctor(args):
    json_mode = getattr(args, "json_output", False)
    arch_mode = getattr(args, "arch", False)
    # Basic environment checks
    checks = []
    try:
        import husks.kernel  # noqa: F401
        checks.append({"name": "kernel", "ok": True, "detail": "importable"})
    except Exception as e:
        checks.append({"name": "kernel", "ok": False, "detail": str(e)})
    try:
        import husks.locke  # noqa: F401
        checks.append({"name": "locke", "ok": True, "detail": "importable"})
    except Exception as e:
        checks.append({"name": "locke", "ok": False, "detail": str(e)})
    try:
        import husks.report  # noqa: F401
        checks.append({"name": "report", "ok": True, "detail": "importable"})
    except Exception as e:
        checks.append({"name": "report", "ok": False, "detail": str(e)})

    arch = _arch_check() if arch_mode else None

    if json_mode:
        out = {"checks": checks}
        if arch is not None:
            out["arch"] = arch
        print(json.dumps(out, indent=2))
    else:
        for c in checks:
            sym = "\u2713" if c["ok"] else "\u2717"
            print(f"  {sym} {c['name']:<20s} {c['detail']}")
        if arch is not None:
            if arch["status"] == "unavailable":
                print(f"  \u2014 arch                 {arch['detail']}")
            elif arch["status"] == "ok":
                n = len(arch["modules"])
                print(f"  \u2713 arch                 {n} modules, layer DAG clean")
            else:
                for v in arch["violations"]:
                    print(f"  \u2717 arch                 {v['module']} (L{v['module_layer']}) "
                          f"imports {v['imports']} (L{v['import_layer']})")
                for m in arch["unassigned"]:
                    print(f"  \u2717 arch                 {m} unassigned in layers.toml")

    failed = any(not c["ok"] for c in checks)
    if arch is not None and arch["status"] == "violations":
        sys.exit(EXIT_BUILD_FAIL)
    if failed:
        sys.exit(EXIT_MISSING_DEP)


def _cmd_cache_export(args):
    from husks.seal import fresh_store
    from husks.engine import cache_export as _export
    site = args.site
    if not Path(site).is_dir():
        print(f"husks: site not found: {site}", file=sys.stderr); sys.exit(EXIT_USAGE)
    export_path = args.file
    if not export_path.endswith(".tar.gz"):
        print("husks cache export: path must end with .tar.gz", file=sys.stderr); sys.exit(EXIT_USAGE)
    S = fresh_store(site, fuel=1)
    count = _export(S, export_path)
    if getattr(args, "json_output", False):
        print(json.dumps({"status": "exported", "site": site,
                          "file": export_path, "entries": count}, indent=2))
    elif getattr(args, "verbose", False):
        print(f"  exported {BOLD}{count}{RESET} entries {DIM}\u2192 {export_path}{RESET}")
    sys.exit(EXIT_OK)


def _cmd_cache_import(args):
    from husks.seal import fresh_store
    from husks.engine import cache_import as _import
    site = args.site
    import_path = args.file
    if not Path(import_path).is_file():
        print(f"husks cache import: file not found: {import_path}", file=sys.stderr); sys.exit(EXIT_USAGE)
    if not import_path.endswith(".tar.gz"):
        print("husks cache import: path must end with .tar.gz", file=sys.stderr); sys.exit(EXIT_USAGE)
    merge = not getattr(args, "no_merge", False)
    S = fresh_store(site, fuel=1)
    count = _import(S, import_path, merge=merge)
    if getattr(args, "json_output", False):
        print(json.dumps({"status": "imported", "site": site,
                          "file": import_path, "entries": count, "merge": merge}, indent=2))
    elif getattr(args, "verbose", False):
        print(f"  imported {BOLD}{count}{RESET} entries {DIM}\u2192 {site}{RESET}")
    sys.exit(EXIT_OK)


# ── §8a Tree command ─────────────────────────────────────────────

def _cmd_tree(args):
    """Show working directory overview: designs, sites, native files."""
    import os
    from husks.report import read_manifest

    cwd = Path(".")

    # ── Discover designs ──────────────────────────────────────
    designs: list[tuple[str, dict]] = []
    for pattern in ("*.locke", "*.json"):
        for p in sorted(cwd.glob(pattern)):
            try:
                from husks.locke import from_file, from_json as lk_from_json
                d = from_file(str(p)) if p.suffix == ".locke" else lk_from_json(str(p))
                designs.append((p.name, d))
            except Exception:
                continue

    # ── Discover sites ────────────────────────────────────────
    sites: list[tuple[str, dict]] = []
    dry_sites: list[str] = []
    for manifest_path in sorted(cwd.glob("*/.traces/build.manifest.json")):
        site_dir = manifest_path.parent.parent.name
        manifest = read_manifest(str(manifest_path.parent.parent))
        if manifest:
            sites.append((site_dir, manifest))
    built_site_names = {name for name, _ in sites}
    for cache_dir in sorted(cwd.glob("*/.cache")):
        site_dir = cache_dir.parent.name
        if site_dir not in built_site_names:
            dry_sites.append(site_dir)

    # ── Compute husk hashes per design ─────────────────────────
    import hashlib as _hl
    # design_name -> list of husk hashes (one per site that has the .husk file)
    husk_hashes: dict[str, list[str]] = {}
    for dir_name, manifest in sites:
        dname = manifest.get("name", "")
        if not dname:
            continue
        hp = cwd / dir_name / f"{dname}.husk"
        if hp.is_file():
            h = _hl.sha256(hp.read_bytes()).hexdigest()
            husk_hashes.setdefault(dname, []).append(h)
    # A design is a three-machine contender if 3+ sites share the same husk hash
    from collections import Counter
    three_machine_contenders: set[str] = set()
    for dname, hashes in husk_hashes.items():
        counts = Counter(hashes)
        if counts.most_common(1)[0][1] >= 3:
            three_machine_contenders.add(dname)

    # ── Build input usage map ─────────────────────────────────
    # Maps source path -> list of design names that reference it
    input_usage: dict[str, list[str]] = {}
    for design_name, design in designs:
        si = design.get("site_inputs", {})
        if isinstance(si, list):
            si = {s: s for s in si}
        for _local, source in si.items():
            input_usage.setdefault(source, []).append(design_name)

    # ── Discover native files ─────────────────────────────────
    design_files = {name for name, _ in designs}
    site_dirs = {name for name, _ in sites} | set(dry_sites)
    skip_dirs = site_dirs | {".git", "__pycache__", ".traces"}

    native_files: list[str] = []
    for dirpath, dirnames, filenames in os.walk("."):
        # Prune hidden dirs and skip dirs
        dirnames[:] = [d for d in dirnames if not d.startswith(".") and d not in skip_dirs]
        dirnames.sort()
        rel_dir = os.path.relpath(dirpath, ".")
        for f in sorted(filenames):
            if f.startswith("."):
                continue
            rel = os.path.join(rel_dir, f) if rel_dir != "." else f
            if rel in design_files:
                continue
            native_files.append(rel)

    # ── Print designs ─────────────────────────────────────────
    if designs:
        for name, design in designs:
            si = design.get("site_inputs", {})
            if isinstance(si, list):
                si = {s: s for s in si}
            if si and all(Path(source).exists() for source in si.values()):
                mark = f"{GREEN}\u2713{RESET}"
            elif si:
                missing = [s for s in si.values() if not Path(s).exists()]
                mark = f"{RED}\u2717{RESET} {DIM}missing {', '.join(missing)}{RESET}"
            else:
                mark = ""
            dname = design.get("name", "")
            if dname in three_machine_contenders:
                mark = f"{CYAN}\u25c8{RESET} {mark}" if mark else f"{CYAN}\u25c8{RESET}"
            print(f"  {BOLD}{name}{RESET}  {mark}")
        print()

    # ── Print sites ───────────────────────────────────────────
    if sites or dry_sites:
        for dir_name, manifest in sites:
            status = manifest.get("status", "unknown")
            root = manifest.get("root", "")
            root_short = root[:12] + "\u2026" if len(root) > 12 else root
            sc = STATE_COLORS.get(status, DIM)
            print(f"  {BOLD}{dir_name}/{RESET}  {sc}{status}{RESET}  {DIM}{root_short}{RESET}")
        for dir_name in dry_sites:
            print(f"  {BOLD}{dir_name}/{RESET}  {DIM}dry{RESET}")
        print()

    # ── Print native file tree ────────────────────────────────
    if native_files:
        printed_dirs: set[str] = set()
        for rel in native_files:
            parts = rel.split(os.sep)
            # Print directory headers
            if len(parts) > 1:
                dir_path = os.sep.join(parts[:-1])
                if dir_path not in printed_dirs:
                    printed_dirs.add(dir_path)
                    print(f"  {BOLD}{dir_path}/{RESET}")

            filename = parts[-1]
            indent = "    " if len(parts) > 1 else "  "
            ref_count = len(input_usage.get(rel, []))
            if ref_count == 1:
                color = GREEN
            elif ref_count > 1:
                color = BLUE
            else:
                color = DIM
            print(f"{indent}{color}{filename}{RESET}")


# ── §8 Main ─────────────────────────────────────────────────────

def main():
    p = argparse.ArgumentParser(prog="husks", description="Husks design CLI", add_help=False)
    p.add_argument("-h", "--help", action="store_true", default=False)
    p.add_argument("--color", choices=["auto", "always", "never"], default="auto")
    p.add_argument("--quiet", "-q", action="store_true")
    p.add_argument("--version", action="store_true")

    sub = p.add_subparsers(dest="cmd")

    # check
    c = sub.add_parser("check")
    c.add_argument("design", nargs="?", default=None)
    c_out = c.add_mutually_exclusive_group()
    c_out.add_argument("--verbose", "-v", action="store_true")
    c_out.add_argument("--json", action="store_true", dest="json_output")

    # run
    r = sub.add_parser("run")
    r.add_argument("design", nargs="?", default=None)
    r.add_argument("--site")
    r.add_argument("--model", default="anthropic/claude-haiku-4-5-20251001")
    r.add_argument("--stub", action="store_true")
    r.add_argument("--backend", choices=["litellm", "claude-code"], default="litellm")
    r.add_argument("--reuse-only", action="store_true")
    r.add_argument("--unsafe", action="store_true")
    r.add_argument("--soft-fail", action="store_true")
    r_out = r.add_mutually_exclusive_group()
    r_out.add_argument("--verbose", "-v", action="store_true")
    r_out.add_argument("--json", action="store_true", dest="json_output")
    r.add_argument("--report-json", metavar="PATH")

    # status
    st = sub.add_parser("status")
    st.add_argument("site")
    st.add_argument("--json", action="store_true", dest="json_output")
    st.add_argument("--verbose", "-v", action="store_true")
    st.add_argument("--fail-if-dirty", action="store_true")
    st.add_argument("--fail-if-stale", action="store_true")

    # history
    h = sub.add_parser("history")
    h.add_argument("site")
    h.add_argument("rule", nargs="?", default=None)
    h.add_argument("-n", type=int, default=5)
    h.add_argument("--json", action="store_true", dest="json_output")

    # verify
    v = sub.add_parser("verify")
    v.add_argument("site")
    v.add_argument("--name")
    v.add_argument("--verbose", "-v", action="store_true")
    v.add_argument("--json", action="store_true", dest="json_output")

    # compare
    cmp = sub.add_parser("compare")
    cmp.add_argument("sites", nargs="+")
    cmp.add_argument("--json", action="store_true", dest="json_output")
    cmp.add_argument("--roots-only", action="store_true")
    cmp.add_argument("--hashes-only", action="store_true")

    # cache
    ca = sub.add_parser("cache")
    ca_sub = ca.add_subparsers(dest="cache_cmd")
    ca_exp = ca_sub.add_parser("export")
    ca_exp.add_argument("site")
    ca_exp.add_argument("file")
    ca_exp.add_argument("--verbose", "-v", action="store_true")
    ca_exp.add_argument("--json", action="store_true", dest="json_output")
    ca_imp = ca_sub.add_parser("import")
    ca_imp.add_argument("file")
    ca_imp.add_argument("site")
    ca_imp.add_argument("--no-merge", action="store_true")
    ca_imp.add_argument("--verbose", "-v", action="store_true")
    ca_imp.add_argument("--json", action="store_true", dest="json_output")

    # doctor
    doc = sub.add_parser("doctor")
    doc.add_argument("--json", action="store_true", dest="json_output")
    doc.add_argument("--arch", action="store_true",
                     help="Verify the module import DAG against layers.toml")

    # tree
    sub.add_parser("tree")

    args, unknown = p.parse_known_args()

    if args.help:
        print(emit_help(_version())); sys.exit(EXIT_OK)
    if args.version:
        print(f"husks {_version()}"); sys.exit(EXIT_OK)
    if args.cmd is None:
        print(emit_help(_version())); sys.exit(EXIT_USAGE)

    # Catch unrecognized arguments with contextual hints
    if unknown:
        # Common mistake: positional site arg instead of --site
        if args.cmd == "run" and len(unknown) == 1 and not unknown[0].startswith("-"):
            site_guess = unknown[0]
            print(f"husks run: '{site_guess}' is not a flag. Did you mean --site {site_guess}?", file=sys.stderr)
            print(f"  husks run <design> --site {site_guess}", file=sys.stderr)
            sys.exit(EXIT_USAGE)
        print(f"husks {args.cmd}: unrecognized arguments: {' '.join(unknown)}", file=sys.stderr)
        sys.exit(EXIT_USAGE)

    # Design-loading commands
    if args.cmd in ("check", "run"):
        design_path = resolve_design(args)
        args.design = design_path
        try:
            from husks.locke import from_file, from_json as lk_from_json
            design = from_file(design_path) if design_path.endswith(".locke") else lk_from_json(design_path)
        except Exception as e:
            if getattr(args, "json_output", False):
                print(json.dumps({"status": "error", "error": str(e)}))
            else:
                print(f"husks {args.cmd}: cannot load design: {e}", file=sys.stderr)
            sys.exit(EXIT_USAGE)
        if args.cmd == "check":
            _cmd_check(args, design)
        elif args.cmd == "run":
            if not args.site:
                args.site = f"/tmp/husks-{design.get('name', 'unnamed')}"
            _cmd_run(args, design)
    elif args.cmd == "status":
        _cmd_status(args)
    elif args.cmd == "history":
        _cmd_history(args)
    elif args.cmd == "verify":
        _cmd_verify(args)
    elif args.cmd == "compare":
        _cmd_compare(args)
    elif args.cmd == "cache":
        if getattr(args, "cache_cmd", None) == "export":
            _cmd_cache_export(args)
        elif getattr(args, "cache_cmd", None) == "import":
            _cmd_cache_import(args)
        else:
            print("husks cache: specify 'export' or 'import'.", file=sys.stderr); sys.exit(EXIT_USAGE)
    elif args.cmd == "doctor":
        _cmd_doctor(args)
    elif args.cmd == "tree":
        _cmd_tree(args)


def _cli_entry():
    """Top-level exception handler."""
    try:
        main()
    except KeyboardInterrupt:
        print("\nInterrupted", file=sys.stderr); sys.exit(130)
    except SystemExit:
        raise
    except Exception as e:
        verbose = "--verbose" in sys.argv or "-v" in sys.argv
        if verbose:
            import traceback; traceback.print_exc()
        else:
            print(f"husks: {type(e).__name__}: {e}", file=sys.stderr)
        sys.exit(EXIT_INTERNAL)


if __name__ == "__main__":
    _cli_entry()
