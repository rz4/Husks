"""
CLI View layer - visual DAG renderer with unified grammar.

Beta Gate 95: One shared renderer for check, run, and status commands.

**Visual grammar:**
- Symbols: ◆ oracle, ▫ action, ◇ trial
- States: dry (dim), sealed (green), cached (cyan), stale (yellow), failed (red)
- Cache indicator: ⚡ (cyan) after cost for cached nodes
- Format: `◆ name kind state [⚡fuel $cost ⚡]`

**Modes:**
- Concise: one line per node with essential info
- Verbose: multi-line detail per node with inputs/outputs/diagnostics
"""

from __future__ import annotations
from husks.cli.residue import CliResidue, CliNode
from husks.utils.console import GREEN, YELLOW, RED, CYAN, DIM, BOLD, RESET


# Symbol mapping
KIND_SYMBOLS = {
    "oracle": "◆",
    "action": "▫",
    "trial": "◇",
}

# State colors
STATE_COLORS = {
    "dry": DIM,
    "sealed": GREEN,
    "cached": CYAN,
    "stale": YELLOW,
    "failed": RED,
}


def render_dag(residue: CliResidue, *, verbose: bool = False) -> str:
    """Render DAG tree with unified visual grammar.

    Parameters
    ----------
    residue : CliResidue
        Residue from check, run, or status command
    verbose : bool
        Show detailed multi-line output per node

    Returns
    -------
    str
        Formatted visual output with ANSI colors
    """
    lines = []

    # Header (if design name available)
    if residue.design_name and residue.design_name != "unknown":
        lines.append(f"\n  design: {BOLD}{residue.design_name}{RESET}")
        if residue.site:
            lines.append(f"  site:   {residue.site}")
        lines.append(f"  {'─' * 50}")
        lines.append("")

    # Render nodes
    for node in residue.nodes:
        if verbose:
            lines.extend(_render_node_verbose(node))
        else:
            lines.append(_render_node_concise(node))

    # Footer with status and summary
    lines.append(f"\n  {_render_footer(residue)}")
    lines.append("")

    return "\n".join(lines)


def _render_node_concise(node: CliNode) -> str:
    """Render one-line concise node representation."""
    symbol = KIND_SYMBOLS.get(node.kind, "▫")
    color = STATE_COLORS.get(node.state, RESET)

    # Base format: symbol name kind state
    parts = [f"{color}{symbol}{RESET}", node.name, node.kind, node.state]

    # Add fuel/cost if available (for run command)
    if node.fuel is not None or node.cost is not None or node.cache:
        fuel_str = f"⚡{node.fuel}" if node.fuel is not None else ""
        cost_str = f"${node.cost:.4f}" if node.cost is not None else ""

        # Cache indicator (show even if no cost)
        if node.cache:
            cache_indicator = f"{CYAN}⚡{RESET}"
            if fuel_str or cost_str:
                parts.append(f"{fuel_str} {cost_str} {cache_indicator}".strip())
            else:
                parts.append(cache_indicator)
        elif fuel_str or cost_str:
            parts.append(f"{fuel_str} {cost_str}".strip())

    return f"  {' '.join(parts)}"


def _render_node_verbose(node: CliNode) -> list[str]:
    """Render multi-line verbose node representation."""
    lines = []
    symbol = KIND_SYMBOLS.get(node.kind, "▫")
    color = STATE_COLORS.get(node.state, RESET)

    # Header line
    lines.append(f"  {color}{symbol}{RESET} {BOLD}{node.name}{RESET}  ({node.kind})")
    lines.append(f"     state:  {color}{node.state}{RESET}")

    # State-specific details
    if node.stale_reason:
        lines.append(f"     reason: {node.stale_reason}")

    if node.diagnosis:
        lines.append(f"     error:  {RED}{node.diagnosis}{RESET}")

    # Execution facts
    if node.fuel is not None:
        lines.append(f"     fuel:   {node.fuel}")

    if node.cost is not None:
        cache_note = f"  {CYAN}(cached){RESET}" if node.cache else ""
        lines.append(f"     cost:   ${node.cost:.4f}{cache_note}")

    if node.duration is not None:
        lines.append(f"     time:   {node.duration:.2f}s")

    if node.output_hash:
        lines.append(f"     hash:   {node.output_hash[:16]}...")

    lines.append("")  # Blank line after each node in verbose mode
    return lines


def _render_footer(residue: CliResidue) -> str:
    """Render footer with status, summary, fuel, and cost."""
    parts = []

    # Status
    status_color = GREEN if residue.status == "committed" else (YELLOW if residue.status == "halted" else DIM)
    parts.append(f"{status_color}{residue.status}{RESET}")

    # Root (if available)
    if residue.root:
        root_short = residue.root[:16] if len(residue.root) > 16 else residue.root
        parts.append(f"root {root_short}")

    # Fuel
    if residue.fuel_budget > 0:
        fuel_str = f"fuel {residue.fuel_used}/{residue.fuel_budget}"
        parts.append(fuel_str)

    # Cost
    if residue.cost > 0:
        parts.append(f"${residue.cost:.4f}")

    # Summary (passes/fails)
    if residue.passes > 0 or residue.fails > 0:
        summary_parts = []
        if residue.passes > 0:
            summary_parts.append(f"{GREEN}{residue.passes} pass{RESET}")
        if residue.fails > 0:
            summary_parts.append(f"{RED}{residue.fails} fail{RESET}")
        parts.append(f"({', '.join(summary_parts)})")

    return "  ".join(parts)
