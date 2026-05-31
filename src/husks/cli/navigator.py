"""
Navigator model for explain command.

Provides cursor and aperture state over CliResidue without duplicating
the residue tree structure. The explain view is a piloted projection
of the same residue used by status.
"""

from __future__ import annotations
from dataclasses import dataclass
from typing import Optional

from husks.cli.residue import CliResidue, CliNode


# Aperture levels (detail expansion)
APERTURE_NODE = 0      # Node line only
APERTURE_OUTPUT = 1    # Node + primary output
APERTURE_SEAL = 2      # Node + outputs + seal/cache
APERTURE_TRACE = 3     # Node + outputs + seal + trace/log/error

APERTURE_MIN = 0
APERTURE_MAX = 3


@dataclass
class ExplainState:
    """Navigation state over a residue tree.

    Attributes:
        residue: The underlying CLI residue (same structure as status)
        order: Target-rooted traversal order for arrow-key navigation
        cursor: Name of the currently selected node
        aperture: Detail level for the selected node (0-3)
    """
    residue: CliResidue
    order: list[str]
    cursor: str
    aperture: int = APERTURE_OUTPUT


def create_explain_state(
    residue: CliResidue,
    cursor: Optional[str] = None,
    aperture: int = APERTURE_OUTPUT
) -> ExplainState:
    """Create ExplainState from residue.

    Parameters:
        residue: CLI residue from status or run
        cursor: Initial cursor position (defaults to target/first node)
        aperture: Initial aperture level (defaults to 1)

    Returns:
        ExplainState ready for navigation
    """
    # Build traversal order
    order = flatten_tree(residue)

    # Default cursor to target or first node
    if cursor is None:
        cursor = residue.target if residue.target else (order[0] if order else "")

    # Validate cursor is in tree
    if cursor not in order:
        cursor = order[0] if order else ""

    # Clamp aperture
    aperture = max(APERTURE_MIN, min(APERTURE_MAX, aperture))

    return ExplainState(
        residue=residue,
        order=order,
        cursor=cursor,
        aperture=aperture
    )


def flatten_tree(residue: CliResidue) -> list[str]:
    """Build target-rooted traversal order for navigation.

    The order follows a depth-first traversal from the target node,
    visiting dependencies in the order they appear in the children list.

    For core-bootstrap with target=validate depending on generate:
        ["validate", "generate"]

    Parameters:
        residue: CLI residue with nodes

    Returns:
        List of node names in traversal order
    """
    if not residue.nodes:
        return []

    # Build node lookup
    nodes_by_name = {n.name: n for n in residue.nodes}

    # Start at target (already first in residue.nodes list)
    target = residue.nodes[0]

    # Depth-first traversal
    order = []
    visited = set()

    def visit(node: CliNode):
        if node.name in visited:
            return
        visited.add(node.name)
        order.append(node.name)

        # Visit children in order
        for child_name in node.children:
            if child_name in nodes_by_name:
                visit(nodes_by_name[child_name])

    visit(target)

    return order


def move_cursor(state: ExplainState, direction: str) -> ExplainState:
    """Move cursor up or down in traversal order.

    Parameters:
        state: Current explain state
        direction: "up" or "down"

    Returns:
        New ExplainState with updated cursor
    """
    if not state.order:
        return state

    try:
        current_idx = state.order.index(state.cursor)
    except ValueError:
        # Cursor not in order, reset to first
        current_idx = 0

    if direction == "up":
        new_idx = max(0, current_idx - 1)
    elif direction == "down":
        new_idx = min(len(state.order) - 1, current_idx + 1)
    else:
        new_idx = current_idx

    return ExplainState(
        residue=state.residue,
        order=state.order,
        cursor=state.order[new_idx],
        aperture=state.aperture
    )


def select_node(state: ExplainState, node_name: str) -> ExplainState:
    """Jump cursor to specific node by name.

    Parameters:
        state: Current explain state
        node_name: Name of node to select

    Returns:
        New ExplainState with cursor at node_name (if valid)
    """
    if node_name not in state.order:
        # Invalid node name, return unchanged
        return state

    return ExplainState(
        residue=state.residue,
        order=state.order,
        cursor=node_name,
        aperture=state.aperture
    )


def set_aperture(state: ExplainState, level: int) -> ExplainState:
    """Set aperture level for selected node.

    Parameters:
        state: Current explain state
        level: New aperture level (0-3)

    Returns:
        New ExplainState with updated aperture
    """
    # Clamp to valid range
    level = max(APERTURE_MIN, min(APERTURE_MAX, level))

    return ExplainState(
        residue=state.residue,
        order=state.order,
        cursor=state.cursor,
        aperture=level
    )


def adjust_aperture(state: ExplainState, delta: int) -> ExplainState:
    """Adjust aperture level by delta.

    Parameters:
        state: Current explain state
        delta: Amount to change aperture (+1 or -1)

    Returns:
        New ExplainState with adjusted aperture
    """
    return set_aperture(state, state.aperture + delta)
