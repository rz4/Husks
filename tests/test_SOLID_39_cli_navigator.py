"""
Tests for explain navigator model.

Tests the pure navigation logic over CliResidue without requiring
interactive terminal or explain command execution.
"""

import pytest

from husks.cli.residue import CliResidue, CliNode
from husks.cli.navigator import (
    create_explain_state,
    flatten_tree,
    move_cursor,
    select_node,
    set_aperture,
    adjust_aperture,
    APERTURE_NODE,
    APERTURE_OUTPUT,
    APERTURE_SEAL,
    APERTURE_TRACE,
)


@pytest.fixture
def simple_residue():
    """Create a simple 2-node residue for testing."""
    nodes = [
        CliNode(
            name="validate",
            kind="action",
            state="sealed",
            children=["generate"]
        ),
        CliNode(
            name="generate",
            kind="oracle",
            state="sealed",
            children=[]
        )
    ]

    return CliResidue(
        command="status",
        design_name="core-bootstrap",
        site="m1",
        cse_path="core-bootstrap.husk",
        status="sealed",
        target="validate",
        fuel_budget=20,
        nodes=nodes,
        passes=["site"],
        fails=[]
    )


def test_flatten_tree_simple(simple_residue):
    """Flatten tree builds target-rooted traversal order."""
    order = flatten_tree(simple_residue)

    # Should start at target, then visit dependencies
    assert order == ["validate", "generate"]


def test_flatten_tree_empty():
    """Flatten tree handles empty residue."""
    residue = CliResidue(
        command="status",
        design_name="empty",
        site="test",
        cse_path="empty.husk",
        status="dry",
        target=None,
        fuel_budget=0,
        nodes=[],
        passes=[],
        fails=[]
    )

    order = flatten_tree(residue)
    assert order == []


def test_create_explain_state_defaults(simple_residue):
    """Create explain state defaults to target cursor and aperture 1."""
    state = create_explain_state(simple_residue)

    assert state.residue == simple_residue
    assert state.order == ["validate", "generate"]
    assert state.cursor == "validate"  # Target
    assert state.aperture == APERTURE_OUTPUT  # Default


def test_create_explain_state_custom_cursor(simple_residue):
    """Create explain state accepts custom cursor."""
    state = create_explain_state(simple_residue, cursor="generate")

    assert state.cursor == "generate"


def test_create_explain_state_invalid_cursor(simple_residue):
    """Create explain state falls back to target for invalid cursor."""
    state = create_explain_state(simple_residue, cursor="invalid")

    assert state.cursor == "validate"  # Falls back to target


def test_create_explain_state_custom_aperture(simple_residue):
    """Create explain state accepts custom aperture."""
    state = create_explain_state(simple_residue, aperture=APERTURE_TRACE)

    assert state.aperture == APERTURE_TRACE


def test_create_explain_state_clamps_aperture(simple_residue):
    """Create explain state clamps aperture to valid range."""
    state_low = create_explain_state(simple_residue, aperture=-1)
    assert state_low.aperture == APERTURE_NODE

    state_high = create_explain_state(simple_residue, aperture=10)
    assert state_high.aperture == APERTURE_TRACE


def test_move_cursor_down(simple_residue):
    """Move cursor down advances in traversal order."""
    state = create_explain_state(simple_residue, cursor="validate")

    new_state = move_cursor(state, "down")

    assert new_state.cursor == "generate"
    assert new_state.residue is state.residue  # Same residue
    assert new_state.aperture == state.aperture  # Unchanged


def test_move_cursor_up(simple_residue):
    """Move cursor up retreats in traversal order."""
    state = create_explain_state(simple_residue, cursor="generate")

    new_state = move_cursor(state, "up")

    assert new_state.cursor == "validate"


def test_move_cursor_clamps_at_start(simple_residue):
    """Move cursor up at start stays at first node."""
    state = create_explain_state(simple_residue, cursor="validate")

    new_state = move_cursor(state, "up")

    assert new_state.cursor == "validate"  # Stays at start


def test_move_cursor_clamps_at_end(simple_residue):
    """Move cursor down at end stays at last node."""
    state = create_explain_state(simple_residue, cursor="generate")

    new_state = move_cursor(state, "down")

    assert new_state.cursor == "generate"  # Stays at end


def test_select_node_valid(simple_residue):
    """Select node jumps to named node."""
    state = create_explain_state(simple_residue, cursor="validate")

    new_state = select_node(state, "generate")

    assert new_state.cursor == "generate"


def test_select_node_invalid(simple_residue):
    """Select node ignores invalid node name."""
    state = create_explain_state(simple_residue, cursor="validate")

    new_state = select_node(state, "invalid")

    assert new_state.cursor == "validate"  # Unchanged


def test_set_aperture_valid(simple_residue):
    """Set aperture changes detail level."""
    state = create_explain_state(simple_residue, aperture=APERTURE_OUTPUT)

    new_state = set_aperture(state, APERTURE_TRACE)

    assert new_state.aperture == APERTURE_TRACE


def test_set_aperture_clamps_low(simple_residue):
    """Set aperture clamps to minimum."""
    state = create_explain_state(simple_residue)

    new_state = set_aperture(state, -5)

    assert new_state.aperture == APERTURE_NODE


def test_set_aperture_clamps_high(simple_residue):
    """Set aperture clamps to maximum."""
    state = create_explain_state(simple_residue)

    new_state = set_aperture(state, 100)

    assert new_state.aperture == APERTURE_TRACE


def test_adjust_aperture_increase(simple_residue):
    """Adjust aperture increases by delta."""
    state = create_explain_state(simple_residue, aperture=APERTURE_OUTPUT)

    new_state = adjust_aperture(state, +1)

    assert new_state.aperture == APERTURE_SEAL


def test_adjust_aperture_decrease(simple_residue):
    """Adjust aperture decreases by delta."""
    state = create_explain_state(simple_residue, aperture=APERTURE_SEAL)

    new_state = adjust_aperture(state, -1)

    assert new_state.aperture == APERTURE_OUTPUT


def test_adjust_aperture_clamps(simple_residue):
    """Adjust aperture clamps at boundaries."""
    state = create_explain_state(simple_residue, aperture=APERTURE_NODE)

    # Can't go below 0
    new_state = adjust_aperture(state, -1)
    assert new_state.aperture == APERTURE_NODE

    # Can't go above 3
    state_high = create_explain_state(simple_residue, aperture=APERTURE_TRACE)
    new_state_high = adjust_aperture(state_high, +1)
    assert new_state_high.aperture == APERTURE_TRACE


def test_navigation_sequence(simple_residue):
    """Test a complete navigation sequence."""
    # Start at target with aperture 1
    state = create_explain_state(simple_residue)
    assert state.cursor == "validate"
    assert state.aperture == APERTURE_OUTPUT

    # Move down to generate
    state = move_cursor(state, "down")
    assert state.cursor == "generate"

    # Increase aperture to see trace
    state = adjust_aperture(state, +2)
    assert state.aperture == APERTURE_TRACE

    # Jump back to validate
    state = select_node(state, "validate")
    assert state.cursor == "validate"
    assert state.aperture == APERTURE_TRACE  # Aperture preserved

    # Decrease aperture to node-only
    state = set_aperture(state, APERTURE_NODE)
    assert state.aperture == APERTURE_NODE
