"""test_tokenizer.py -- Lexer and token tests."""

import pytest
from locke import tokenize, _TT, Token


class TestTokenTypes:
    def test_decl_operator(self):
        toks = tokenize(":=")
        assert toks[0].type == _TT.DECL and toks[0].value == ":="

    def test_bind_operator(self):
        toks = tokenize(":-")
        assert toks[0].type == _TT.BIND and toks[0].value == ":-"

    def test_brackets(self):
        toks = tokenize("[ ]")
        assert toks[0].type == _TT.LBRACKET
        assert toks[1].type == _TT.RBRACKET

    def test_string(self):
        toks = tokenize('"hello world"')
        assert toks[0].type == _TT.STRING
        assert toks[0].value == "hello world"

    def test_triple_quoted_string(self):
        toks = tokenize('"""multi\nline"""')
        assert toks[0].type == _TT.STRING
        assert "multi\nline" == toks[0].value

    def test_integer(self):
        toks = tokenize("42")
        assert toks[0].type == _TT.INT and toks[0].value == "42"

    def test_float(self):
        toks = tokenize("3.14")
        assert toks[0].type == _TT.FLOAT and toks[0].value == "3.14"

    def test_bareword(self):
        toks = tokenize("hello-world")
        assert toks[0].type == _TT.BAREWORD and toks[0].value == "hello-world"

    def test_bareword_with_dots_slashes(self):
        toks = tokenize("path/to/file.txt")
        assert toks[0].type == _TT.BAREWORD

    def test_eof(self):
        toks = tokenize("")
        assert toks[0].type == _TT.EOF


class TestComments:
    def test_line_comment(self):
        toks = tokenize("# this is a comment\n42")
        assert toks[0].type == _TT.INT

    def test_comment_only(self):
        toks = tokenize("# just a comment")
        assert toks[0].type == _TT.EOF

    def test_inline_comment(self):
        toks = tokenize('42 # the answer')
        assert toks[0].type == _TT.INT
        assert toks[1].type == _TT.EOF


class TestWhitespace:
    def test_spaces_and_tabs(self):
        toks = tokenize("  \t  42")
        assert toks[0].type == _TT.INT

    def test_newlines(self):
        toks = tokenize("42\n43")
        assert toks[0].type == _TT.INT and toks[0].value == "42"
        assert toks[1].type == _TT.INT and toks[1].value == "43"


class TestLineTracking:
    def test_line_numbers(self):
        toks = tokenize("a\nb\nc")
        assert toks[0].line == 1
        assert toks[1].line == 2
        assert toks[2].line == 3


class TestErrors:
    def test_unterminated_string(self):
        with pytest.raises(SyntaxError, match="unterminated"):
            tokenize('"no close')

    def test_unterminated_triple(self):
        with pytest.raises(SyntaxError, match="unterminated"):
            tokenize('"""no close')

    def test_unexpected_char(self):
        with pytest.raises(SyntaxError, match="unexpected"):
            tokenize("@")


class TestFullTokenization:
    def test_simple_design(self):
        src = '"demo" := public\n10 := fuel\nworker := oracle [\n  "do it" := prompt\n  8 := fuel\n]'
        toks = tokenize(src)
        types = [t.type for t in toks if t.type != _TT.EOF]
        assert _TT.STRING in types
        assert _TT.DECL in types
        assert _TT.BAREWORD in types
        assert _TT.LBRACKET in types
        assert _TT.RBRACKET in types
