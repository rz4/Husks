"""
graph.py -- Dependency graph rendering for Husks designs.

Renders the rule dependency graph from a design IR in multiple formats:
text (indented tree), mermaid, dot (graphviz), and json.

Consumed by cli.py for the `husks graph` command.
"""

from __future__ import annotations

import json
from typing import Any


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
        nodes.append({"name": name, "kind": kind})

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


def _state_symbol(state: str | None) -> str:
    """Map a freshness state to a display symbol."""
    return {
        "fresh": "\u2713",
        "stale": "\u25b8",
        "missing": "\u2717",
        "dirty": "!",
        "failed": "\u2717",
    }.get(state or "", "")


def render_graph(
    design: dict[str, Any],
    fmt: str = "text",
    site: str | None = None,
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
    """
    nodes, edges = _extract_edges(design)

    # Optionally compute freshness states
    states: dict[str, str] = {}
    if site:
        try:
            from husks.manifest import read_manifest, read_seal, compute_rule_state
            manifest = read_manifest(site)
            if manifest:
                for rule in manifest.get("rules", []):
                    seal = read_seal(site, rule["name"])
                    st, _reason = compute_rule_state(site, rule, seal)
                    states[rule["name"]] = st
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
        return _render_text(nodes, edges, states, targets, design)


def _render_text(
    nodes: list[dict],
    edges: list[tuple[str, str]],
    states: dict[str, str],
    targets: set[str],
    design: dict[str, Any],
) -> str:
    """Render an indented tree view."""
    lines: list[str] = []
    name = design.get("name", "?")
    fuel = design.get("fuel", "?")
    lines.append(f"  {name}  (fuel {fuel})")
    lines.append(f"  {'─' * 40}")

    # Build children map
    children: dict[str, list[str]] = {}
    for src, dst in edges:
        children.setdefault(src, []).append(dst)

    # Find roots (nodes with no incoming edges)
    has_incoming = {dst for _, dst in edges}
    roots = [n["name"] for n in nodes if n["name"] not in has_incoming]
    if not roots:
        roots = [n["name"] for n in nodes]

    node_map = {n["name"]: n for n in nodes}
    visited: set[str] = set()

    def _walk(name: str, depth: int) -> None:
        if name in visited:
            lines.append(f"  {'  ' * depth}{name}  (ref)")
            return
        visited.add(name)
        nd = node_map.get(name)
        kind = nd["kind"] if nd else "?"
        st = states.get(name, "")
        sym = _state_symbol(st)
        target_tag = " \u25c0" if name in targets else ""
        state_tag = f" [{sym}{st}]" if st else ""
        lines.append(f"  {'  ' * depth}{name}  ({kind}){state_tag}{target_tag}")
        for child in children.get(name, []):
            _walk(child, depth + 1)

    for r in roots:
        _walk(r, 0)

    lines.append(f"  {'─' * 40}")
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
