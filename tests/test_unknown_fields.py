"""
test_unknown_fields.py -- Validation of unknown design and rule fields.

Beta Gate A2: Reject unknown design fields.

Tests that misspelled or unknown fields are detected and reported clearly,
helping users catch typos like 'ouputs', 'taget', 'fuell', etc.
"""

from husks.designs.ir import check


def test_unknown_top_level_field():
    """Unknown top-level design field should be rejected."""
    design = {
        "name": "test",
        "fuel": 10,
        "target": "r",
        "unknown_field": "value",  # Unknown field
        "rules": [
            {"name": "r", "kind": "action", "outputs": ["out.txt"]},
        ],
    }
    errors = check(design)
    assert any("unknown design field" in e and "unknown_field" in e for e in errors), \
        f"Should detect unknown_field, got: {errors}"


def test_misspelled_targets():
    """Common misspelling: 'taget' instead of 'target'."""
    design = {
        "name": "test",
        "fuel": 10,
        "taget": "r",  # Misspelled
        "rules": [
            {"name": "r", "kind": "action", "outputs": ["out.txt"]},
        ],
    }
    errors = check(design)
    assert any("unknown design field" in e and "taget" in e for e in errors), \
        f"Should detect 'taget' misspelling, got: {errors}"
    assert any("no target" in e for e in errors), \
        f"Should also report missing target, got: {errors}"


def test_misspelled_fuel():
    """Common misspelling: 'fuell' instead of 'fuel'."""
    design = {
        "name": "test",
        "fuell": 10,  # Misspelled
        "target": "r",
        "rules": [
            {"name": "r", "kind": "action", "outputs": ["out.txt"]},
        ],
    }
    errors = check(design)
    assert any("unknown design field" in e and "fuell" in e for e in errors), \
        f"Should detect 'fuell' misspelling, got: {errors}"
    assert any("no fuel" in e for e in errors), \
        f"Should also report missing fuel, got: {errors}"


def test_misspelled_outputs():
    """Common misspelling: 'ouputs' instead of 'outputs'."""
    design = {
        "name": "test",
        "fuel": 10,
        "target": "r",
        "rules": [
            {
                "name": "r",
                "kind": "action",
                "ouputs": ["out.txt"],  # Misspelled
            },
        ],
    }
    errors = check(design)
    assert any("unknown field" in e and "ouputs" in e for e in errors), \
        f"Should detect 'ouputs' misspelling, got: {errors}"
    assert any("no declared outputs" in e for e in errors), \
        f"Should also report missing outputs, got: {errors}"


def test_unknown_action_field():
    """Unknown field in action rule."""
    design = {
        "name": "test",
        "fuel": 10,
        "target": "r",
        "rules": [
            {
                "name": "r",
                "kind": "action",
                "outputs": ["out.txt"],
                "unknown_action_field": "value",
            },
        ],
    }
    errors = check(design)
    assert any("unknown field" in e and "unknown_action_field" in e for e in errors), \
        f"Should detect unknown action field, got: {errors}"


def test_unknown_oracle_field():
    """Unknown field in oracle rule."""
    design = {
        "name": "test",
        "fuel": 10,
        "target": "r",
        "rules": [
            {
                "name": "r",
                "kind": "oracle",
                "outputs": ["out.txt"],
                "prompt": "test",
                "fuel": 5,
                "unknown_oracle_field": "value",
            },
        ],
    }
    errors = check(design)
    assert any("unknown field" in e and "unknown_oracle_field" in e for e in errors), \
        f"Should detect unknown oracle field, got: {errors}"


def test_misspelled_prompt():
    """Common misspelling: 'promtp' instead of 'prompt'."""
    design = {
        "name": "test",
        "fuel": 10,
        "target": "r",
        "rules": [
            {
                "name": "r",
                "kind": "oracle",
                "outputs": ["out.txt"],
                "promtp": "test",  # Misspelled
                "fuel": 5,
            },
        ],
    }
    errors = check(design)
    assert any("unknown field" in e and "promtp" in e for e in errors), \
        f"Should detect 'promtp' misspelling, got: {errors}"
    assert any("oracle rule has no prompt" in e for e in errors), \
        f"Should also report missing prompt, got: {errors}"


def test_unknown_trial_field():
    """Unknown field in trial rule."""
    design = {
        "name": "test",
        "fuel": 10,
        "target": "r",
        "rules": [
            {
                "name": "r",
                "kind": "trial",
                "outputs": ["out.txt"],
                "branches": [{"prompt": "a"}, {"prompt": "b"}],
                "unknown_trial_field": "value",
            },
        ],
    }
    errors = check(design)
    assert any("unknown field" in e and "unknown_trial_field" in e for e in errors), \
        f"Should detect unknown trial field, got: {errors}"


def test_unknown_commit_field():
    """Unknown field in commit rule."""
    design = {
        "name": "test",
        "fuel": 10,
        "target": "r",
        "rules": [
            {
                "name": "r",
                "kind": "commit",
                "value": "ok",
                "unknown_commit_field": "value",
            },
        ],
    }
    errors = check(design)
    assert any("unknown field" in e and "unknown_commit_field" in e for e in errors), \
        f"Should detect unknown commit field, got: {errors}"


def test_unknown_halt_field():
    """Unknown field in halt rule."""
    design = {
        "name": "test",
        "fuel": 10,
        "target": "r",
        "rules": [
            {
                "name": "r",
                "kind": "halt",
                "reason": "test",
                "unknown_halt_field": "value",
            },
        ],
    }
    errors = check(design)
    assert any("unknown field" in e and "unknown_halt_field" in e for e in errors), \
        f"Should detect unknown halt field, got: {errors}"


def test_unknown_let_field():
    """Unknown field in let rule."""
    design = {
        "name": "test",
        "fuel": 10,
        "target": "b",
        "rules": [
            {"name": "a", "kind": "action", "outputs": ["x"]},
            {
                "name": "b",
                "kind": "let",
                "bind": "a",
                "unknown_let_field": "value",
            },
        ],
    }
    errors = check(design)
    assert any("unknown field" in e and "unknown_let_field" in e for e in errors), \
        f"Should detect unknown let field, got: {errors}"


def test_unknown_cond_field():
    """Unknown field in cond rule."""
    design = {
        "name": "test",
        "fuel": 10,
        "target": "c",
        "predicates": {"test_pred": lambda S: True},
        "rules": [
            {"name": "a", "kind": "action", "outputs": ["x"]},
            {"name": "b", "kind": "action", "outputs": ["y"]},
            {
                "name": "c",
                "kind": "cond",
                "predicate": "test_pred",
                "then": "a",
                "else": "b",
                "unknown_cond_field": "value",
            },
        ],
    }
    errors = check(design)
    assert any("unknown field" in e and "unknown_cond_field" in e for e in errors), \
        f"Should detect unknown cond field, got: {errors}"


def test_multiple_unknown_fields():
    """Multiple unknown fields should all be reported."""
    design = {
        "name": "test",
        "fuel": 10,
        "target": "r",
        "unknown1": "a",
        "unknown2": "b",
        "rules": [
            {
                "name": "r",
                "kind": "action",
                "outputs": ["out.txt"],
                "unknown3": "c",
                "unknown4": "d",
            },
        ],
    }
    errors = check(design)
    assert any("unknown1" in e for e in errors), f"Should detect unknown1, got: {errors}"
    assert any("unknown2" in e for e in errors), f"Should detect unknown2, got: {errors}"
    assert any("unknown3" in e for e in errors), f"Should detect unknown3, got: {errors}"
    assert any("unknown4" in e for e in errors), f"Should detect unknown4, got: {errors}"


def test_misspelled_inputs():
    """Common misspelling: 'input' (singular) instead of 'inputs'."""
    design = {
        "name": "test",
        "fuel": 10,
        "target": "r",
        "site_inputs": ["data.txt"],
        "rules": [
            {
                "name": "r",
                "kind": "action",
                "input": ["data.txt"],  # Misspelled (should be 'inputs')
                "outputs": ["out.txt"],
            },
        ],
    }
    errors = check(design)
    assert any("unknown field" in e and "input" in e for e in errors), \
        f"Should detect 'input' misspelling, got: {errors}"


def test_misspelled_branches():
    """Common misspelling: 'branchs' instead of 'branches'."""
    design = {
        "name": "test",
        "fuel": 10,
        "target": "r",
        "rules": [
            {
                "name": "r",
                "kind": "trial",
                "outputs": ["out.txt"],
                "branchs": [{"prompt": "a"}],  # Misspelled
            },
        ],
    }
    errors = check(design)
    assert any("unknown field" in e and "branchs" in e for e in errors), \
        f"Should detect 'branchs' misspelling, got: {errors}"
    assert any("trial has no branches" in e for e in errors), \
        f"Should also report missing branches, got: {errors}"


def test_valid_design_no_errors():
    """A valid design with all correct fields should pass."""
    design = {
        "name": "valid",
        "fuel": 10,
        "target": "b",
        "site_inputs": ["input.txt"],
        "rules": [
            {
                "name": "a",
                "kind": "oracle",
                "inputs": ["input.txt"],
                "outputs": ["intermediate.txt"],
                "prompt": "Process the input",
                "tools": ["read-file", "write-file"],
                "fuel": 5,
            },
            {
                "name": "b",
                "kind": "action",
                "inputs": ["intermediate.txt"],
                "outputs": ["output.txt"],
                "run": "cp intermediate.txt output.txt",
            },
        ],
    }
    errors = check(design)
    unknown_errors = [e for e in errors if "unknown" in e.lower()]
    assert len(unknown_errors) == 0, \
        f"Valid design should have no unknown field errors, got: {unknown_errors}"


def test_typo_site_input_singular():
    """Common typo: 'site_input' instead of 'site_inputs'."""
    design = {
        "name": "test",
        "fuel": 10,
        "target": "r",
        "site_input": ["data.txt"],  # Misspelled (should be 'site_inputs')
        "rules": [
            {
                "name": "r",
                "kind": "action",
                "inputs": ["data.txt"],
                "outputs": ["out.txt"],
            },
        ],
    }
    errors = check(design)
    assert any("unknown design field" in e and "site_input" in e for e in errors), \
        f"Should detect 'site_input' misspelling, got: {errors}"
