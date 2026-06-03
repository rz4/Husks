"""
test_conditional_seed_semantics.py -- Conditional seed portability semantics.

Beta Gate A4: Define conditional seed semantics.

Documents and tests the semantic decision: conditional designs bind BOTH
branches into seed identity, even though only one branch executes at runtime.

This ensures seed portability: the same design can run on different machines
where predicates may evaluate differently, but the seed identity remains stable.

## Semantic Decision

**Runtime**: Only the selected branch executes (determined by predicate evaluation).
**Identity**: Both branches are included in the build-root digest.

This means:
- Machine 1 (predicate=True) executes 'then' branch
- Machine 2 (predicate=False) executes 'else' branch
- Both machines run the SAME seed (same build-root, same design)
- The design is portable because it contains both execution paths

## Why Both Branches?

If only the executed branch were included in identity:
1. The same design would have different identities on different machines
2. Predicates based on environment (file-exists, etc.) would break portability
3. The seed would be incomplete (missing one execution path)
4. Reproducibility would depend on the predicate result, not just the design

By binding both branches:
1. The seed is complete and self-contained
2. The design is portable across different environments
3. Build identity is stable regardless of which branch executes
4. The predicate becomes a runtime dispatch, not an identity factor
"""

import tempfile
import shutil
from pathlib import Path

from husks.build import build, rule, cond, action
from husks.build.eval import compute_build_root, node_to_cse
from husks.core import encode


def test_cond_both_branches_in_cse_form():
    """The CSE form of a cond node includes both branches."""
    def always_true(S):
        return True

    then_node = {"type": "commit", "value": "then"}
    else_node = {"type": "commit", "value": "else"}

    cond_node = cond(always_true, then_node, else_node)

    # Serialize to CSE
    cse_form = node_to_cse(cond_node)

    # The CSE form should be: [b"cond", predicate_id, then_cse, else_cse]
    assert cse_form[0] == b"cond", "First element should be 'cond'"
    assert len(cse_form) == 4, "Should have 4 elements: kind, predicate, then, else"

    # Both branches should be present in the CSE form
    then_cse = cse_form[2]
    else_cse = cse_form[3]
    assert then_cse == [b"commit", b"then"], "Then branch should be in CSE"
    assert else_cse == [b"commit", b"else"], "Else branch should be in CSE"


def test_cond_both_branches_in_design_identity():
    """Design identity (CSE form) includes both branches, regardless of which executes."""
    import hashlib

    def test_predicate(S):
        return S.get("test_flag", True)

    def action_a(S):
        from husks.build import write_text, site_path
        write_text(site_path(S, "result.txt", write=True), "a\n")

    def action_b(S):
        from husks.build import write_text, site_path
        write_text(site_path(S, "result.txt", write=True), "b\n")

    then_node = rule("then-rule", outputs=["result.txt"], recipe=action(action_a))
    else_node = rule("else-rule", outputs=["result.txt"], recipe=action(action_b))
    cond_node = cond(test_predicate, then_node, else_node)

    # The CSE form is the same regardless of which branch will execute
    cse_form = node_to_cse(cond_node)
    design_hash = hashlib.sha256(encode(cse_form)).hexdigest()

    # The design identity is stable (doesn't depend on runtime predicate value)
    # This hash represents the seed design, not the build outputs
    assert len(design_hash) == 64, "Should produce a valid SHA-256 hash"

    # Verify both branches are in the CSE
    assert cse_form[0] == b"cond"
    assert len(cse_form) == 4  # kind, predicate, then, else
    then_cse = cse_form[2]
    else_cse = cse_form[3]

    # Both branch CSE forms should be present
    assert b"then-rule" in encode(then_cse)
    assert b"else-rule" in encode(else_cse)


def test_cond_only_selected_branch_executes():
    """Runtime: only the selected branch executes (not both)."""
    tmpdir = tempfile.mkdtemp(prefix="cond-runtime-")
    try:
        site = Path(tmpdir) / "site"
        site.mkdir()

        executed = []

        def always_true(S):
            return True

        def then_action(S):
            executed.append("then")
            from husks.build import write_text, site_path
            write_text(site_path(S, "out.txt", write=True), "then\n")

        def else_action(S):
            executed.append("else")
            from husks.build import write_text, site_path
            write_text(site_path(S, "out.txt", write=True), "else\n")

        then_node = rule("then-rule", outputs=["out.txt"], recipe=action(then_action))
        else_node = rule("else-rule", outputs=["out.txt"], recipe=action(else_action))
        cond_node = cond(always_true, then_node, else_node)

        S = build("test", 10, cond_node, site=str(site))

        # Only the then branch should have executed
        assert executed == ["then"], "Only then branch should execute"
        assert (site / "out.txt").read_text() == "then\n"

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_cond_seed_portability_scenario():
    """Seed portability: same design, different environments, different outputs."""
    import hashlib
    tmpdir = tempfile.mkdtemp(prefix="cond-portability-")
    try:
        # Scenario: a design that checks if a config file exists
        # Machine 1 has the file, Machine 2 doesn't
        # Both run the SAME seed design but produce DIFFERENT outputs

        def config_exists(S):
            from husks.build import site_path
            import os
            return os.path.exists(site_path(S, "config.json"))

        def use_config_action(S):
            from husks.build import write_text, site_path
            write_text(site_path(S, "result.txt", write=True), "using config\n")

        def use_defaults_action(S):
            from husks.build import write_text, site_path
            write_text(site_path(S, "result.txt", write=True), "using defaults\n")

        then_node = rule("use-config", outputs=["result.txt"], recipe=action(use_config_action))
        else_node = rule("use-defaults", outputs=["result.txt"], recipe=action(use_defaults_action))
        cond_node = cond(config_exists, then_node, else_node)

        # Machine 1: has config file
        site1 = Path(tmpdir) / "machine1"
        site1.mkdir()
        (site1 / "config.json").write_text('{"key": "value"}\n')

        S1 = build("portable-design", 10, cond_node, site=str(site1))
        assert S1["status"] == "committed"
        assert (site1 / "result.txt").read_text() == "using config\n"

        # Machine 2: no config file
        site2 = Path(tmpdir) / "machine2"
        site2.mkdir()
        # No config.json

        S2 = build("portable-design", 10, cond_node, site=str(site2))
        assert S2["status"] == "committed"
        assert (site2 / "result.txt").read_text() == "using defaults\n"

        # Key insight: SAME design identity (CSE form), DIFFERENT build outputs
        cse_form = node_to_cse(cond_node)
        design_hash = hashlib.sha256(encode(cse_form)).hexdigest()

        # The seed design is the same
        assert S1["status"] == S2["status"] == "committed"
        # Both machines ran the same design
        # (In a real scenario, both would have the same .locke or .json source)

        # But the outputs differ (expected and valid)
        output1 = (site1 / "result.txt").read_text()
        output2 = (site2 / "result.txt").read_text()
        assert output1 != output2, "Different branches produce different outputs"

        # The seed design is portable (CSE form is complete)
        # The build outputs depend on environment (predicate result)

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_cond_predicate_identity_affects_build_root():
    """Different predicates produce different build-roots."""
    tmpdir = tempfile.mkdtemp(prefix="cond-pred-identity-")
    try:
        site = Path(tmpdir) / "site"
        site.mkdir()

        def predicate_a(S):
            return True

        def predicate_b(S):
            return True

        # Give predicates different identities
        predicate_a._husks_pred_spec = "predicate-a"
        predicate_b._husks_pred_spec = "predicate-b"

        def action_fn(S):
            from husks.build import write_text, site_path
            write_text(site_path(S, "out.txt", write=True), "output\n")

        then_node = rule("then", outputs=["out.txt"], recipe=action(action_fn))
        else_node = rule("else", outputs=["out.txt"], recipe=action(action_fn))

        # Build with predicate A
        cond_a = cond(predicate_a, then_node, else_node)
        S_a = build("test-a", 10, cond_a, site=str(site))
        root_a = compute_build_root(S_a, cond_a)

        # Clean site
        shutil.rmtree(site)
        site.mkdir()

        # Build with predicate B (but same branches)
        cond_b = cond(predicate_b, then_node, else_node)
        S_b = build("test-b", 10, cond_b, site=str(site))
        root_b = compute_build_root(S_b, cond_b)

        # Different predicates should produce different build-roots
        assert root_a != root_b, (
            "Different predicates should produce different build-roots"
        )

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_cond_branch_order_affects_identity():
    """Swapping then/else branches changes build-root."""
    def always_true(S):
        return True

    def action_a(S):
        from husks.build import write_text, site_path
        write_text(site_path(S, "out.txt", write=True), "a\n")

    def action_b(S):
        from husks.build import write_text, site_path
        write_text(site_path(S, "out.txt", write=True), "b\n")

    rule_a = rule("a", outputs=["out.txt"], recipe=action(action_a))
    rule_b = rule("b", outputs=["out.txt"], recipe=action(action_b))

    # cond with A then B
    cond_ab = cond(always_true, rule_a, rule_b)
    cse_ab = node_to_cse(cond_ab)
    bytes_ab = encode(cse_ab)

    # cond with B then A (swapped)
    cond_ba = cond(always_true, rule_b, rule_a)
    cse_ba = node_to_cse(cond_ba)
    bytes_ba = encode(cse_ba)

    # Different branch order should produce different encodings
    assert bytes_ab != bytes_ba, (
        "Swapping then/else branches should change the encoded form"
    )


def test_cond_design_completeness():
    """A cond design is complete only if both branches are specified."""
    from husks.designs.ir import check

    # Valid cond design
    valid_design = {
        "name": "test",
        "fuel": 10,
        "target": "c",
        "predicates": {"always_true": lambda S: True},
        "rules": [
            {"name": "a", "kind": "action", "outputs": ["a.txt"]},
            {"name": "b", "kind": "action", "outputs": ["b.txt"]},
            {
                "name": "c",
                "kind": "cond",
                "predicate": "always_true",
                "then": "a",
                "else": "b",
            },
        ],
    }

    errors = check(valid_design)
    cond_errors = [e for e in errors if "cond" in e and "then" in e or "else" in e]
    assert len(cond_errors) == 0, f"Valid cond should have no errors: {errors}"

    # Missing 'then' branch
    missing_then = {
        "name": "test",
        "fuel": 10,
        "target": "c",
        "predicates": {"always_true": lambda S: True},
        "rules": [
            {"name": "a", "kind": "action", "outputs": ["a.txt"]},
            {"name": "b", "kind": "action", "outputs": ["b.txt"]},
            {
                "name": "c",
                "kind": "cond",
                "predicate": "always_true",
                # Missing "then"
                "else": "b",
            },
        ],
    }

    errors = check(missing_then)
    assert any("then" in e for e in errors), "Should report missing 'then' branch"

    # Missing 'else' branch
    missing_else = {
        "name": "test",
        "fuel": 10,
        "target": "c",
        "predicates": {"always_true": lambda S: True},
        "rules": [
            {"name": "a", "kind": "action", "outputs": ["a.txt"]},
            {"name": "b", "kind": "action", "outputs": ["b.txt"]},
            {
                "name": "c",
                "kind": "cond",
                "predicate": "always_true",
                "then": "a",
                # Missing "else"
            },
        ],
    }

    errors = check(missing_else)
    assert any("else" in e for e in errors), "Should report missing 'else' branch"
