"""test_bijection.py -- CSE<->JSON round-trip for all form types."""

import pytest
from kernel import encode, parse, NIL
from forms import ast_to_json, json_to_ast, to_json_str, from_json_str, round_trip


# ── Atom round-trips ─────────────────────────────────────────────

class TestAtomBijection:
    def test_nil_atom(self):
        assert ast_to_json(NIL) is None
        assert json_to_ast(None) == NIL

    def test_string_atom(self):
        assert ast_to_json(b"hello") == "hello"
        assert json_to_ast("hello") == b"hello"

    def test_utf8_atom(self):
        val = "café"
        assert json_to_ast(ast_to_json(val.encode("utf-8"))) == val.encode("utf-8")


# ── Form tag round-trips ────────────────────────────────────────

class TestFormBijection:
    def test_action(self):
        tree = [b"action"]
        assert json_to_ast(ast_to_json(tree)) == tree

    def test_commit(self):
        tree = [b"commit", b"ok"]
        assert json_to_ast(ast_to_json(tree)) == tree

    def test_halt(self):
        tree = [b"halt", b"timeout"]
        assert json_to_ast(ast_to_json(tree)) == tree

    def test_oracle(self):
        tree = [b"oracle", b"gpt", b"Do it.", [b"read", b"write"], b"5"]
        assert json_to_ast(ast_to_json(tree)) == tree

    def test_oracle_nil_name(self):
        tree = [b"oracle", NIL, b"prompt", [b"t1"], b"8"]
        assert json_to_ast(ast_to_json(tree)) == tree

    def test_trial(self):
        tree = [b"trial", [b"action"], [b"action"]]
        assert json_to_ast(ast_to_json(tree)) == tree

    def test_cond(self):
        tree = [b"cond", b"file-exists:x", [b"commit", b"yes"], [b"halt", b"no"]]
        assert json_to_ast(ast_to_json(tree)) == tree

    def test_let(self):
        tree = [b"let", b"shared", [b"action"]]
        assert json_to_ast(ast_to_json(tree)) == tree

    def test_rule(self):
        tree = [b"rule", b"worker", [b"action"], [b"in.txt"], [b"out.txt"]]
        assert json_to_ast(ast_to_json(tree)) == tree

    def test_rule_with_children(self):
        child = [b"rule", b"dep", [b"action"], [b"a.txt"], [b"in.txt"]]
        tree = [b"rule", b"worker", [b"action"], [b"in.txt"], [b"out.txt"], child]
        assert json_to_ast(ast_to_json(tree)) == tree

    def test_build(self):
        target = [b"rule", b"r", [b"action"], [], [b"x"]]
        tree = [b"build", b"demo", b"10", target]
        assert json_to_ast(ast_to_json(tree)) == tree

    def test_husk(self):
        target = [b"rule", b"r", [b"action"], [], [b"x"]]
        build = [b"build", b"demo", b"10", target]
        tree = [b"husk", b"1", build]
        assert json_to_ast(ast_to_json(tree)) == tree


# ── Wire round-trip ──────────────────────────────────────────────

class TestWireRoundTrip:
    def test_demo_vector_round_trip(self, demo_vector):
        husk_bytes, _, _ = demo_vector
        assert round_trip(husk_bytes) == husk_bytes

    @pytest.mark.parametrize("name", ["demo", "adversarial"])
    def test_canonical_vectors_round_trip(self, name):
        """Vectors with only standard form tags round-trip through JSON losslessly."""
        import importlib, sys, pathlib
        spec = importlib.util.spec_from_file_location(
            "l1_conftest", str(pathlib.Path(__file__).parent / "conftest.py"))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        husk_bytes, _, _ = mod._load_vector(name)
        assert round_trip(husk_bytes) == husk_bytes

    def test_encode_parse_json_cycle(self):
        tree = [b"husk", b"1", [b"build", b"t", b"5",
                [b"rule", b"r", [b"action"], [b"a"], [b"b"]]]]
        wire = encode(tree)
        assert round_trip(wire) == wire


# ── Convenience wrappers ─────────────────────────────────────────

class TestConvenience:
    def test_to_from_json_str(self):
        tree = [b"commit", b"done"]
        s = to_json_str(tree)
        assert from_json_str(s) == tree

    def test_json_str_is_valid_json(self):
        tree = [b"halt", b"err"]
        import json
        parsed = json.loads(to_json_str(tree))
        assert parsed["form"] == "halt"


# ── Error cases ──────────────────────────────────────────────────

class TestErrors:
    def test_unknown_cse_tag_raises(self):
        with pytest.raises(ValueError, match="Unknown CSE form tag"):
            ast_to_json([b"bogus", b"data"])

    def test_unknown_json_form_raises(self):
        with pytest.raises(ValueError, match="Unknown JSON form"):
            json_to_ast({"form": "bogus"})
