"""
test_2_json_bijection.py -- Canonical JSON <-> CSE bijection.

Gate: CSE(json_to_ast(ast_to_json(parse(demo.husk)))) == demo.husk bytes,
      and recompute_root(round_tripped_bytes, demo.site) == demo.root.
"""

import pytest

from conftest import DEMO_HUSK, DEMO_ROOT, DEMO_SITE, load_demo
from husks.core import encode, parse, recompute_root, NIL
from husks.designs.transport import ast_to_json, json_to_ast, to_json_str, from_json_str, round_trip


# -- Gate tests ----------------------------------------------------------------

class TestGoldenVectorRoundTrip:
    """The primary gate: byte-exact CSE round-trip through JSON."""

    def test_round_trip_bytes_match(self):
        husk_bytes, _ = load_demo()
        result = round_trip(husk_bytes)
        assert result == husk_bytes, "Round-tripped bytes differ from original"

    def test_root_preservation(self):
        husk_bytes, expected_root = load_demo()
        rt_bytes = round_trip(husk_bytes)
        actual_root = recompute_root(rt_bytes, DEMO_SITE)
        assert actual_root == expected_root, (
            f"Root mismatch: {actual_root} != {expected_root}"
        )


# -- JSON structure tests -----------------------------------------------------

class TestJSONStructure:
    """Spot-check that ast_to_json produces the expected JSON shape."""

    def setup_method(self):
        husk_bytes, _ = load_demo()
        self.tree = parse(husk_bytes)
        self.j = ast_to_json(self.tree)

    def test_top_level_form(self):
        assert self.j["form"] == "husk"
        assert self.j["version"] == "1"

    def test_build_form(self):
        build = self.j["build"]
        assert build["form"] == "build"
        assert build["name"] == "demo"
        assert build["fuel"] == "10"

    def test_rule_form(self):
        rule = self.j["build"]["targets"][0]
        assert rule["form"] == "rule"
        assert rule["name"] == "combine"
        assert rule["inputs"] == ["hello.txt"]
        assert rule["outputs"] == ["result.txt"]
        assert isinstance(rule["children"], list)
        assert len(rule["children"]) == 1

    def test_oracle_recipe(self):
        recipe = self.j["build"]["targets"][0]["recipe"]
        assert recipe["form"] == "oracle"
        assert recipe["name"] is None  # NIL
        assert recipe["prompt"] == "Combine the files."
        assert recipe["tools"] == ["read-file", "write-file"]
        assert recipe["fuel"] == "3"

    def test_child_rule(self):
        child = self.j["build"]["targets"][0]["children"][0]
        assert child["form"] == "rule"
        assert child["name"] == "greet"
        assert child["inputs"] == ["config.txt", "greeting.txt"]
        assert child["outputs"] == ["hello.txt"]
        assert child["children"] == []

    def test_action_recipe(self):
        child = self.j["build"]["targets"][0]["children"][0]
        assert child["recipe"]["form"] == "action"


# -- Symmetry tests -----------------------------------------------------------

class TestSymmetry:
    """json_to_ast(ast_to_json(x)) == x for each form type."""

    def test_action(self):
        original = [b"action"]
        assert json_to_ast(ast_to_json(original)) == original

    def test_oracle(self):
        original = [b"oracle", NIL, b"Do stuff.", [b"tool-a"], b"5"]
        assert json_to_ast(ast_to_json(original)) == original

    def test_oracle_with_name(self):
        original = [b"oracle", b"my-oracle", b"prompt", [b"t1", b"t2"], b"1"]
        assert json_to_ast(ast_to_json(original)) == original

    def test_trial(self):
        original = [b"trial", [b"action"], [b"action"]]
        assert json_to_ast(ast_to_json(original)) == original

    def test_trial_empty(self):
        original = [b"trial"]
        assert json_to_ast(ast_to_json(original)) == original

    def test_rule_no_children(self):
        original = [b"rule", b"r1", [b"action"], [b"in.txt"], [b"out.txt"]]
        assert json_to_ast(ast_to_json(original)) == original

    def test_rule_with_children(self):
        child = [b"rule", b"c1", [b"action"], [], []]
        original = [b"rule", b"parent", [b"action"], [b"a"], [b"b"], child]
        assert json_to_ast(ast_to_json(original)) == original

    def test_build(self):
        rule = [b"rule", b"r", [b"action"], [], []]
        original = [b"build", b"mybuild", b"7", rule]
        assert json_to_ast(ast_to_json(original)) == original

    def test_husk(self):
        rule = [b"rule", b"r", [b"action"], [], []]
        build = [b"build", b"b", b"1", rule]
        original = [b"husk", b"1", build]
        assert json_to_ast(ast_to_json(original)) == original

    def test_full_demo(self):
        husk_bytes, _ = load_demo()
        tree = parse(husk_bytes)
        assert json_to_ast(ast_to_json(tree)) == tree


# -- Atom edge cases -----------------------------------------------------------

class TestAtomEdgeCases:
    """NIL, UTF-8, and numeric-looking atoms."""

    def test_nil_round_trips(self):
        oracle = [b"oracle", NIL, b"prompt", [], b"1"]
        j = ast_to_json(oracle)
        assert j["name"] is None
        rt = json_to_ast(j)
        assert rt[1] == NIL

    def test_utf8_prompt(self):
        prompt = "Héllo wörld! \U0001f389".encode("utf-8")
        oracle = [b"oracle", b"n", prompt, [], b"1"]
        rt = json_to_ast(ast_to_json(oracle))
        assert rt[2] == prompt

    def test_numeric_atoms_stay_strings(self):
        build = [b"build", b"b", b"42", [b"rule", b"r", [b"action"], [], []]]
        j = ast_to_json(build)
        assert j["fuel"] == "42"
        assert isinstance(j["fuel"], str)

    def test_json_string_round_trip(self):
        """to_json_str / from_json_str produce identical CSE trees."""
        husk_bytes, _ = load_demo()
        tree = parse(husk_bytes)
        json_str = to_json_str(tree)
        tree2 = from_json_str(json_str)
        assert tree2 == tree
        assert encode(tree2) == husk_bytes
