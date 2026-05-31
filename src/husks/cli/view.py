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


def render_dag(residue: CliResidue, *, verbose: bool = False) -> str:
    """Render target-rooted DAG in bounded box.

    Parameters
    ----------
    residue : CliResidue
        Residue from check, run, or status command
    verbose : bool
        Show bounded box (False = silent for passing check)

    Returns
    -------
    str
        Formatted visual output with ANSI colors
    """
    # check without verbose: silent on success
    if residue.command == "check" and not verbose:
        return ""

    lines = []
    separator = "─" * 60

    # Beta 100: Bounded CSE block format
    status_display = _map_visual_status(residue.status, residue.command)

    # CSE path and root
    cse_display = residue.cse_path if residue.cse_path else "none"
    root_display = f"root:{residue.root[:7]}" if residue.root else ""

    # Site
    site_display = residue.site if residue.site else "none"

    # Fuel
    fuel_display = f"⚡{residue.fuel_used}/{residue.fuel_budget}" if residue.fuel_budget > 0 else ""

    # Header section - Beta 100 format
    lines.append(separator)

    # Line 1: <name> <status> <fuel>
    line1_parts = [f" {residue.design_name}"]
    line1_parts.append(" " * (20 - len(residue.design_name)))  # Pad to column 20
    line1_parts.append(status_display)
    if fuel_display:
        # Right-align fuel
        current_len = len(residue.design_name) + 1 + len(status_display) + 21
        padding_needed = max(1, 60 - current_len - len(fuel_display))
        line1_parts.append(" " * padding_needed)
        line1_parts.append(fuel_display)
    lines.append("".join(line1_parts))

    # Line 2: cse:<path> <root>
    line2 = f" cse:{cse_display}"
    if root_display:
        line2 += f" {root_display}"
    lines.append(line2)

    # Line 3: site:<name>
    lines.append(f" site:{site_display}")

    lines.append(separator)

    # Tree: target-rooted (between separators)
    tree_lines = _render_tree(residue.nodes, verbose)
    lines.extend(tree_lines)
    lines.append(separator)

    # Footer: conformance status
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


def _render_tree(nodes: list[CliNode], verbose: bool) -> list[str]:
    """Render target-rooted dependency tree."""
    if not nodes:
        return []

    # Build dependency map
    nodes_by_name = {n.name: n for n in nodes}

    # Target is first in list (already reordered by collectors)
    target = nodes[0]

    # Render tree recursively from target
    lines = []
    _render_node_tree(target, nodes_by_name, lines, "", verbose, is_last=True)
    return lines


def _render_node_tree(
    node: CliNode,
    nodes_by_name: dict,
    lines: list,
    prefix: str,
    verbose: bool,
    is_last: bool = True
):
    """Recursively render node and children."""
    glyph = STATE_GLYPHS.get(node.state, "□")
    color = STATE_COLORS.get(node.state, RESET)

    # Node line: glyph + name + kind + metadata (table-aligned)
    metadata_parts = []

    # Add time/fuel/cost
    if node.duration is not None:
        metadata_parts.append(f"{node.duration:.2f}s")

    if node.fuel is not None:
        metadata_parts.append(f"⚡{node.fuel}")

    if node.cost is not None and node.cost > 0:
        metadata_parts.append(f"${node.cost:.4f}")
    elif node.cache:
        metadata_parts.append("⚡0  $0.0000")

    if node.fuel_budget is not None:
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

    # Build name field with padding to reach column 2
    full_prefix = prefix + connector
    name_field = f"{full_prefix}{color}{glyph}{RESET} {node.name}"

    # Get children for later rendering
    children_names = getattr(node, 'children', [])

    # Calculate visible length (excluding ANSI codes)
    visible_len = len(full_prefix) + 1 + 1 + len(node.name)  # prefix + glyph + space + name
    padding = max(1, 28 - visible_len)  # At least 1 space

    # Add space before metadata to align with header fuel column
    metadata_str = f" {metadata}" if metadata else ""
    node_line = f" {name_field}{' ' * padding}{node.kind:<15s}{metadata_str}"
    lines.append(node_line.rstrip())

    # Beta 100: Show outputs (always, not just verbose)
    if node.outputs:
        detail_prefix = full_prefix + ("   " if is_last else "│  ")
        for output in node.outputs:
            hash_short = output.sha256[:6] if output.sha256 else "??????"
            lines.append(f"      out:{output.path}@{hash_short}")

    # Verbose: add trace and error details
    if verbose:
        detail_prefix = full_prefix + ("   " if is_last else "│  ")

        # Show trace drawer for oracle nodes
        if node.trace:
            trace = node.trace
            lines.append(f" {detail_prefix}trace:")
            if trace.backend:
                lines.append(f" {detail_prefix}  backend: {trace.backend}")
            if trace.model:
                lines.append(f" {detail_prefix}  model: {trace.model}")
            if trace.prompt_hash:
                lines.append(f" {detail_prefix}  prompt: sha256:{trace.prompt_hash[:6]}")
            if trace.input_tokens > 0:
                lines.append(f" {detail_prefix}  input_tokens: {trace.input_tokens}")
            if trace.output_tokens > 0:
                lines.append(f" {detail_prefix}  output_tokens: {trace.output_tokens}")
            if trace.elapsed_s is not None:
                lines.append(f" {detail_prefix}  elapsed: {trace.elapsed_s:.2f}s")
            if trace.cost_usd > 0:
                lines.append(f" {detail_prefix}  cost: ${trace.cost_usd:.4f}")
            if trace.stdout:
                stdout_preview = trace.stdout[:100] + "..." if len(trace.stdout) > 100 else trace.stdout
                lines.append(f" {detail_prefix}  stdout: {stdout_preview}")
            if trace.stderr:
                stderr_preview = trace.stderr[:100] + "..." if len(trace.stderr) > 100 else trace.stderr
                lines.append(f" {detail_prefix}  stderr: {stderr_preview}")

        # Show stale reason or diagnosis
        if node.stale_reason:
            lines.append(f" {detail_prefix}reason: {node.stale_reason}")
        if node.diagnosis:
            # Show full diagnosis without truncation
            lines.append(f" {detail_prefix}error: {node.diagnosis}")

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
