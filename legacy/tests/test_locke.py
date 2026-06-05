"""Tests for the Locke surface language parser and compiler."""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from husks.design.locke import (
    tokenize, parse, resolve, from_file, compile_bytes,
    _TT, DeclNode, RuleNode, BindNode, LetNode,
)


# ── Tokenizer tests ─────────────────────────────────────────────

class TestTokenizer:
    def test_bind_token(self):
        tokens = tokenize('name :- "hello"')
        types = [t.type for t in tokens]
        assert types == [_TT.BAREWORD, _TT.BIND, _TT.STRING, _TT.EOF]

    def test_decl_token(self):
        tokens = tokenize('"x" := public')
        types = [t.type for t in tokens]
        assert types == [_TT.STRING, _TT.DECL, _TT.BAREWORD, _TT.EOF]

    def test_integer(self):
        tokens = tokenize("20 := fuel")
        assert tokens[0].type == _TT.INT
        assert tokens[0].value == "20"

    def test_float(self):
        tokens = tokenize("[0.5 2.0]")
        assert tokens[1].type == _TT.FLOAT
        assert tokens[1].value == "0.5"

    def test_brackets(self):
        tokens = tokenize("[a b c]")
        types = [t.type for t in tokens]
        assert types == [_TT.LBRACKET, _TT.BAREWORD, _TT.BAREWORD,
                         _TT.BAREWORD, _TT.RBRACKET, _TT.EOF]

    def test_comment_skipped(self):
        tokens = tokenize("# comment\n20 := fuel")
        types = [t.type for t in tokens if t.type != _TT.EOF]
        assert types == [_TT.INT, _TT.DECL, _TT.BAREWORD]

    def test_bareword_with_slashes(self):
        tokens = tokenize("readers/generated_reader.py")
        assert tokens[0].type == _TT.BAREWORD
        assert tokens[0].value == "readers/generated_reader.py"

    def test_unterminated_string_error(self):
        with pytest.raises(SyntaxError, match="unterminated string"):
            tokenize('"hello')

    def test_unexpected_char_error(self):
        with pytest.raises(SyntaxError, match="unexpected character"):
            tokenize("~bad")

    def test_line_numbers(self):
        tokens = tokenize('"a" := public\n20 := fuel')
        assert tokens[0].line == 1
        assert tokens[3].line == 2


# ── Parser tests ─────────────────────────────────────────────────

class TestParser:
    def test_decl_public(self):
        ast = parse(tokenize('"my-build" := public'))
        assert len(ast) == 1
        assert isinstance(ast[0], DeclNode)
        assert ast[0].label == "public"
        assert ast[0].value == "my-build"

    def test_decl_fuel(self):
        ast = parse(tokenize("20 := fuel"))
        assert isinstance(ast[0], DeclNode)
        assert ast[0].label == "fuel"
        assert ast[0].value == 20

    def test_decl_site_inputs(self):
        ast = parse(tokenize('["a" "b" "c" "d"] := site-inputs'))
        assert isinstance(ast[0], DeclNode)
        assert ast[0].label == "site-inputs"
        assert ast[0].value == ["a", "b", "c", "d"]

    def test_decl_cost_tolerance(self):
        ast = parse(tokenize("[0.5 2.0] := cost-tolerance"))
        assert isinstance(ast[0], DeclNode)
        assert ast[0].label == "cost-tolerance"
        assert ast[0].value == [0.5, 2.0]

    def test_target_rule(self):
        src = 'go := action [\n  [out.txt] := outputs\n  "echo ok" := run\n]'
        ast = parse(tokenize(src))
        assert len(ast) == 1
        r = ast[0]
        assert isinstance(r, RuleNode)
        assert r.name == "go"
        assert r.kind == "action"
        assert r.is_target is True
        assert ("outputs", ["out.txt"]) in r.decls
        assert ("run", "echo ok") in r.decls

    def test_bind_rule(self):
        src = 'gen :- oracle [\n  [a b] := inputs\n  15 := fuel\n]'
        ast = parse(tokenize(src))
        r = ast[0]
        assert isinstance(r, RuleNode)
        assert r.name == "gen"
        assert r.kind == "oracle"
        assert r.is_target is False

    def test_nested_child(self):
        src = textwrap.dedent('''\
            parent := action [
              [out.txt] := outputs
              "echo" := run
              child :- action [
                [in.txt] := inputs
                [dep.txt] := outputs
                "make" := run
              ]
            ]
        ''')
        ast = parse(tokenize(src))
        parent = ast[0]
        assert isinstance(parent, RuleNode)
        assert len(parent.children) == 1
        child = parent.children[0]
        assert isinstance(child, RuleNode)
        assert child.name == "child"
        assert child.kind == "action"

    def test_plain_binding(self):
        src = 'name :- "hello"'
        ast = parse(tokenize(src))
        assert isinstance(ast[0], BindNode)
        assert ast[0].name == "name"
        assert ast[0].expr == "hello"

    def test_cond_with_refs(self):
        src = textwrap.dedent('''\
            c :- cond [
              check-rule
              ok :- action [
                [out.txt] := outputs
                "echo yes" := run
              ]
              fail :- halt [
                "nope" := reason
              ]
            ]
        ''')
        ast = parse(tokenize(src))
        r = ast[0]
        assert isinstance(r, RuleNode)
        assert r.kind == "cond"
        assert r.refs == ["check-rule"]
        assert len(r.children) == 2
        assert r.children[0].name == "ok"
        assert r.children[1].name == "fail"


# ── Resolver tests ───────────────────────────────────────────────

class TestResolver:
    def test_decl_metadata(self):
        src = textwrap.dedent('''\
            "test" := public
            10 := fuel
            [0.5 2.0] := cost-tolerance
            ["a" "path/a"] := site-inputs
        ''')
        design = resolve(parse(tokenize(src)))
        assert design["name"] == "test"
        assert design["fuel"] == 10
        assert design["cost_tolerance"] == {"ratio": [0.5, 2.0]}
        assert design["site_inputs"] == {"a": "path/a"}

    def test_first_occurrence_wins(self):
        src = textwrap.dedent('''\
            "first" := public
            "second" := public
            10 := fuel
            99 := fuel
        ''')
        design = resolve(parse(tokenize(src)))
        assert design["name"] == "first"
        assert design["fuel"] == 10

    def test_target_from_decl_rule(self):
        src = textwrap.dedent('''\
            "x" := public
            5 := fuel
            go := action [
              [out.txt] := outputs
              "echo ok" := run
            ]
        ''')
        design = resolve(parse(tokenize(src)))
        assert design["target"] == "go"

    def test_nested_rules_flatten(self):
        src = textwrap.dedent('''\
            "x" := public
            5 := fuel
            parent := action [
              [dep.txt] := inputs
              [out.txt] := outputs
              "echo" := run
              child :- action [
                [in.txt] := inputs
                [dep.txt] := outputs
                "make" := run
              ]
            ]
        ''')
        design = resolve(parse(tokenize(src)))
        rules = design["rules"]
        # child flattened before parent (depth-first)
        assert rules[0]["name"] == "child"
        assert rules[1]["name"] == "parent"

    def test_free_exact_merge(self):
        src = textwrap.dedent('''\
            val := action [
              [x.py] := inputs
              [report.txt] := free
              [VERIFIED] := exact
              "echo ok" := run
            ]
        ''')
        design = resolve(parse(tokenize(src)))
        rule = design["rules"][0]
        assert rule["outputs"] == ["report.txt", "VERIFIED"]
        assert rule["equivalence"] == {
            "report.txt": "free",
            "VERIFIED": "exact",
        }

    def test_plain_outputs_no_equivalence(self):
        src = textwrap.dedent('''\
            build :- action [
              [src.py] := inputs
              [out.bin] := outputs
              "make" := run
            ]
        ''')
        design = resolve(parse(tokenize(src)))
        rule = design["rules"][0]
        assert rule["outputs"] == ["out.bin"]
        assert "equivalence" not in rule

    def test_prompt_file_resolution(self, tmp_path):
        prompt_file = tmp_path / "prompt.txt"
        prompt_file.write_text("Generate code.")

        src = textwrap.dedent('''\
            gen :- oracle [
              [out.py] := free
              prompt.txt := prompt
              [read-file] := tools
              5 := fuel
            ]
        ''')
        design = resolve(parse(tokenize(src)), str(tmp_path))
        assert design["rules"][0]["prompt"] == "Generate code."

    def test_prompt_inline_string(self):
        src = textwrap.dedent('''\
            gen :- oracle [
              [out.py] := free
              "Do the thing." := prompt
              [read-file] := tools
              5 := fuel
            ]
        ''')
        design = resolve(parse(tokenize(src)))
        assert design["rules"][0]["prompt"] == "Do the thing."

    def test_cond_resolution(self):
        src = textwrap.dedent('''\
            c :- cond [
              check-rule
              ok :- action [
                [out.txt] := outputs
                "echo yes" := run
              ]
              fail :- halt [
                "nope" := reason
              ]
            ]
        ''')
        design = resolve(parse(tokenize(src)))
        cond_rule = [r for r in design["rules"] if r["kind"] == "cond"][0]
        assert cond_rule["predicate"] == "check-rule"
        assert cond_rule["then"] == "ok"
        assert cond_rule["else"] == "fail"

    def test_odd_site_inputs_error(self):
        src = '["a" "b" "c"] := site-inputs'
        with pytest.raises(ValueError, match="even number"):
            resolve(parse(tokenize(src)))

    def test_legacy_bind_still_works(self):
        src = textwrap.dedent('''\
            name :- "test"
            fuel :- 10
            target :- "build"
        ''')
        design = resolve(parse(tokenize(src)))
        assert design["name"] == "test"
        assert design["fuel"] == 10
        assert design["target"] == "build"


# ── from_file tests ──────────────────────────────────────────────

class TestFromFile:
    def test_loads_locke_file(self, tmp_path):
        locke = tmp_path / "test.locke"
        locke.write_text(textwrap.dedent('''\
            "test-design" := public
            5 := fuel
            go := action [
              [out.txt] := outputs
              "echo ok" := run
            ]
        '''))
        design = from_file(str(locke))
        assert design["name"] == "test-design"
        assert design["fuel"] == 5
        assert design["target"] == "go"
        assert design["_source_path"] == str(locke.resolve())
        assert len(design["rules"]) == 1

    def test_prompt_resolved_relative_to_locke(self, tmp_path):
        prompts = tmp_path / "prompts"
        prompts.mkdir()
        (prompts / "gen.txt").write_text("do something")

        locke = tmp_path / "design.locke"
        locke.write_text(textwrap.dedent('''\
            "link-test" := public
            5 := fuel
            gen := oracle [
              [out.py] := free
              prompts/gen.txt := prompt
              [read-file write-file] := tools
              3 := fuel
            ]
        '''))
        design = from_file(str(locke))
        assert design["rules"][0]["prompt"] == "do something"
        assert design["target"] == "gen"


# ── CSE equivalence test ─────────────────────────────────────────

class TestCSEEquivalence:
    def test_core_bootstrap_matches_json(self):
        """core-bootstrap.locke produces identical CSE bytes to core-bootstrap.json."""
        templates = Path(__file__).parent.parent / "examples" / "templates"
        locke_path = templates / "core-bootstrap.locke"
        json_path = templates / "core-bootstrap.json"

        if not locke_path.exists() or not json_path.exists():
            pytest.skip("template files not found")

        from husks.design.locke import from_json
        from husks.design.transport import elaborate
        from husks.core import encode

        locke_bytes = compile_bytes(
            locke_path.read_text(), base_dir=str(templates)
        )

        json_design = from_json(str(json_path))
        json_bytes = encode(elaborate(json_design))

        assert locke_bytes == json_bytes, "CSE output mismatch between .locke and .json"


# ── Error case tests ─────────────────────────────────────────────

class TestErrors:
    def test_missing_operator(self):
        with pytest.raises(SyntaxError):
            parse(tokenize("name = 1"))

    def test_missing_block_close(self):
        with pytest.raises(SyntaxError):
            parse(tokenize("gen :- oracle [inputs [a]"))

    def test_empty_source(self):
        ast = parse(tokenize(""))
        assert ast == []

    def test_comment_only(self):
        ast = parse(tokenize("# just a comment\n"))
        assert ast == []

    def test_bad_decl_label(self):
        with pytest.raises(SyntaxError, match="unknown label"):
            parse(tokenize('"hello" := bogus'))

    def test_unterminated_string(self):
        with pytest.raises(SyntaxError, match="unterminated string"):
            tokenize('"hello')
