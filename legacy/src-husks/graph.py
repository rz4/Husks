"""
graph.py -- Dependency graph rendering for Husks designs.

Renders the rule dependency graph from a design IR in multiple formats:
text (bordered tree), mermaid, dot (graphviz), and json.

Consumed by cli.py for the `husks explain` command.
"""

from __future__ import annotations

import json
import sys
from typing import Any

from husks.manifest import read_manifest, compute_rule_states

from husks.utils.console import DIM, BOLD, RESET, GREEN, YELLOW, RED, CYAN


def _extract_edges(design: dict[str, Any]) -> tuple[list[dict], list[tuple[str, str]]]:
    """Extract nodes and edges from a design's rules.

    Edges are inferred from input/output overlap: if rule B's inputs
    include a file produced by rule A's outputs, there is an edge A -> B.
    """
    rules = design.get("rules", [])
    nodes: list[dict] = []
    edges: list[tuple[str, str]] = []

    # Map output -> producing rule
    output_to_rule: dict[str, str] = {}
    for r in rules:
        kind = r.get("kind", "")
        if kind in ("action", "oracle", "trial"):
            for o in r.get("outputs", []):
                output_to_rule[o] = r["name"]

    for r in rules:
        kind = r.get("kind", "")
        name = r.get("name", "?")
        nodes.append({"name": name, "kind": kind, "fuel": r.get("fuel")})

        if kind in ("action", "oracle", "trial"):
            for inp in r.get("inputs", []):
                producer = output_to_rule.get(inp)
                if producer:
                    edges.append((producer, name))

        if kind == "cond":
            then_name = r.get("then")
            else_name = r.get("else")
            if then_name:
                edges.append((name, then_name))
            if else_name:
                edges.append((name, else_name))

        if kind == "let":
            bind = r.get("bind")
            if bind:
                edges.append((bind, name))

    return nodes, edges


# ── Symbols ──────────────────────────────────────────────────────

_STATE_SYM = {
    "fresh":   "■",
    "stale":   "▸",
    "missing": "✗",
    "dirty":   "!",
    "failed":  "✗",
}
_DEFAULT_SYM = "□"
_TRIAL_SYM = "◇"

_STATE_COLOR = {
    "fresh":   GREEN,
    "stale":   YELLOW,
    "missing": RED,
    "dirty":   RED,
    "failed":  RED,
}
_TRIAL_COLOR = CYAN


def _state_symbol(state: str | None) -> str:
    """Map a freshness state to a display symbol."""
    return _STATE_SYM.get(state or "", "")


def render_graph(
    design: dict[str, Any],
    fmt: str = "text",
    site: str | None = None,
    root_hash: str | None = None,
) -> str:
    """Render the design dependency graph in the requested format.

    Parameters
    ----------
    design : dict
        The design IR dict.
    fmt : str
        One of "text", "mermaid", "dot", "json".
    site : str, optional
        If provided, overlay freshness state symbols on nodes.
    root_hash : str, optional
        First 12 chars of the build root hash (for preamble display).
    """
    nodes, edges = _extract_edges(design)

    # Optionally compute freshness states
    states: dict[str, str] = {}
    if site:
        try:
            manifest = read_manifest(site)
            if manifest:
                for rs in compute_rule_states(site, manifest):
                    states[rs["name"]] = rs["state"]
        except Exception:
            pass

    targets = set()
    t = design.get("targets", design.get("target"))
    if isinstance(t, list):
        targets = set(t)
    elif isinstance(t, str):
        targets = {t}

    if fmt == "mermaid":
        return _render_mermaid(nodes, edges, states, targets)
    elif fmt == "dot":
        return _render_dot(nodes, edges, states, targets)
    elif fmt == "json":
        return _render_json(nodes, edges, states)
    else:
        return _render_text(nodes, edges, states, targets, design, root_hash)


def _render_text(
    nodes: list[dict],
    edges: list[tuple[str, str]],
    states: dict[str, str],
    targets: set[str],
    design: dict[str, Any],
    root_hash: str | None = None,
) -> str:
    """Render a bordered DAG tree with connectors.

    Target at top, dependencies grow downward.  Bordered with
    horizontal rules; preamble shows build name, fuel, and root hash.
    Diamond nodes (shared deps) get merge-line visuals.
    """
    lines: list[str] = []

    build_name = design.get("name", "?")
    build_fuel = design.get("fuel", "?")
    hash_label = f"husk:{root_hash[:12]}" if root_hash else "husk:none"

    # ── Preamble ─────────────────────────────────────────────
    fuel_str = f"\u26a1{build_fuel}"
    preamble_inner = f" {BOLD}{build_name}{RESET}  {fuel_str}"
    # Compute display width (without ANSI escapes) for padding
    preamble_plain = f" {build_name}  {fuel_str}"
    # Minimum rule width — ensure hash_label fits with padding
    min_width = max(len(preamble_plain) + len(hash_label) + 4, 40)

    gap = min_width - len(preamble_plain) - len(hash_label) - 1
    if gap < 2:
        gap = 2
    preamble_line = f"{preamble_inner}{' ' * gap}{hash_label}"

    rule = "\u2500" * (min_width + 1)
    lines.append(rule)
    lines.append(preamble_line)
    lines.append(rule)

    # ── Build graph structures ───────────────────────────────
    node_map = {n["name"]: n for n in nodes}

    # deps: consumer -> [producers] (reverse of edges)
    deps: dict[str, list[str]] = {}
    for src, dst in edges:
        deps.setdefault(dst, []).append(src)

    # Identify target nodes
    targets_list = [t for t in targets if t in node_map]
    if not targets_list:
        has_consumer = {src for src, _ in edges}
        targets_list = [n["name"] for n in nodes if n["name"] not in has_consumer]
    if not targets_list:
        targets_list = [n["name"] for n in nodes]

    # ── Diamond detection (pre-pass) ─────────────────────────
    parent_count: dict[str, int] = {}

    def _count_parents(name: str, seen: set[str]) -> None:
        if name in seen:
            return
        seen.add(name)
        for child in deps.get(name, []):
            parent_count[child] = parent_count.get(child, 0) + 1
            _count_parents(child, seen)

    for t in targets_list:
        _count_parents(t, set())

    diamonds = {n for n, c in parent_count.items() if c > 1}
    diamond_visits: dict[str, int] = {n: 0 for n in diamonds}

    # ── Tree walk with connectors ────────────────────────────
    visited: set[str] = set()

    def _sym_str(name: str) -> str:
        nd = node_map.get(name)
        kind = nd["kind"] if nd else "?"
        st = states.get(name, "")

        if kind == "trial" and not st:
            sym, color = _TRIAL_SYM, _TRIAL_COLOR
        elif st:
            sym = _STATE_SYM.get(st, _DEFAULT_SYM)
            color = _STATE_COLOR.get(st, "")
        else:
            sym, color = _DEFAULT_SYM, DIM

        if color:
            return f"{color}{sym}{RESET}"
        return sym

    def _node_line(name: str) -> str:
        nd = node_map.get(name)
        kind = nd["kind"] if nd else "?"
        sym = _sym_str(name)

        fuel_tag = ""
        if nd and nd.get("fuel") is not None and nd["fuel"] != build_fuel:
            fuel_tag = f"  \u26a1{nd['fuel']}"

        target_tag = "  \u25c0" if name in targets else ""
        return f"{sym} {name}  ({kind}){fuel_tag}{target_tag}"

    def _walk(name: str, prefix: str, is_last: bool, depth: int) -> None:
        # Connector for this node
        if depth == 0:
            connector = ""
            child_prefix = prefix
        elif is_last:
            connector = "\u2514\u2500 "
            child_prefix = prefix + "   "
        else:
            connector = "\u251c\u2500 "
            child_prefix = prefix + "\u2502  "

        lines.append(f" {prefix}{connector}{_node_line(name)}")
        visited.add(name)

        children = deps.get(name, [])
        for i, child in enumerate(children):
            last = (i == len(children) - 1)

            # Diamond handling
            if child in diamonds:
                diamond_visits[child] += 1
                if diamond_visits[child] < parent_count[child]:
                    # Not the last parent — emit deferred merge connector
                    merge_conn = "\u2514\u2500\u2510" if last else "\u251c\u2500\u2510"
                    lines.append(f" {child_prefix}{merge_conn}")
                    continue
                else:
                    # Last parent — emit merge join, then render subtree
                    merge_conn = "\u2514\u2500\u2524" if last else "\u251c\u2500\u2524"
                    lines.append(f" {child_prefix}{merge_conn}")
                    merge_indent = child_prefix + ("   " if last else "\u2502  ")
                    _walk(child, merge_indent, True, depth + 1)
                    continue

            if child in visited:
                # Already rendered — show as ref
                ref_conn = "\u2514\u2500 " if last else "\u251c\u2500 "
                lines.append(f" {child_prefix}{ref_conn}{child}  (ref)")
                continue

            _walk(child, child_prefix, last, depth + 1)

    for t in targets_list:
        _walk(t, "", True, 0)

    # Walk any nodes not reachable from targets
    for n in nodes:
        if n["name"] not in visited:
            _walk(n["name"], "", True, 0)

    # ── Footer ───────────────────────────────────────────────
    lines.append(rule)

    return "\n".join(lines)


def _render_mermaid(
    nodes: list[dict],
    edges: list[tuple[str, str]],
    states: dict[str, str],
    targets: set[str],
) -> str:
    lines = ["flowchart TD"]
    for n in nodes:
        name = n["name"]
        kind = n["kind"]
        st = states.get(name, "")
        sym = _state_symbol(st)
        label = f"{sym} {name}" if sym else name
        if name in targets:
            lines.append(f"    {name}[[\"{label} ({kind})\"]];")
        elif kind in ("commit", "halt"):
            lines.append(f"    {name}([\"{label} ({kind})\"])")
        else:
            lines.append(f"    {name}[\"{label} ({kind})\"]")
    for src, dst in edges:
        lines.append(f"    {src} --> {dst}")
    return "\n".join(lines)


def _render_dot(
    nodes: list[dict],
    edges: list[tuple[str, str]],
    states: dict[str, str],
    targets: set[str],
) -> str:
    lines = ["digraph husks {", "    rankdir=TB;"]
    for n in nodes:
        name = n["name"]
        kind = n["kind"]
        st = states.get(name, "")
        sym = _state_symbol(st)
        label = f"{sym} {name}\\n({kind})" if sym else f"{name}\\n({kind})"
        shape = "doubleoctagon" if name in targets else "box"
        lines.append(f'    "{name}" [label="{label}" shape={shape}];')
    for src, dst in edges:
        lines.append(f'    "{src}" -> "{dst}";')
    lines.append("}")
    return "\n".join(lines)


def _render_json(
    nodes: list[dict],
    edges: list[tuple[str, str]],
    states: dict[str, str],
) -> str:
    node_list = []
    for n in nodes:
        entry = {"name": n["name"], "kind": n["kind"]}
        if n["name"] in states:
            entry["state"] = states[n["name"]]
        node_list.append(entry)
    return json.dumps({
        "nodes": node_list,
        "edges": [{"from": s, "to": d} for s, d in edges],
    }, indent=2)
