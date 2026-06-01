"""
CLI View layer - visual DAG renderer with unified grammar.

Beta Gate 95: One shared renderer for check, run, and status commands.

**Visual grammar:**
- State glyphs: □ unrealized, ■ sealed, ◆ cached, △ stale, ✕ failed, ◉ running
- Kind appears as text column, not glyph
- Target-rooted dependency tree
- Bounded box with header/footer

**Modes:**
- Concise: silent or bounded box
- Verbose: bounded box with tree
"""

from __future__ import annotations
from husks.cli.residue import CliResidue, CliNode
from husks.utils.console import GREEN, YELLOW, RED, CYAN, DIM, BOLD, RESET


# State glyphs (leading mark)
STATE_GLYPHS = {
    "unrealized": "□",
    "sealed": "■",
    "cached": "◆",
    "stale": "△",
    "failed": "✕",
    "running": "◉",
}

# State colors
STATE_COLORS = {
    "unrealized": DIM,
    "sealed": GREEN,
    "cached": CYAN,
    "stale": YELLOW,
    "failed": RED,
    "running": CYAN,
}


def render_dag(
    residue: CliResidue,
    *,
    verbose: bool = False,
    cursor: str = None,
    aperture: int = 1,
    controls: bool = False
) -> str:
    """Render target-rooted DAG in bounded box.

    Parameters
    ----------
    residue : CliResidue
        Residue from check, run, or status command
    verbose : bool
        Show bounded box (False = silent for passing check)
    cursor : str, optional
        Name of selected node (for explain mode)
    aperture : int, default=1
        Detail level for selected node (0-3)
    controls : bool, default=False
        Show controls footer (for explain mode)

    Returns
    -------
    str
        Formatted visual output with ANSI colors
    """
    # check without verbose: silent on success
    if residue.command == "check" and not verbose:
        return ""

    lines = []

    # Explain mode uses wider box and shows cursor/aperture
    is_explain = cursor is not None
    box_width = 40 if is_explain else 32
    separator = "─" * box_width

    # Beta 100: Bounded CSE block format
    status_display = _map_visual_status(residue.status, residue.command)

    # CSE path and root
    cse_display = residue.cse_path if residue.cse_path else "none"
    root_display = f"root:{residue.root[:7]}" if residue.root else ""

    # Site
    site_display = residue.site if residue.site else "none"

    # Fuel - shows budget only for dry check, used/budget for runs
    # Beta 100: For sealed runs, use oracle_calls if available
    if residue.fuel_budget > 0:
        if residue.status == "committed" and hasattr(residue, 'oracle_calls') and residue.oracle_calls > 0:
            # Sealed run with oracle_calls data: show oracle calls
            fuel_display = f"⚡{residue.oracle_calls}/{residue.fuel_budget}"
        elif residue.fuel_used > 0 or residue.command != "check":
            # Hydrated run: show used/budget
            fuel_display = f"⚡{residue.fuel_used}/{residue.fuel_budget}"
        else:
            # Dry check: show just budget
            fuel_display = f"⚡{residue.fuel_budget}"
    else:
        fuel_display = ""

    # Header section
    lines.append(separator)

    if is_explain:
        # Explain mode header: CSE.husk + root on line 1, site + cursor on line 2, aperture on line 3
        line1 = f" {cse_display}"
        if root_display:
            padding1 = max(2, box_width - len(line1) - len(root_display) - 1)
            line1 += f"{' ' * padding1}{root_display}"
        lines.append(line1)

        cursor_display = f"cursor:{cursor}" if cursor else ""
        line2 = f" site:{site_display}"
        if cursor_display:
            padding2 = max(2, box_width - len(line2) - len(cursor_display) - 1)
            line2 += f"{' ' * padding2}{cursor_display}"
        lines.append(line2)

        lines.append(f" aperture:{aperture}")
    else:
        # Status/run/check mode header: name + status + fuel on line 1
        line1_base = f" {residue.design_name}"
        padding1 = max(1, 22 - len(line1_base))
        line1 = f"{line1_base}{' ' * padding1}{status_display}"
        if fuel_display:
            padding2 = max(1, box_width - len(line1) - len(fuel_display))
            line1 += f"{' ' * padding2}{fuel_display}"
        lines.append(line1)

        # Line 2+: cse/root/site
        if root_display:
            # Sealed run: line 2 = cse + root, line 3 = site
            lines.append(f" cse:{cse_display} {root_display}")
            lines.append(f" site:{site_display}")
        else:
            # Dry/hydrating: line 2 = cse + site on same line
            cse_part = f" cse:{cse_display}"
            site_part = f"site:{site_display}"
            # Pad between cse and site to reach ~column 22
            padding = max(2, 22 - len(cse_part))
            lines.append(f"{cse_part}{' ' * padding}{site_part}")

    lines.append(separator)

    # Tree: target-rooted (between separators)
    tree_lines = _render_tree(residue.nodes, verbose, cursor, aperture)
    lines.extend(tree_lines)
    lines.append(separator)

    # Footer: conformance status or controls
    if controls:
        footer = " ↑↓ move   ←→ aperture   q quit"
    else:
        footer = _render_footer_status(residue)
    lines.append(footer)

    return "\n".join(lines)


def _map_visual_status(status: str, command: str) -> str:
    """Map residue status to visual display status."""
    if command == "check":
        return "checked" if status == "dry" else status
    elif status == "committed":
        return "sealed"
    elif status == "halted":
        return "failed"
    return status


def _render_tree(
    nodes: list[CliNode],
    verbose: bool,
    cursor: str = None,
    aperture: int = 1
) -> list[str]:
    """Render target-rooted dependency tree."""
    if not nodes:
        return []

    # Build dependency map
    nodes_by_name = {n.name: n for n in nodes}

    # Target is first in list (already reordered by collectors)
    target = nodes[0]

    # Render tree recursively from target
    lines = []
    _render_node_tree(target, nodes_by_name, lines, "", verbose, cursor, aperture, is_last=True)
    return lines


def _render_node_tree(
    node: CliNode,
    nodes_by_name: dict,
    lines: list,
    prefix: str,
    verbose: bool,
    cursor: str = None,
    aperture: int = 1,
    is_last: bool = True
):
    """Recursively render node and children."""
    glyph = STATE_GLYPHS.get(node.state, "□")
    color = STATE_COLORS.get(node.state, RESET)

    # Phase 4: Check if this node is selected
    is_selected = (cursor == node.name)

    # Node line: glyph + name + kind + metadata (table-aligned)
    metadata_parts = []

    # For cached nodes, show "cached" label
    if node.cache:
        metadata_parts.append("cached")

    # Add time/fuel/cost
    if node.duration is not None and node.duration > 0:
        metadata_parts.append(f"{node.duration:.2f}s")

    # For cached nodes, show explicit zero fuel and cost
    if node.cache:
        metadata_parts.append("⚡0")
        metadata_parts.append("$0.0000")
    else:
        # Non-cached nodes: show actual fuel and cost
        if node.fuel is not None:
            metadata_parts.append(f"⚡{node.fuel}")

        if node.cost is not None and node.cost > 0:
            metadata_parts.append(f"${node.cost:.4f}")

        # Show fuel budget for unrealized nodes
        if node.fuel_budget is not None and node.state == "unrealized":
            metadata_parts.append(f"⚡{node.fuel_budget}")

    metadata = "     ".join(metadata_parts) if metadata_parts else ""

    # Table alignment: fixed-width columns matching header
    # Column 1: prefix + glyph + name (25 chars total)
    # Column 2: kind (15 chars)
    # Column 3: metadata (variable, aligned with header fuel)

    # Add tree connector for non-root nodes
    connector = ""
    if prefix:  # Non-root nodes get connectors
        connector = "└─ " if is_last else "├─ "

    # Phase 4: Add cursor marker for selected node
    cursor_mark = "▶" if is_selected else ""

    # Build name field with padding to reach column 2
    full_prefix = prefix + connector
    name_field = f"{cursor_mark}{color}{glyph}{RESET} {node.name}"

    # Get children for later rendering
    children_names = getattr(node, 'children', [])

    # Calculate visible length (excluding ANSI codes and cursor marker)
    cursor_len = 1 if is_selected else 0
    visible_len = len(full_prefix) + cursor_len + 1 + 1 + len(node.name)  # prefix + cursor + glyph + space + name
    padding = max(1, 22 - visible_len)  # At least 1 space

    # Build node line with leading space for bounded box formatting
    metadata_str = f"     {metadata}" if metadata else ""
    node_line = f" {full_prefix}{name_field}{' ' * padding}{node.kind}{metadata_str}"
    lines.append(node_line.rstrip())

    # Phase 4: Aperture-aware detail rendering
    # Selected node expands to its aperture level, non-selected stay minimal

    # Determine effective aperture for this node
    if is_selected:
        node_aperture = aperture
    elif verbose:
        node_aperture = 3  # Verbose mode shows full details for all nodes
    else:
        node_aperture = 1  # Non-selected nodes show primary output only

    # Detail indent (no tree connectors in detail lines)
    if prefix:
        detail_indent = "      "  # Child node: 1 leading + 5 to align under node name
    else:
        detail_indent = "    "  # Root node: 1 leading + 3 to align under node name

    # Aperture 0: Node only (no details)
    if node_aperture == 0:
        pass  # No details rendered

    # Aperture 1+: Outputs
    elif node_aperture >= 1:
        if node.outputs:
            # Primary output only for aperture 1
            outputs_to_show = node.outputs[:1] if node_aperture == 1 else node.outputs
            for output in outputs_to_show:
                hash_short = output.sha256[:6] if output.sha256 else "??????"
                lines.append(f"{detail_indent}out:{output.path}@{hash_short}")

        # Aperture 2+: Seal and cache
        if node_aperture >= 2:
            # Seal section
            if node.seal_digest or node.recipe_digest:
                lines.append(f"{detail_indent}seal:")
                if node.seal_digest:
                    lines.append(f"{detail_indent}  digest: {node.seal_digest[:6]}")
                if node.recipe_digest:
                    lines.append(f"{detail_indent}  recipe: {node.recipe_digest[:6]}")
                if node.input_hashes:
                    lines.append(f"{detail_indent}  inputs: {len(node.input_hashes)}")
                if node.output_hashes:
                    lines.append(f"{detail_indent}  outputs: {len(node.output_hashes)}")

            # Cache section
            if node.trace and node.trace.cache_source:
                lines.append(f"{detail_indent}cache: {node.trace.cache_source}")

        # Aperture 3: Trace, log, error
        if node_aperture >= 3:
            # Trace section
            if node.trace:
                trace = node.trace
                lines.append(f"{detail_indent}trace:")
                if trace.backend:
                    lines.append(f"{detail_indent}  backend: {trace.backend}")
                if trace.model:
                    lines.append(f"{detail_indent}  model: {trace.model}")
                if trace.config_hash:
                    lines.append(f"{detail_indent}  config: sha256:{trace.config_hash[:6]}")
                if trace.prompt_hash:
                    lines.append(f"{detail_indent}  prompt: sha256:{trace.prompt_hash[:6]}")
                if trace.input_tokens > 0:
                    lines.append(f"{detail_indent}  input_tokens: {trace.input_tokens}")
                if trace.output_tokens > 0:
                    lines.append(f"{detail_indent}  output_tokens: {trace.output_tokens}")
                if trace.elapsed_s is not None:
                    lines.append(f"{detail_indent}  elapsed: {trace.elapsed_s:.2f}s")
                if trace.cost_usd > 0:
                    lines.append(f"{detail_indent}  cost: ${trace.cost_usd:.4f}")

            # Log section
            if node.trace:
                if node.trace.stdout:
                    lines.append(f"{detail_indent}stdout:")
                    stdout_lines = node.trace.stdout.split('\n')[:5]  # First 5 lines
                    for log_line in stdout_lines:
                        lines.append(f"{detail_indent}  {log_line}")
                if node.trace.stderr:
                    lines.append(f"{detail_indent}stderr:")
                    stderr_lines = node.trace.stderr.split('\n')[:5]  # First 5 lines
                    for log_line in stderr_lines:
                        lines.append(f"{detail_indent}  {log_line}")

            # Error section
            if node.stale_reason:
                lines.append(f"{detail_indent}stale: {node.stale_reason}")
            if node.diagnosis:
                lines.append(f"{detail_indent}error: {node.diagnosis}")

    # Render children (children_names already fetched above for leaf detection)
    children = [nodes_by_name[name] for name in children_names if name in nodes_by_name]

    # Children get an extended prefix with continuation character
    if children:
        # Extend prefix: add continuation from this level (not the connector)
        continuation = "   " if is_last else "│  "
        child_prefix = prefix + continuation

        for i, child in enumerate(children):
            is_last_child = (i == len(children) - 1)
            _render_node_tree(
                child,
                nodes_by_name,
                lines,
                child_prefix,
                verbose,
                cursor,
                aperture,
                is_last=is_last_child
            )


def _render_footer_status(residue: CliResidue) -> str:
    """Render footer with pass/fail status (Beta 100 format)."""
    # Beta 100: Simple pass/fail footer
    has_fails = residue.fails and len(residue.fails) > 0 if isinstance(residue.fails, list) else residue.fails > 0

    if has_fails:
        # Build failure message
        fail_items = residue.fails if isinstance(residue.fails, list) else []
        if fail_items:
            message = f"failures in {', '.join(fail_items)}"
        else:
            message = "failed"
        return f" {message}"
    else:
        # Build success message
        pass_items = residue.passes if isinstance(residue.passes, list) else []
        if pass_items:
            message = f"passes: {', '.join(pass_items)}"
        else:
            message = "passed"
        return f" {message}"


# Unused legacy functions removed for Beta 100
