"""test_elaborate.py -- Flat-design elaboration tests."""

import pytest
from husks.kernel import encode, parse
from husks.forms import elaborate, ast_to_json, json_to_ast


# ── Demo flat design (matches spec/conformance/demo.husk) ────────

DEMO_FLAT = {
    "name": "demo", "fuel": 10, "target": "combine",
    "site_inputs": ["config.txt", "greeting.txt"],
    "rules": [
        {"name": "greet", "kind": "action",
         "inputs": ["config.txt", "greeting.txt"], "outputs": ["hello.txt"]},
        {"name": "combine", "kind": "oracle",
         "inputs": ["hello.txt"], "outputs": ["result.txt"],
         "prompt": "Combine the files.", "tools": ["read-file", "write-file"], "fuel": 3},
    ],
}

DEMO_FLAT_REVERSED = {**DEMO_FLAT, "rules": list(reversed(DEMO_FLAT["rules"]))}


# ── Golden vector ────────────────────────────────────────────────

class TestGoldenVector:
    def test_elaborate_matches_demo_bytes(self, demo_vector):
        husk_bytes, _, _ = demo_vector
        assert encode(elaborate(DEMO_FLAT)) == husk_bytes

    def test_elaborate_matches_demo_ast(self, demo_vector):
        husk_bytes, _, _ = demo_vector
        assert elaborate(DEMO_FLAT) == parse(husk_bytes)


# ── Order independence ───────────────────────────────────────────

class TestOrderIndependence:
    def test_reversed_same_bytes(self):
        assert encode(elaborate(DEMO_FLAT)) == encode(elaborate(DEMO_FLAT_REVERSED))

    def test_reversed_same_ast(self):
        assert elaborate(DEMO_FLAT) == elaborate(DEMO_FLAT_REVERSED)


# ── Diamond DAG (shared producer) ────────────────────────────────

DIAMOND = {
    "name": "diamond", "fuel": 20, "target": "merge",
    "site_inputs": ["seed.txt"],
    "rules": [
        {"name": "shared", "kind": "action", "inputs": ["seed.txt"], "outputs": ["common.txt"]},
        {"name": "left", "kind": "action", "inputs": ["common.txt"], "outputs": ["left.txt"]},
        {"name": "right", "kind": "action", "inputs": ["common.txt"], "outputs": ["right.txt"]},
        {"name": "merge", "kind": "action", "inputs": ["left.txt", "right.txt"], "outputs": ["merged.txt"]},
    ],
}

DIAMOND_SHUFFLED = {**DIAMOND, "rules": [
    DIAMOND["rules"][3], DIAMOND["rules"][2], DIAMOND["rules"][0], DIAMOND["rules"][1],
]}


class TestDiamondDAG:
    def test_diamond_order_independent(self):
        assert encode(elaborate(DIAMOND)) == encode(elaborate(DIAMOND_SHUFFLED))

    def test_diamond_structure(self):
        j = ast_to_json(elaborate(DIAMOND))
        merge = j["build"]["targets"][0]
        assert merge["name"] == "merge"
        assert len(merge["children"]) == 2
        assert merge["children"][0]["name"] == "left"
        assert merge["children"][1]["name"] == "right"
        # Both children reference shared
        assert merge["children"][0]["children"][0]["name"] == "shared"
        assert merge["children"][1]["children"][0]["name"] == "shared"

    def test_children_ordered_by_input_reference(self):
        swapped = {**DIAMOND, "rules": [
            {"name": "shared", "kind": "action", "inputs": ["seed.txt"], "outputs": ["common.txt"]},
            {"name": "left", "kind": "action", "inputs": ["common.txt"], "outputs": ["left.txt"]},
            {"name": "right", "kind": "action", "inputs": ["common.txt"], "outputs": ["right.txt"]},
            {"name": "merge", "kind": "action", "inputs": ["right.txt", "left.txt"], "outputs": ["merged.txt"]},
        ]}
        j = ast_to_json(elaborate(swapped))
        merge = j["build"]["targets"][0]
        assert [c["name"] for c in merge["children"]] == ["right", "left"]


# ── Target defaults to last rule ─────────────────────────────────

class TestTargetDefault:
    def test_defaults_to_last(self):
        design = {"name": "b", "fuel": 1, "rules": [
            {"name": "a", "kind": "action", "inputs": [], "outputs": ["x"]},
            {"name": "b", "kind": "action", "inputs": ["x"], "outputs": ["y"]},
        ]}
        j = ast_to_json(elaborate(design))
        assert j["build"]["targets"][0]["name"] == "b"


# ── site_inputs not children ─────────────────────────────────────

class TestSiteInputs:
    def test_site_inputs_not_children(self):
        design = {"name": "b", "fuel": 1, "target": "r", "site_inputs": ["ext.txt"],
                  "rules": [{"name": "r", "kind": "action", "inputs": ["ext.txt"], "outputs": ["out.txt"]}]}
        j = ast_to_json(elaborate(design))
        assert j["build"]["targets"][0]["inputs"] == ["ext.txt"]
        assert j["build"]["targets"][0]["children"] == []


# ── Fuel as string ───────────────────────────────────────────────

class TestFuel:
    def test_fuel_int_becomes_string(self):
        design = {"name": "b", "fuel": 42, "target": "r",
                  "rules": [{"name": "r", "kind": "action", "inputs": [], "outputs": ["x"]}]}
        j = ast_to_json(elaborate(design))
        assert j["build"]["fuel"] == "42"
        assert isinstance(j["build"]["fuel"], str)


# ── Cycle detection ──────────────────────────────────────────────

class TestCycleDetection:
    def test_direct_cycle_raises(self):
        design = {"name": "b", "fuel": 1, "target": "a",
                  "rules": [
                      {"name": "a", "kind": "action", "inputs": ["x"], "outputs": ["y"]},
                      {"name": "b", "kind": "action", "inputs": ["y"], "outputs": ["x"]},
                  ]}
        with pytest.raises(ValueError, match="dependency cycle"):
            elaborate(design)

    def test_self_cycle_raises(self):
        design = {"name": "b", "fuel": 1, "target": "a",
                  "rules": [{"name": "a", "kind": "action", "inputs": ["x"], "outputs": ["x"]}]}
        with pytest.raises(ValueError, match="dependency cycle"):
            elaborate(design)


# ── Structural kinds ─────────────────────────────────────────────

class TestStructuralKinds:
    def test_commit_elaboration(self):
        design = {"name": "b", "fuel": 1, "target": "c",
                  "rules": [{"name": "c", "kind": "commit", "value": "done"}]}
        j = ast_to_json(elaborate(design))
        target = j["build"]["targets"][0]
        assert target == {"form": "commit", "value": "done"}

    def test_halt_elaboration(self):
        design = {"name": "b", "fuel": 1, "target": "h",
                  "rules": [{"name": "h", "kind": "halt", "reason": "stopped"}]}
        j = ast_to_json(elaborate(design))
        target = j["build"]["targets"][0]
        assert target == {"form": "halt", "reason": "stopped"}

    def test_cond_elaboration(self):
        design = {"name": "b", "fuel": 1, "target": "branch",
                  "rules": [
                      {"name": "yes", "kind": "commit", "value": "ok"},
                      {"name": "no", "kind": "halt", "reason": "nope"},
                      {"name": "branch", "kind": "cond", "predicate": "check", "then": "yes", "else": "no"},
                  ]}
        j = ast_to_json(elaborate(design))
        target = j["build"]["targets"][0]
        assert target["form"] == "cond"
        assert target["predicate"] == "check"
        assert target["then"]["form"] == "commit"
        assert target["else"]["form"] == "halt"

    def test_let_elaboration(self):
        design = {"name": "b", "fuel": 1, "target": "alias",
                  "rules": [
                      {"name": "worker", "kind": "action", "inputs": [], "outputs": ["x"]},
                      {"name": "alias", "kind": "let", "bind": "worker"},
                  ]}
        j = ast_to_json(elaborate(design))
        target = j["build"]["targets"][0]
        assert target["form"] == "let"
        assert target["name"] == "alias"
        assert target["bound"]["form"] == "rule"


# ── Multi-target ─────────────────────────────────────────────────

class TestMultiTarget:
    def test_multi_targets(self):
        design = {"name": "b", "fuel": 1, "targets": ["a", "b"],
                  "rules": [
                      {"name": "a", "kind": "action", "inputs": [], "outputs": ["x"]},
                      {"name": "b", "kind": "action", "inputs": [], "outputs": ["y"]},
                  ]}
        j = ast_to_json(elaborate(design))
        assert len(j["build"]["targets"]) == 2
        assert j["build"]["targets"][0]["name"] == "a"
        assert j["build"]["targets"][1]["name"] == "b"


# ── Recipe elaboration ───────────────────────────────────────────

class TestRecipeElaboration:
    def test_action_recipe(self):
        design = {"name": "b", "fuel": 1, "target": "r",
                  "rules": [{"name": "r", "kind": "action", "inputs": [], "outputs": ["x"]}]}
        j = ast_to_json(elaborate(design))
        assert j["build"]["targets"][0]["recipe"] == {"form": "action"}

    def test_oracle_recipe(self):
        design = {"name": "b", "fuel": 5, "target": "r",
                  "rules": [{"name": "r", "kind": "oracle", "inputs": [], "outputs": ["x"],
                             "prompt": "Do it.", "tools": ["t1"], "fuel": 3}]}
        j = ast_to_json(elaborate(design))
        recipe = j["build"]["targets"][0]["recipe"]
        assert recipe["form"] == "oracle"
        assert recipe["name"] is None
        assert recipe["prompt"] == "Do it."
        assert recipe["tools"] == ["t1"]
        assert recipe["fuel"] == "3"

    def test_trial_recipe(self):
        design = {"name": "b", "fuel": 5, "target": "r",
                  "rules": [{"name": "r", "kind": "trial", "inputs": [], "outputs": ["x"],
                             "branches": [{"kind": "action"},
                                          {"kind": "oracle", "prompt": "try", "tools": ["t"], "fuel": 1}]}]}
        j = ast_to_json(elaborate(design))
        recipe = j["build"]["targets"][0]["recipe"]
        assert recipe["form"] == "trial"
        assert len(recipe["branches"]) == 2
        assert recipe["branches"][0] == {"form": "action"}
        assert recipe["branches"][1]["form"] == "oracle"

    def test_elaborate_then_json_round_trip(self):
        tree = elaborate(DEMO_FLAT)
        j = ast_to_json(tree)
        tree2 = json_to_ast(j)
        assert encode(tree2) == encode(tree)
