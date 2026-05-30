"""
test_3_flat_elaboration.py -- Flat-design elaboration.

Gate: two distinct flat-designs with the same DAG produce the same build-root.
"""

import pytest

from conftest import DEMO_SITE, load_demo
from husks.core import encode, parse, recompute_root, NIL
from husks.designs.transport import elaborate, ast_to_json


# -- The flat design equivalent to demo.husk -----------------------------------

DEMO_FLAT_DESIGN = {
    "name": "demo",
    "fuel": 10,
    "target": "combine",
    "site_inputs": ["config.txt", "greeting.txt"],
    "rules": [
        {
            "name": "greet",
            "kind": "action",
            "inputs": ["config.txt", "greeting.txt"],
            "outputs": ["hello.txt"],
        },
        {
            "name": "combine",
            "kind": "oracle",
            "inputs": ["hello.txt"],
            "outputs": ["result.txt"],
            "prompt": "Combine the files.",
            "tools": ["read-file", "write-file"],
            "fuel": 3,
        },
    ],
}

# Same DAG, rules listed in reverse order
DEMO_FLAT_DESIGN_REVERSED = {
    "name": "demo",
    "fuel": 10,
    "target": "combine",
    "site_inputs": ["config.txt", "greeting.txt"],
    "rules": [
        {
            "name": "combine",
            "kind": "oracle",
            "inputs": ["hello.txt"],
            "outputs": ["result.txt"],
            "prompt": "Combine the files.",
            "tools": ["read-file", "write-file"],
            "fuel": 3,
        },
        {
            "name": "greet",
            "kind": "action",
            "inputs": ["config.txt", "greeting.txt"],
            "outputs": ["hello.txt"],
        },
    ],
}


# -- Gate: golden vector from flat design --------------------------------------

class TestGoldenVectorElaboration:
    """Flat design elaborates to the exact same CSE bytes as demo.husk."""

    @pytest.mark.alpha

    def test_elaborate_matches_demo_bytes(self):
        husk_bytes, _ = load_demo()
        tree = elaborate(DEMO_FLAT_DESIGN)
        assert encode(tree) == husk_bytes

    @pytest.mark.alpha

    def test_elaborate_matches_demo_ast(self):
        husk_bytes, _ = load_demo()
        expected = parse(husk_bytes)
        actual = elaborate(DEMO_FLAT_DESIGN)
        assert actual == expected

    @pytest.mark.alpha

    def test_elaborate_root_preservation(self):
        _, expected_root = load_demo()
        tree = elaborate(DEMO_FLAT_DESIGN)
        husk_bytes = encode(tree)
        actual_root = recompute_root(husk_bytes, DEMO_SITE)
        assert actual_root == expected_root


# -- Gate: two distinct flat-designs, same DAG, same root ----------------------

class TestOrderIndependence:
    """Different rule orderings in the flat design produce identical output."""

    @pytest.mark.alpha

    def test_reversed_order_same_bytes(self):
        a = encode(elaborate(DEMO_FLAT_DESIGN))
        b = encode(elaborate(DEMO_FLAT_DESIGN_REVERSED))
        assert a == b

    @pytest.mark.alpha

    def test_reversed_order_same_root(self):
        _, expected_root = load_demo()
        husk_bytes = encode(elaborate(DEMO_FLAT_DESIGN_REVERSED))
        actual_root = recompute_root(husk_bytes, DEMO_SITE)
        assert actual_root == expected_root


# -- Diamond DAG (shared producer) ---------------------------------------------

DIAMOND_DESIGN = {
    "name": "diamond",
    "fuel": 20,
    "target": "merge",
    "site_inputs": ["seed.txt"],
    "rules": [
        {
            "name": "shared",
            "kind": "action",
            "inputs": ["seed.txt"],
            "outputs": ["common.txt"],
        },
        {
            "name": "left",
            "kind": "action",
            "inputs": ["common.txt"],
            "outputs": ["left.txt"],
        },
        {
            "name": "right",
            "kind": "action",
            "inputs": ["common.txt"],
            "outputs": ["right.txt"],
        },
        {
            "name": "merge",
            "kind": "action",
            "inputs": ["left.txt", "right.txt"],
            "outputs": ["merged.txt"],
        },
    ],
}

DIAMOND_DESIGN_SHUFFLED = {
    "name": "diamond",
    "fuel": 20,
    "target": "merge",
    "site_inputs": ["seed.txt"],
    "rules": [
        {
            "name": "merge",
            "kind": "action",
            "inputs": ["left.txt", "right.txt"],
            "outputs": ["merged.txt"],
        },
        {
            "name": "right",
            "kind": "action",
            "inputs": ["common.txt"],
            "outputs": ["right.txt"],
        },
        {
            "name": "shared",
            "kind": "action",
            "inputs": ["seed.txt"],
            "outputs": ["common.txt"],
        },
        {
            "name": "left",
            "kind": "action",
            "inputs": ["common.txt"],
            "outputs": ["left.txt"],
        },
    ],
}


class TestDiamondDAG:
    """Shared producer duplicated in tree; order-independent."""

    @pytest.mark.alpha

    def test_diamond_same_bytes_regardless_of_order(self):
        a = encode(elaborate(DIAMOND_DESIGN))
        b = encode(elaborate(DIAMOND_DESIGN_SHUFFLED))
        assert a == b

    @pytest.mark.alpha

    def test_diamond_tree_structure(self):
        tree = elaborate(DIAMOND_DESIGN)
        j = ast_to_json(tree)
        merge = j["build"]["targets"][0]
        assert merge["name"] == "merge"
        assert len(merge["children"]) == 2

        left = merge["children"][0]
        right = merge["children"][1]
        assert left["name"] == "left"
        assert right["name"] == "right"

        # Both reference the shared producer as a child
        assert len(left["children"]) == 1
        assert len(right["children"]) == 1
        assert left["children"][0]["name"] == "shared"
        assert right["children"][0]["name"] == "shared"

    @pytest.mark.alpha

    def test_diamond_children_ordered_by_input_reference(self):
        """Children appear in order of first reference in parent's input list."""
        # merge inputs: [left.txt, right.txt] -> children: [left, right]
        tree = elaborate(DIAMOND_DESIGN)
        j = ast_to_json(tree)
        merge = j["build"]["targets"][0]
        assert [c["name"] for c in merge["children"]] == ["left", "right"]

        # Swap input order -> children order changes
        swapped = {
            "name": "diamond",
            "fuel": 20,
            "target": "merge",
            "site_inputs": ["seed.txt"],
            "rules": [
                {"name": "shared", "kind": "action",
                 "inputs": ["seed.txt"], "outputs": ["common.txt"]},
                {"name": "left", "kind": "action",
                 "inputs": ["common.txt"], "outputs": ["left.txt"]},
                {"name": "right", "kind": "action",
                 "inputs": ["common.txt"], "outputs": ["right.txt"]},
                {"name": "merge", "kind": "action",
                 "inputs": ["right.txt", "left.txt"],
                 "outputs": ["merged.txt"]},
            ],
        }
        tree2 = elaborate(swapped)
        j2 = ast_to_json(tree2)
        merge2 = j2["build"]["targets"][0]
        assert [c["name"] for c in merge2["children"]] == ["right", "left"]


# -- Recipe elaboration -------------------------------------------------------

class TestRecipeElaboration:
    """Each recipe kind elaborates correctly."""

    @pytest.mark.alpha

    def test_action_recipe(self):
        design = {
            "name": "b", "fuel": 1, "target": "r",
            "rules": [{"name": "r", "kind": "action",
                        "inputs": [], "outputs": ["x"]}],
        }
        tree = elaborate(design)
        j = ast_to_json(tree)
        assert j["build"]["targets"][0]["recipe"] == {"form": "action"}

    @pytest.mark.alpha

    def test_oracle_recipe_nil_name(self):
        design = {
            "name": "b", "fuel": 5, "target": "r",
            "rules": [{"name": "r", "kind": "oracle",
                        "inputs": [], "outputs": ["x"],
                        "prompt": "Do it.", "tools": ["t1"], "fuel": 3}],
        }
        tree = elaborate(design)
        j = ast_to_json(tree)
        recipe = j["build"]["targets"][0]["recipe"]
        assert recipe["form"] == "oracle"
        assert recipe["name"] is None
        assert recipe["prompt"] == "Do it."
        assert recipe["tools"] == ["t1"]
        assert recipe["fuel"] == "3"

    @pytest.mark.alpha

    def test_oracle_recipe_with_name(self):
        design = {
            "name": "b", "fuel": 5, "target": "r",
            "rules": [{"name": "r", "kind": "oracle",
                        "oracle_name": "my-oracle",
                        "inputs": [], "outputs": ["x"],
                        "prompt": "Go.", "tools": [], "fuel": 2}],
        }
        tree = elaborate(design)
        j = ast_to_json(tree)
        assert j["build"]["targets"][0]["recipe"]["name"] == "my-oracle"

    @pytest.mark.alpha

    def test_trial_recipe(self):
        design = {
            "name": "b", "fuel": 5, "target": "r",
            "rules": [{"name": "r", "kind": "trial",
                        "inputs": [], "outputs": ["x"],
                        "branches": [
                            {"kind": "action"},
                            {"kind": "oracle", "prompt": "try",
                             "tools": ["t"], "fuel": 1},
                        ]}],
        }
        tree = elaborate(design)
        j = ast_to_json(tree)
        recipe = j["build"]["targets"][0]["recipe"]
        assert recipe["form"] == "trial"
        assert len(recipe["branches"]) == 2
        assert recipe["branches"][0] == {"form": "action"}
        assert recipe["branches"][1]["form"] == "oracle"


# -- Edge cases ----------------------------------------------------------------

class TestElaborateEdgeCases:
    """Flat-design edge cases."""

    @pytest.mark.alpha

    def test_single_rule_no_children(self):
        design = {
            "name": "solo", "fuel": 1, "target": "r",
            "rules": [{"name": "r", "kind": "action",
                        "inputs": [], "outputs": ["out.txt"]}],
        }
        tree = elaborate(design)
        j = ast_to_json(tree)
        assert j["build"]["targets"][0]["children"] == []

    @pytest.mark.alpha

    def test_target_defaults_to_last_rule(self):
        design = {
            "name": "b", "fuel": 1,
            "rules": [
                {"name": "a", "kind": "action", "inputs": [], "outputs": ["x"]},
                {"name": "b", "kind": "action", "inputs": ["x"], "outputs": ["y"]},
            ],
        }
        tree = elaborate(design)
        j = ast_to_json(tree)
        assert j["build"]["targets"][0]["name"] == "b"

    @pytest.mark.alpha

    def test_site_inputs_not_children(self):
        """Inputs from site_inputs don't create child dependencies."""
        design = {
            "name": "b", "fuel": 1, "target": "r",
            "site_inputs": ["ext.txt"],
            "rules": [{"name": "r", "kind": "action",
                        "inputs": ["ext.txt"], "outputs": ["out.txt"]}],
        }
        tree = elaborate(design)
        j = ast_to_json(tree)
        assert j["build"]["targets"][0]["inputs"] == ["ext.txt"]
        assert j["build"]["targets"][0]["children"] == []

    @pytest.mark.alpha

    def test_fuel_as_int_becomes_string_atom(self):
        design = {
            "name": "b", "fuel": 42, "target": "r",
            "rules": [{"name": "r", "kind": "action",
                        "inputs": [], "outputs": ["x"]}],
        }
        tree = elaborate(design)
        j = ast_to_json(tree)
        assert j["build"]["fuel"] == "42"
        assert isinstance(j["build"]["fuel"], str)

    @pytest.mark.alpha

    def test_elaborate_then_json_round_trip(self):
        """elaborate -> ast_to_json -> json_to_ast -> encode is stable."""
        from husks.designs.transport import json_to_ast
        tree = elaborate(DEMO_FLAT_DESIGN)
        j = ast_to_json(tree)
        tree2 = json_to_ast(j)
        assert encode(tree2) == encode(tree)
