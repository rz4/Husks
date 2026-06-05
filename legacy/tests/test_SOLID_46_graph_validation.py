"""
test_graph_validation.py -- Improved graph validation diagnostics.

Beta Gate A3: Improve graph validation diagnostics.

Tests for clear diagnostics on forward references, circular dependencies,
and duplicate outputs (with both producers named).
"""

from husks.design.locke import check


def test_duplicate_output_names_both_producers():
    """Duplicate output error should name both producers."""
    design = {
        "name": "test",
        "fuel": 10,
        "target": "b",
        "rules": [
            {
                "name": "a",
                "kind": "action",
                "outputs": ["conflict.txt"],
            },
            {
                "name": "b",
                "kind": "action",
                "outputs": ["conflict.txt"],  # Duplicate
            },
        ],
    }
    errors = check(design)

    # Should have an error that names both 'a' and 'b'
    duplicate_errors = [e for e in errors if "conflict.txt" in e and "already produced" in e]
    assert len(duplicate_errors) == 1, f"Expected 1 duplicate error, got: {errors}"

    error = duplicate_errors[0]
    assert "already produced by rule 'a'" in error, \
        f"Error should name first producer 'a', got: {error}"
    assert "'b'" in error or "b:" in error, \
        f"Error should reference second producer 'b', got: {error}"


def test_forward_reference_clear_message():
    """Forward reference should be clearly distinguished from missing input."""
    design = {
        "name": "test",
        "fuel": 10,
        "target": "b",
        "rules": [
            {
                "name": "a",
                "kind": "action",
                "inputs": ["later.txt"],  # Forward reference to b's output
                "outputs": ["early.txt"],
            },
            {
                "name": "b",
                "kind": "action",
                "outputs": ["later.txt"],  # Produced by later rule
            },
        ],
    }
    errors = check(design)

    # Should detect forward reference with clear message
    forward_ref_errors = [e for e in errors if "later.txt" in e]
    assert len(forward_ref_errors) > 0, f"Should detect forward reference, got: {errors}"

    error = forward_ref_errors[0]
    assert "forward reference" in error, \
        f"Error should mention 'forward reference', got: {error}"


def test_missing_input_vs_forward_reference():
    """Missing input should be distinguished from forward reference."""
    design = {
        "name": "test",
        "fuel": 10,
        "target": "a",
        "rules": [
            {
                "name": "a",
                "kind": "action",
                "inputs": ["truly_missing.txt"],  # No rule produces this
                "outputs": ["out.txt"],
            },
        ],
    }
    errors = check(design)

    missing_errors = [e for e in errors if "truly_missing.txt" in e]
    assert len(missing_errors) > 0, f"Should detect missing input, got: {errors}"

    error = missing_errors[0]
    assert "not produced by any rule" in error, \
        f"Error should say 'not produced by any rule', got: {error}"
    assert "forward reference" not in error, \
        f"Error should NOT say 'forward reference', got: {error}"


def test_circular_dependency_two_rules():
    """Simple circular dependency between two rules."""
    design = {
        "name": "test",
        "fuel": 10,
        "target": "a",
        "rules": [
            {
                "name": "a",
                "kind": "action",
                "inputs": ["b.txt"],
                "outputs": ["a.txt"],
            },
            {
                "name": "b",
                "kind": "action",
                "inputs": ["a.txt"],
                "outputs": ["b.txt"],
            },
        ],
    }
    errors = check(design)

    cycle_errors = [e for e in errors if "circular dependency" in e]
    assert len(cycle_errors) > 0, f"Should detect circular dependency, got: {errors}"

    error = cycle_errors[0]
    # Should show the cycle path
    assert "a" in error and "b" in error, \
        f"Error should mention both rules in cycle, got: {error}"


def test_circular_dependency_three_rules():
    """Circular dependency among three rules: a -> b -> c -> a."""
    design = {
        "name": "test",
        "fuel": 10,
        "target": "a",
        "rules": [
            {
                "name": "a",
                "kind": "action",
                "inputs": ["c.txt"],
                "outputs": ["a.txt"],
            },
            {
                "name": "b",
                "kind": "action",
                "inputs": ["a.txt"],
                "outputs": ["b.txt"],
            },
            {
                "name": "c",
                "kind": "action",
                "inputs": ["b.txt"],
                "outputs": ["c.txt"],
            },
        ],
    }
    errors = check(design)

    cycle_errors = [e for e in errors if "circular dependency" in e]
    assert len(cycle_errors) > 0, f"Should detect circular dependency, got: {errors}"

    # The cycle should be reported with a path showing the loop
    error = cycle_errors[0]
    # Should contain all three rules in the cycle
    assert "a" in error, f"Cycle should include 'a', got: {error}"
    assert "b" in error, f"Cycle should include 'b', got: {error}"
    assert "c" in error, f"Cycle should include 'c', got: {error}"


def test_self_circular_dependency():
    """Rule that depends on its own output (self-cycle)."""
    design = {
        "name": "test",
        "fuel": 10,
        "target": "a",
        "rules": [
            {
                "name": "a",
                "kind": "action",
                "inputs": ["a.txt"],  # Depends on itself
                "outputs": ["a.txt"],
            },
        ],
    }
    errors = check(design)

    # This creates a forward reference (input not yet produced when rule is validated)
    # and a circular dependency (rule depends on itself)
    cycle_or_forward = [
        e for e in errors
        if "circular" in e or "forward reference" in e
    ]
    assert len(cycle_or_forward) > 0, \
        f"Should detect self-dependency, got: {errors}"


def test_no_cycle_in_valid_dag():
    """Valid DAG should not report circular dependencies."""
    design = {
        "name": "test",
        "fuel": 10,
        "target": "c",
        "rules": [
            {
                "name": "a",
                "kind": "action",
                "outputs": ["a.txt"],
            },
            {
                "name": "b",
                "kind": "action",
                "inputs": ["a.txt"],
                "outputs": ["b.txt"],
            },
            {
                "name": "c",
                "kind": "action",
                "inputs": ["a.txt", "b.txt"],
                "outputs": ["c.txt"],
            },
        ],
    }
    errors = check(design)

    cycle_errors = [e for e in errors if "circular" in e]
    assert len(cycle_errors) == 0, \
        f"Valid DAG should not have circular dependency, got: {cycle_errors}"


def test_diamond_dag_no_cycle():
    """Diamond dependency pattern is valid (not a cycle)."""
    design = {
        "name": "test",
        "fuel": 10,
        "target": "d",
        "rules": [
            {
                "name": "a",
                "kind": "action",
                "outputs": ["a.txt"],
            },
            {
                "name": "b",
                "kind": "action",
                "inputs": ["a.txt"],
                "outputs": ["b.txt"],
            },
            {
                "name": "c",
                "kind": "action",
                "inputs": ["a.txt"],
                "outputs": ["c.txt"],
            },
            {
                "name": "d",
                "kind": "action",
                "inputs": ["b.txt", "c.txt"],
                "outputs": ["d.txt"],
            },
        ],
    }
    errors = check(design)

    cycle_errors = [e for e in errors if "circular" in e]
    assert len(cycle_errors) == 0, \
        f"Diamond DAG should not have circular dependency, got: {cycle_errors}"


def test_multiple_duplicate_outputs():
    """Multiple duplicate outputs should all be reported."""
    design = {
        "name": "test",
        "fuel": 10,
        "target": "c",
        "rules": [
            {
                "name": "a",
                "kind": "action",
                "outputs": ["x.txt", "y.txt"],
            },
            {
                "name": "b",
                "kind": "action",
                "outputs": ["x.txt"],  # Duplicate of a's output
            },
            {
                "name": "c",
                "kind": "action",
                "outputs": ["y.txt"],  # Duplicate of a's output
            },
        ],
    }
    errors = check(design)

    x_errors = [e for e in errors if "x.txt" in e and "already produced" in e]
    y_errors = [e for e in errors if "y.txt" in e and "already produced" in e]

    assert len(x_errors) == 1, f"Should report x.txt duplicate, got: {errors}"
    assert len(y_errors) == 1, f"Should report y.txt duplicate, got: {errors}"

    # Both should name the first producer 'a'
    assert "already produced by rule 'a'" in x_errors[0]
    assert "already produced by rule 'a'" in y_errors[0]


def test_forward_reference_with_multiple_rules():
    """Forward reference in complex graph."""
    design = {
        "name": "test",
        "fuel": 10,
        "target": "c",
        "rules": [
            {
                "name": "a",
                "kind": "action",
                "inputs": ["future.txt"],  # Forward reference
                "outputs": ["a.txt"],
            },
            {
                "name": "b",
                "kind": "action",
                "inputs": ["a.txt"],
                "outputs": ["b.txt"],
            },
            {
                "name": "c",
                "kind": "action",
                "outputs": ["future.txt"],  # Produced later
            },
        ],
    }
    errors = check(design)

    forward_errors = [e for e in errors if "future.txt" in e and "forward reference" in e]
    assert len(forward_errors) > 0, f"Should detect forward reference, got: {errors}"


def test_valid_design_no_graph_errors():
    """Valid design with proper dependencies should have no graph errors."""
    design = {
        "name": "valid",
        "fuel": 10,
        "target": "final",
        "site_inputs": ["input.txt"],
        "rules": [
            {
                "name": "process",
                "kind": "action",
                "inputs": ["input.txt"],
                "outputs": ["processed.txt"],
            },
            {
                "name": "final",
                "kind": "action",
                "inputs": ["processed.txt"],
                "outputs": ["result.txt"],
            },
        ],
    }
    errors = check(design)

    graph_errors = [
        e for e in errors
        if any(x in e for x in ["circular", "forward reference", "already produced", "not produced"])
    ]
    assert len(graph_errors) == 0, \
        f"Valid design should have no graph errors, got: {graph_errors}"
