"""
_parser.py -- Parser for Locke surface syntax.

Provides AST node classes and parse function.
"""

from __future__ import annotations

from typing import Any

from ._tokenizer import _TT, Token, _RULE_KEYWORDS, _DECL_KEYWORDS


# ── AST types ────────────────────────────────────────────────────

class DeclNode:
    """Top-level realization: ``value := label``."""
    __slots__ = ("label", "value")

    def __init__(self, label: str, value: Any):
        self.label = label
        self.value = value

    def __repr__(self) -> str:
        return f"DeclNode({self.value!r} := {self.label})"


class RuleNode:
    """A rule definition: ``name :- kind [block]`` or ``name := kind [block]``."""
    __slots__ = ("name", "kind", "decls", "children", "refs", "is_target")

    def __init__(
        self,
        name: str,
        kind: str,
        decls: list[tuple[str, Any]] | None = None,
        children: list[Any] | None = None,
        refs: list[str] | None = None,
        is_target: bool = False,
    ):
        self.name = name
        self.kind = kind
        self.decls = decls or []       # (label, value) pairs from := inside block
        self.children = children or [] # nested RuleNode / LetNode
        self.refs = refs or []         # bare name references (e.g. cond predicate)
        self.is_target = is_target


class LetNode:
    """A let scope: ``:- let [bindings... body...]``."""
    __slots__ = ("items",)

    def __init__(self, items: list[Any] | None = None):
        self.items = items or []  # mix of RuleNode / LetNode


class BindNode:
    """A plain top-level binding: ``name :- expr``."""
    __slots__ = ("name", "expr")

    def __init__(self, name: str, expr: Any):
        self.name = name
        self.expr = expr


# ── Parser ───────────────────────────────────────────────────────

class _Parser:
    def __init__(self, tokens: list[Token]):
        self.tokens = tokens
        self.pos = 0

    def peek(self) -> Token:
        return self.tokens[self.pos]

    def peek2(self) -> Token | None:
        if self.pos + 1 < len(self.tokens):
            return self.tokens[self.pos + 1]
        return None

    def advance(self) -> Token:
        t = self.tokens[self.pos]
        self.pos += 1
        return t

    def expect(self, type: str) -> Token:
        t = self.advance()
        if t.type != type:
            raise SyntaxError(
                f"expected {type}, got {t.type} ({t.value!r}) "
                f"at line {t.line}, col {t.col}"
            )
        return t

    def at_end(self) -> bool:
        return self.peek().type == _TT.EOF

    # ── Top-level ────────────────────────────────────────────

    def parse_program(self) -> list:
        """Parse the full program into a list of AST nodes."""
        nodes: list = []
        while not self.at_end():
            nodes.append(self.parse_top_level())
        return nodes

    def parse_top_level(self):
        """Dispatch a top-level form."""
        # Look ahead to determine the form:
        #   expr := label       -> DeclNode or target RuleNode
        #   ident :- kind [...]  -> RuleNode
        #   ident :- expr        -> BindNode

        t = self.peek()
        t2 = self.peek2()

        # :- let [...] at top level (anonymous let)
        if t.type == _TT.BIND and t2 and t2.type == _TT.BAREWORD and t2.value == "let":
            self.advance()  # :-
            self.advance()  # let
            return self._parse_let_block()

        # We need to figure out if this is:
        #   value := label          (top-level decl or target rule)
        #   ident :- kind [block]   (rule)
        #   ident :- expr           (plain binding)
        #
        # Strategy: parse the first expr, then look at the operator.

        # Save position for backtracking
        saved = self.pos
        first = self._parse_lead()

        op = self.peek()
        if op.type == _TT.DECL:
            # value := label
            self.advance()  # :=
            return self._parse_decl_rhs(first)

        if op.type == _TT.BIND:
            # name :- ...
            self.advance()  # :-
            name = self._lead_to_str(first)
            return self._parse_bind_rhs(name)

        raise SyntaxError(
            f"expected := or :-, got {op.type} ({op.value!r}) "
            f"at line {op.line}, col {op.col}"
        )

    def _parse_lead(self) -> Any:
        """Parse the leading expression (LHS of := or :-)."""
        t = self.peek()
        if t.type == _TT.LBRACKET:
            return self._parse_cell()
        return self._parse_atom()

    def _lead_to_str(self, val: Any) -> str:
        """Convert a leading value to a string name."""
        if isinstance(val, str):
            return val
        if isinstance(val, (int, float)):
            return str(val)
        raise SyntaxError(f"expected identifier, got {val!r}")

    def _parse_decl_rhs(self, value: Any) -> Any:
        """After ``value :=``, parse the label."""
        t = self.advance()
        if t.type != _TT.BAREWORD:
            raise SyntaxError(
                f"expected label after :=, got {t.type} ({t.value!r}) "
                f"at line {t.line}, col {t.col}"
            )
        label = t.value

        # Check if this is a top-level decl keyword
        if label in _DECL_KEYWORDS:
            # site has a bracketed import list: path/ := site [file1 file2 ...]
            if label == "site" and self.peek().type == _TT.LBRACKET:
                imports = self._parse_cell()
                return DeclNode(label, (value, imports))
            return DeclNode(label, value)

        # Check if this is a rule keyword — means target rule
        if label in _RULE_KEYWORDS:
            name = self._lead_to_str(value)
            block = self._parse_block()
            return RuleNode(name, label, *self._unpack_block(block), is_target=True)

        raise SyntaxError(
            f"unknown label {label!r} after :=, expected a declaration "
            f"keyword or rule keyword at line {t.line}, col {t.col}"
        )

    def _parse_bind_rhs(self, name: str) -> Any:
        """After ``name :-``, parse the body."""
        t = self.peek()

        # Rule keyword -> RuleNode
        if t.type == _TT.BAREWORD and t.value in _RULE_KEYWORDS:
            kind = self.advance().value
            if kind == "let":
                let_node = self._parse_let_block()
                # Wrap as named let
                return RuleNode(name, "let", children=[let_node])
            block = self._parse_block()
            return RuleNode(name, kind, *self._unpack_block(block))

        # Plain expression
        expr = self._parse_expr()
        return BindNode(name, expr)

    # ── Block parsing ────────────────────────────────────────

    def _parse_block(self) -> list:
        """Parse ``[ ... ]`` returning raw block items."""
        self.expect(_TT.LBRACKET)
        items: list = []
        while self.peek().type != _TT.RBRACKET:
            items.append(self._parse_block_item())
        self.expect(_TT.RBRACKET)
        return items

    def _parse_block_item(self) -> Any:
        """Parse one item inside a block.

        Returns one of:
          ("decl", label, value)     — value := label
          ("rule", RuleNode)         — name :- kind [...]
          ("let", LetNode)           — :- let [...]
          ("ref", name)              — bare name reference
        """
        t = self.peek()
        t2 = self.peek2()

        # :- at start of item -> sub-rule or let
        if t.type == _TT.BIND:
            self.advance()  # :-
            kw = self.peek()
            if kw.type == _TT.BAREWORD and kw.value == "let":
                self.advance()  # let
                return ("let", self._parse_let_block())
            raise SyntaxError(
                f"expected 'let' after bare :- in block, got {kw.value!r} "
                f"at line {kw.line}, col {kw.col}"
            )

        # Try to detect the three main patterns:
        #   expr := label
        #   ident :- kind [block]
        #   bare-ref

        # Save position
        saved = self.pos
        first = self._parse_lead()
        op = self.peek()

        if op.type == _TT.DECL:
            # value := label
            self.advance()
            label_tok = self.advance()
            if label_tok.type != _TT.BAREWORD:
                raise SyntaxError(
                    f"expected label after :=, got {label_tok.type} ({label_tok.value!r}) "
                    f"at line {label_tok.line}, col {label_tok.col}"
                )
            return ("decl", label_tok.value, first)

        if op.type == _TT.BIND:
            # name :- kind [block]
            self.advance()
            name = self._lead_to_str(first)
            kw = self.peek()
            if kw.type == _TT.BAREWORD and kw.value in _RULE_KEYWORDS:
                kind = self.advance().value
                if kind == "let":
                    let_node = self._parse_let_block()
                    return ("rule", RuleNode(name, "let", children=[let_node]))
                block = self._parse_block()
                decls, children, refs = self._unpack_block(block)
                return ("rule", RuleNode(name, kind, decls, children, refs))
            raise SyntaxError(
                f"expected rule keyword after :-, got {kw.value!r} "
                f"at line {kw.line}, col {kw.col}"
            )

        # Bare reference — just a name (used in cond for predicate rule ref)
        # We already consumed first; if it's a bareword it's a ref
        if isinstance(first, str) and op.type not in (_TT.DECL, _TT.BIND):
            return ("ref", first)

        raise SyntaxError(
            f"unexpected block item at line {op.line}, col {op.col}"
        )

    def _parse_let_block(self) -> LetNode:
        """Parse the contents of a let: ``[ items... ]``."""
        self.expect(_TT.LBRACKET)
        items: list = []
        while self.peek().type != _TT.RBRACKET:
            item = self._parse_block_item()
            if item[0] == "rule":
                items.append(item[1])
            elif item[0] == "let":
                items.append(item[1])
            elif item[0] == "ref":
                # bare ref inside let body
                items.append(item[1])
            else:
                raise SyntaxError(
                    f"unexpected {item[0]} inside let block"
                )
        self.expect(_TT.RBRACKET)
        return LetNode(items)

    def _unpack_block(self, items: list) -> tuple[list, list, list]:
        """Unpack raw block items into (decls, children, refs)."""
        decls: list[tuple[str, Any]] = []
        children: list = []
        refs: list[str] = []
        for item in items:
            if item[0] == "decl":
                decls.append((item[1], item[2]))
            elif item[0] == "rule":
                children.append(item[1])
            elif item[0] == "let":
                children.append(item[1])
            elif item[0] == "ref":
                refs.append(item[1])
        return decls, children, refs

    # ── Expressions ──────────────────────────────────────────

    def _parse_expr(self) -> Any:
        t = self.peek()
        if t.type == _TT.LBRACKET:
            return self._parse_cell()
        return self._parse_atom()

    def _parse_cell(self) -> list:
        self.expect(_TT.LBRACKET)
        items: list = []
        while self.peek().type != _TT.RBRACKET:
            items.append(self._parse_expr())
        self.expect(_TT.RBRACKET)
        return items

    def _parse_atom(self) -> Any:
        t = self.advance()
        if t.type == _TT.STRING:
            return t.value
        if t.type == _TT.INT:
            return int(t.value)
        if t.type == _TT.FLOAT:
            return float(t.value)
        if t.type == _TT.BAREWORD:
            return t.value
        raise SyntaxError(
            f"expected atom, got {t.type} ({t.value!r}) "
            f"at line {t.line}, col {t.col}"
        )


def parse(tokens: list[Token]) -> list:
    """Parse a token list into a list of AST nodes."""
    return _Parser(tokens).parse_program()
