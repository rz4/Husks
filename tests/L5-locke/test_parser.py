"""test_parser.py -- Parser and resolver tests."""

import os
import pytest
from husks.locke import (
    tokenize, parse, resolve, from_file,
    DeclNode, RuleNode, LetNode, BindNode,
)


# ── Parser AST ───────────────────────────────────────────────────

class TestParserDecl:
    def test_public_decl(self):
        ast = parse(tokenize('"demo" := public'))
        assert len(ast) == 1
        assert isinstance(ast[0], DeclNode)
        assert ast[0].label == "public"
        assert ast[0].value == "demo"

    def test_fuel_decl(self):
        ast = parse(tokenize("10 := fuel"))
        assert ast[0].label == "fuel"
        assert ast[0].value == 10

    def test_site_inputs_decl(self):
        ast = parse(tokenize("[a b c d] := site-inputs"))
        assert isinstance(ast[0], DeclNode)
        assert ast[0].label == "site-inputs"


class TestParserRule:
    def test_oracle_rule(self):
        src = 'worker := oracle [\n  "do it" := prompt\n  8 := fuel\n  [out.txt] := outputs\n]'
        ast = parse(tokenize(src))
        assert len(ast) == 1
        r = ast[0]
        assert isinstance(r, RuleNode)
        assert r.name == "worker"
        assert r.kind == "oracle"
        assert r.is_target

    def test_action_rule_with_run(self):
        src = 'builder :- action [\n  "make build" := run\n  [out.txt] := outputs\n]'
        ast = parse(tokenize(src))
        r = ast[0]
        assert isinstance(r, RuleNode)
        assert r.kind == "action"
        assert not r.is_target  # :- not :=

    def test_commit(self):
        src = 'done :- commit [\n  "ok" := value\n]'
        ast = parse(tokenize(src))
        assert ast[0].kind == "commit"

    def test_halt(self):
        src = 'fail :- halt [\n  "timeout" := reason\n]'
        ast = parse(tokenize(src))
        assert ast[0].kind == "halt"

    def test_cond_rule(self):
        src = 'check :- cond [\n  "file-exists:x" := predicate\n  a := then\n  b := else\n]'
        ast = parse(tokenize(src))
        assert ast[0].kind == "cond"

    def test_nested_children(self):
        src = '''
        parent := oracle [
            "go" := prompt
            8 := fuel
            [out.txt] := outputs
            child :- action [
                "make" := run
                [dep.txt] := outputs
            ]
        ]
        '''
        ast = parse(tokenize(src))
        r = ast[0]
        assert len(r.children) == 1
        assert isinstance(r.children[0], RuleNode)
        assert r.children[0].name == "child"

    def test_trial_rule(self):
        src = '''
        t :- trial [
            [out.txt] := outputs
            b1 :- oracle [
                "try a" := prompt
                4 := fuel
            ]
            b2 :- oracle [
                "try b" := prompt
                4 := fuel
            ]
        ]
        '''
        ast = parse(tokenize(src))
        r = ast[0]
        assert r.kind == "trial"
        assert len(r.children) == 2


class TestParserLet:
    def test_let_block(self):
        src = '''
        shared :- let [
            inner :- oracle [
                "prompt" := prompt
                4 := fuel
                [x.txt] := outputs
            ]
        ]
        '''
        ast = parse(tokenize(src))
        r = ast[0]
        assert r.kind == "let"
        assert len(r.children) == 1


class TestParserBind:
    def test_plain_binding(self):
        src = 'x :- 42'
        ast = parse(tokenize(src))
        assert isinstance(ast[0], BindNode)
        assert ast[0].name == "x"
        assert ast[0].expr == 42


class TestParserErrors:
    def test_missing_operator(self):
        with pytest.raises(SyntaxError, match="expected"):
            parse(tokenize("hello world"))

    def test_unknown_label(self):
        with pytest.raises(SyntaxError, match="unknown label"):
            parse(tokenize("x := bogus"))


# ── Resolver ─────────────────────────────────────────────────────

class TestResolve:
    def test_basic_design(self):
        src = '"demo" := public\n10 := fuel\nworker := oracle [\n  "do it" := prompt\n  8 := fuel\n  [out.txt] := outputs\n]'
        ast = parse(tokenize(src))
        d = resolve(ast)
        assert d["name"] == "demo"
        assert d["fuel"] == 10
        assert d["target"] == "worker"
        assert len(d["rules"]) == 1
        assert d["rules"][0]["kind"] == "oracle"
        assert d["rules"][0]["prompt"] == "do it"

    def test_action_with_run(self):
        src = '"test" := public\n5 := fuel\nw := action [\n  "make" := run\n  [x.txt] := outputs\n]'
        ast = parse(tokenize(src))
        d = resolve(ast)
        assert d["rules"][0]["run"] == "make"

    def test_commit_halt(self):
        src = '"test" := public\n5 := fuel\ndone :- commit [\n  "ok" := value\n]\nfail :- halt [\n  "err" := reason\n]\nw := oracle [\n  "go" := prompt\n  4 := fuel\n  [x] := outputs\n]'
        ast = parse(tokenize(src))
        d = resolve(ast)
        rules = {r["name"]: r for r in d["rules"]}
        assert rules["done"]["kind"] == "commit"
        assert rules["fail"]["kind"] == "halt"

    def test_prompt_from_file(self, tmp_path):
        prompt_file = tmp_path / "prompt.txt"
        prompt_file.write_text("Do the thing.")
        src = f'"test" := public\n5 := fuel\nw := oracle [\n  prompt.txt := prompt\n  4 := fuel\n  [out.txt] := outputs\n]'
        ast = parse(tokenize(src))
        d = resolve(ast, str(tmp_path))
        assert d["rules"][0]["prompt"] == "Do the thing."

    def test_free_exact_outputs(self):
        src = '"test" := public\n5 := fuel\nw := oracle [\n  "go" := prompt\n  4 := fuel\n  [a.txt] := free\n  [b.txt] := exact\n]'
        ast = parse(tokenize(src))
        d = resolve(ast)
        r = d["rules"][0]
        assert r["outputs"] == ["a.txt", "b.txt"]
        assert r["equivalence"]["a.txt"] == "free"
        assert r["equivalence"]["b.txt"] == "exact"

    def test_cond_resolve(self):
        src = '''
        "test" := public
        5 := fuel
        a :- commit ["ok" := value]
        b :- halt ["no" := reason]
        gate :- cond [
            "file-exists:x" := predicate
            a := then
            b := else
        ]
        '''
        d = resolve(parse(tokenize(src)))
        rules = {r["name"]: r for r in d["rules"]}
        assert rules["gate"]["predicate"] == "file-exists:x"
        assert rules["gate"]["then"] == "a"
        assert rules["gate"]["else"] == "b"

    def test_trial_branches(self):
        src = '''
        "test" := public
        5 := fuel
        t := trial [
            [out.txt] := outputs
            b1 :- oracle ["try a" := prompt  4 := fuel]
            b2 :- oracle ["try b" := prompt  4 := fuel]
        ]
        '''
        d = resolve(parse(tokenize(src)))
        r = d["rules"][0]
        assert r["kind"] == "trial"
        assert len(r["branches"]) == 2
        assert r["branches"][0]["prompt"] == "try a"


class TestFromFile:
    def test_from_file(self, tmp_path):
        p = tmp_path / "test.locke"
        p.write_text('"test" := public\n5 := fuel\nw := oracle [\n  "go" := prompt\n  4 := fuel\n  [out.txt] := outputs\n]')
        d = from_file(str(p))
        assert d["name"] == "test"
        assert d["_source_path"] == str(p.resolve())
