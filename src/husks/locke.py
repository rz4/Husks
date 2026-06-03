"""
locke.py -- Square-Lisp-Python surface language for Husks CSE.

Minimal surface language with square brackets, two binding operators,
and structural nesting that compiles to the flat design dict consumed
by ``transport.elaborate()`` and ``core.encode()``.

Zero external dependencies (stdlib only), matching core.py's discipline.

Two operators
-------------

``:=``  realization — value on the left, label on the right.
        Declares something concrete and deterministic.

``:-``  composition — name on the left, kind + block on the right.
        Defines a sub-rule that connects into the build tree.

Inside a rule block:

    ``value := label``   deterministic declaration (inputs, outputs, ...)
    ``name :- kind [...]``  nested sub-rule (child in the DAG)

At the top level:

    ``"core-bootstrap" := public``   build name
    ``20 := fuel``                   fuel budget
    ``rule := action [...]``         target rule (first := rule wins)

Type semantics for ``:=`` values:

    atom (bare word)    file reference — resolved at parse time
    string (quoted)     inline data — embedded in the design
    int / float         numeric literal
    cell (brackets)     list of values

Grammar
-------
::

    program    = (comment | top_decl | top_rule | top_bind)*

    top_decl   = expr ':=' DECL_KW
    top_rule   = IDENT (':=' | ':-') RULE_KW block
    top_bind   = IDENT ':-' expr

    DECL_KW    = 'public' | 'fuel' | 'site-inputs' | 'cost-tolerance'
    RULE_KW    = 'oracle' | 'action' | 'trial' | 'commit' | 'halt' | 'cond' | 'let'

    block      = '[' block_item* ']'
    block_item = expr ':=' IDENT           # realization (value := label)
               | IDENT ':-' RULE_KW block  # sub-rule
               | ':-' 'let' block          # anonymous let scope
               | IDENT                     # bare reference (cond predicate)

    cell       = '[' expr* ']'
    expr       = cell | atom
    atom       = STRING | FLOAT | INT | BAREWORD
    STRING     = '"' [^"]* '"'
    INT        = [0-9]+
    FLOAT      = [0-9]+ '.' [0-9]+
    BAREWORD   = [A-Za-z0-9_./-]+
    comment    = '#' [^\\n]*
"""

from __future__ import annotations

import os
from typing import Any


# ── Token types ──────────────────────────────────────────────────

class _TT:
    IDENT    = "IDENT"
    BIND     = "BIND"      # :-
    DECL     = "DECL"      # :=  (realization)
    LBRACKET = "LBRACKET"  # [
    RBRACKET = "RBRACKET"  # ]
    STRING   = "STRING"
    INT      = "INT"
    FLOAT    = "FLOAT"
    BAREWORD = "BAREWORD"
    EOF      = "EOF"


class Token:
    __slots__ = ("type", "value", "line", "col")

    def __init__(self, type: str, value: str, line: int = 0, col: int = 0):
        self.type = type
        self.value = value
        self.line = line
        self.col = col

    def __repr__(self) -> str:
        return f"Token({self.type}, {self.value!r}, L{self.line})"


# ── Keywords ─────────────────────────────────────────────────────

_RULE_KEYWORDS = frozenset({
    "oracle", "action", "trial", "commit", "halt", "cond", "let",
})

_DECL_KEYWORDS = frozenset({
    "public", "fuel", "site-inputs", "cost-tolerance",
})

# Labels allowed on the right side of := inside a rule block
_BLOCK_LABELS = frozenset({
    "inputs", "outputs", "free", "exact",
    "prompt", "tools", "fuel", "run",
    "value", "reason",
    "predicate", "then", "else",
})


# ── Lexer ────────────────────────────────────────────────────────

def _is_bareword_char(c: str) -> bool:
    return c.isalnum() or c in "_./-"


def tokenize(source: str) -> list[Token]:
    """Lex *source* into a flat list of tokens."""
    tokens: list[Token] = []
    i = 0
    line = 1
    col = 1
    n = len(source)

    while i < n:
        c = source[i]

        # newline
        if c == "\n":
            i += 1
            line += 1
            col = 1
            continue

        # whitespace
        if c in " \t\r":
            i += 1
            col += 1
            continue

        # comment
        if c == "#":
            while i < n and source[i] != "\n":
                i += 1
            continue

        # := (realization) — must check before :-
        if c == ":" and i + 1 < n and source[i + 1] == "=":
            tokens.append(Token(_TT.DECL, ":=", line, col))
            i += 2
            col += 2
            continue

        # :- (composition)
        if c == ":" and i + 1 < n and source[i + 1] == "-":
            tokens.append(Token(_TT.BIND, ":-", line, col))
            i += 2
            col += 2
            continue

        # brackets
        if c == "[":
            tokens.append(Token(_TT.LBRACKET, "[", line, col))
            i += 1
            col += 1
            continue
        if c == "]":
            tokens.append(Token(_TT.RBRACKET, "]", line, col))
            i += 1
            col += 1
            continue

        # string
        if c == '"':
            start_line, start_col = line, col
            i += 1
            col += 1
            buf: list[str] = []
            while i < n and source[i] != '"':
                if source[i] == "\n":
                    line += 1
                    col = 0
                buf.append(source[i])
                i += 1
                col += 1
            if i >= n:
                raise SyntaxError(
                    f"unterminated string starting at line {start_line}, col {start_col}"
                )
            i += 1  # closing quote
            col += 1
            tokens.append(Token(_TT.STRING, "".join(buf), start_line, start_col))
            continue

        # number or bareword
        if c.isdigit() or _is_bareword_char(c):
            start_col = col
            buf = []
            while i < n and _is_bareword_char(source[i]):
                buf.append(source[i])
                i += 1
                col += 1
            word = "".join(buf)
            if _looks_like_float(word):
                tokens.append(Token(_TT.FLOAT, word, line, start_col))
            elif _looks_like_int(word):
                tokens.append(Token(_TT.INT, word, line, start_col))
            else:
                tokens.append(Token(_TT.BAREWORD, word, line, start_col))
            continue

        raise SyntaxError(f"unexpected character {c!r} at line {line}, col {col}")

    tokens.append(Token(_TT.EOF, "", line, col))
    return tokens


def _looks_like_int(word: str) -> bool:
    return word.isdigit()


def _looks_like_float(word: str) -> bool:
    parts = word.split(".")
    return len(parts) == 2 and parts[0].isdigit() and parts[1].isdigit()


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


# ── Resolver ─────────────────────────────────────────────────────

def _resolve_atom_file(val: Any, base_dir: str) -> str:
    """Resolve a bare-word atom as a file path, reading its contents."""
    if not isinstance(val, str):
        return val
    full = os.path.join(base_dir, val)
    try:
        with open(full) as f:
            return f.read()
    except FileNotFoundError:
        raise FileNotFoundError(f"file not found: {full}")


def _resolve_decl_value(label: str, val: Any, base_dir: str) -> Any:
    """Resolve a declaration value based on its label.

    For ``prompt``, bare-word atoms are file references.
    For most labels, values are used as-is (strings are inline,
    atoms are names/paths within the site).
    """
    if label == "prompt":
        # prompt: atom = file to read, string = inline text
        if isinstance(val, str) and not _is_quoted_string(val):
            return _resolve_atom_file(val, base_dir)
        return val
    return val


def _is_quoted_string(val: Any) -> bool:
    """Heuristic: strings from the parser are always str, but atoms
    are also str.  We track this via the AST — prompt resolution
    uses the label context to decide.  By the time we get here,
    strings and atoms are both str; we rely on the caller to know
    which label expects file resolution."""
    return False  # caller handles this via label


def resolve(ast: list, base_dir: str = ".") -> dict[str, Any]:
    """Resolve AST nodes into a flat design dict.

    Transforms the parsed AST into the same dict shape that
    ``from_json()`` produces, ready for ``elaborate()`` and ``compile()``.
    """
    design: dict[str, Any] = {}
    rules: list[dict[str, Any]] = []
    seen_decls: set[str] = set()
    target_name: str | None = None

    for node in ast:
        if isinstance(node, DeclNode):
            if node.label in seen_decls:
                continue
            seen_decls.add(node.label)

            if node.label == "public":
                design["name"] = node.value
            elif node.label == "fuel":
                design["fuel"] = node.value
            elif node.label == "site-inputs":
                design["site_inputs"] = _cell_to_site_inputs(node.value)
            elif node.label == "cost-tolerance":
                design["cost_tolerance"] = {"ratio": node.value}

        elif isinstance(node, RuleNode):
            _flatten_rule(node, rules, base_dir)
            if node.is_target and target_name is None:
                target_name = node.name

        elif isinstance(node, BindNode):
            resolved_name = node.name.replace("-", "_")
            if node.name == "site-inputs":
                design["site_inputs"] = _cell_to_site_inputs(node.expr)
            elif node.name == "cost-tolerance":
                design["cost_tolerance"] = {"ratio": node.expr}
            else:
                design[resolved_name] = node.expr

    if target_name:
        design["target"] = target_name
    if rules:
        design["rules"] = rules

    return design


def _cell_to_site_inputs(cell: list) -> dict[str, str]:
    """Convert ``[k1 v1 k2 v2 ...]`` to a dict."""
    if not isinstance(cell, list) or len(cell) % 2 != 0:
        raise ValueError(
            f"site-inputs must be a cell with even number of elements, got {cell!r}"
        )
    d: dict[str, str] = {}
    for i in range(0, len(cell), 2):
        d[str(cell[i])] = str(cell[i + 1])
    return d


def _collect_outputs(node) -> set[str]:
    """Collect all output paths declared by a RuleNode (including free/exact)."""
    if not isinstance(node, RuleNode):
        return set()
    paths: set[str] = set()
    for label, val in node.decls:
        if label in ("outputs", "free", "exact"):
            if isinstance(val, list):
                paths.update(str(v) for v in val)
            else:
                paths.add(str(val))
    return paths


def _collect_inputs(node) -> set[str]:
    """Collect all input paths declared by a RuleNode."""
    if not isinstance(node, RuleNode):
        return set()
    paths: set[str] = set()
    for label, val in node.decls:
        if label == "inputs":
            if isinstance(val, list):
                paths.update(str(v) for v in val)
            else:
                paths.add(str(val))
    return paths


def _topo_sort_children(children: list) -> list:
    """Sort sibling nodes so producers come before consumers.

    Also ensures cond nodes come after all other siblings, since they
    reference siblings by name.
    """
    if len(children) <= 1:
        return children

    # Build output->node index
    output_to_idx: dict[str, int] = {}
    for i, child in enumerate(children):
        for path in _collect_outputs(child):
            output_to_idx[path] = i

    # Build dependency graph: child i depends on child j
    n = len(children)
    deps: list[set[int]] = [set() for _ in range(n)]
    for i, child in enumerate(children):
        # Input dependencies
        for path in _collect_inputs(child):
            j = output_to_idx.get(path)
            if j is not None and j != i:
                deps[i].add(j)
        # Cond nodes depend on all non-cond siblings
        if isinstance(child, RuleNode) and child.kind == "cond":
            for j in range(n):
                if j != i:
                    deps[i].add(j)

    # Kahn's algorithm
    in_degree = [len(d) for d in deps]
    rdeps: list[set[int]] = [set() for _ in range(n)]
    for i in range(n):
        for j in deps[i]:
            rdeps[j].add(i)

    queue = [i for i in range(n) if in_degree[i] == 0]
    order: list[int] = []
    while queue:
        # Stable: pick lowest index first
        queue.sort()
        i = queue.pop(0)
        order.append(i)
        for k in rdeps[i]:
            in_degree[k] -= 1
            if in_degree[k] == 0:
                queue.append(k)

    # If cycle detected, fall back to original order
    if len(order) != n:
        return children

    return [children[i] for i in order]


def _flatten_rule(
    node: RuleNode,
    rules: list[dict],
    base_dir: str,
    _seen: set[str] | None = None,
) -> None:
    """Recursively flatten a RuleNode tree into the flat rules list.

    Trial branches are NOT flattened as standalone rules — they become
    inline recipe dicts in the parent trial's ``branches`` list.

    All other children are flattened depth-first (leaves before parents)
    so the flat list has no forward references.
    """
    if _seen is None:
        _seen = set()

    # Guard against duplicate flattening (shared nodes via let)
    if node.name in _seen:
        return
    _seen.add(node.name)

    # Collect children to flatten (skip trial branches — they stay inline).
    to_flatten: list = []
    for child in node.children:
        if node.kind == "trial" and isinstance(child, RuleNode):
            continue
        to_flatten.append(child)

    # Topologically sort siblings: producers before consumers, conds last.
    to_flatten = _topo_sort_children(to_flatten)

    for child in to_flatten:
        if isinstance(child, RuleNode):
            _flatten_rule(child, rules, base_dir, _seen)
        elif isinstance(child, LetNode):
            _flatten_let(child, rules, base_dir, _seen)

    # Build the rule dict
    rule: dict[str, Any] = {"name": node.name, "kind": node.kind}

    free_list: list[str] = []
    exact_list: list[str] = []

    for label, val in node.decls:
        if label == "inputs":
            rule["inputs"] = _to_str_list(val)
        elif label == "outputs":
            rule["outputs"] = _to_str_list(val)
        elif label == "free":
            free_list = _to_str_list(val)
        elif label == "exact":
            exact_list = _to_str_list(val)
        elif label == "tools":
            rule["tools"] = _to_str_list(val)
        elif label == "fuel":
            rule["fuel"] = int(val) if not isinstance(val, int) else val
        elif label == "prompt":
            rule["prompt"] = _resolve_prompt(val, base_dir)
        elif label == "run":
            rule["run"] = str(val)
        elif label == "value":
            rule["value"] = str(val)
        elif label == "reason":
            rule["reason"] = str(val)
        else:
            rule[label] = val

    # Merge free/exact into outputs + equivalence
    if free_list or exact_list:
        outputs = free_list + exact_list
        rule["outputs"] = outputs
        # Trial rules don't carry equivalence — only producing rules do
        if node.kind != "trial":
            equivalence: dict[str, str] = {}
            for p in free_list:
                equivalence[p] = "free"
            for p in exact_list:
                equivalence[p] = "exact"
            if equivalence:
                rule["equivalence"] = equivalence

    # Handle cond: predicate/then/else come from decls or refs
    if node.kind == "cond":
        _resolve_cond(node, rule, base_dir)

    # Handle trial: children become inline branch recipe dicts
    if node.kind == "trial":
        _resolve_trial(node, rule, base_dir)

    # Handle let: bind field references the bound rule
    if node.kind == "let":
        if node.children:
            child = node.children[0]
            if isinstance(child, LetNode) and child.items:
                first = child.items[0]
                rule["bind"] = first.name if isinstance(first, RuleNode) else str(first)
            elif isinstance(child, RuleNode):
                rule["bind"] = child.name

    rules.append(rule)


def _flatten_let(
    node: LetNode, rules: list[dict], base_dir: str,
    _seen: set[str] | None = None,
) -> None:
    """Flatten all items inside a let scope."""
    if _seen is None:
        _seen = set()
    for item in node.items:
        if isinstance(item, RuleNode):
            _flatten_rule(item, rules, base_dir, _seen)
        elif isinstance(item, LetNode):
            _flatten_let(item, rules, base_dir, _seen)


def _resolve_cond(node: RuleNode, rule: dict, base_dir: str) -> None:
    """Map cond to predicate/then/else fields.

    Cond fields come from := declarations inside the block:
        "file-exists:parser/VERIFIED" := predicate
        ok-branch                     := then
        fail-branch                   := else

    For backwards compat, also supports bare refs (first ref = predicate).
    """
    # Declarations set predicate/then/else directly
    for label, val in node.decls:
        if label == "predicate":
            rule["predicate"] = str(val)
        elif label == "then":
            rule["then"] = str(val)
        elif label == "else":
            rule["else"] = str(val)

    # Fallback: bare refs (legacy positional style)
    if "predicate" not in rule and node.refs:
        rule["predicate"] = node.refs[0]
    children = [c for c in node.children if isinstance(c, RuleNode)]
    if "then" not in rule and len(children) >= 1:
        rule["then"] = children[0].name
    if "else" not in rule and len(children) >= 2:
        rule["else"] = children[1].name


def _resolve_trial(node: RuleNode, rule: dict, base_dir: str) -> None:
    """Map trial children to inline branch recipe dicts."""
    branches = []
    for child in node.children:
        if isinstance(child, RuleNode):
            branch: dict[str, Any] = {"kind": child.kind}
            for label, val in child.decls:
                if label == "prompt":
                    branch["prompt"] = _resolve_prompt(val, base_dir)
                elif label == "tools":
                    branch["tools"] = _to_str_list(val)
                elif label == "fuel":
                    branch["fuel"] = int(val) if not isinstance(val, int) else val
                elif label == "run":
                    branch["run"] = str(val)
            branches.append(branch)
    if branches:
        rule["branches"] = branches


def _resolve_prompt(val: Any, base_dir: str) -> str:
    """Resolve a prompt value: string = inline, bare atom = file."""
    if isinstance(val, str):
        # Try to read as file; if it looks like a path and exists, read it
        full = os.path.join(base_dir, val)
        if os.path.isfile(full):
            with open(full) as f:
                return f.read()
        # Otherwise treat as inline string
        return val
    return str(val)


def _to_str_list(val: Any) -> list[str]:
    """Coerce a value to a list of strings."""
    if isinstance(val, list):
        return [str(v) for v in val]
    return [str(val)]


# ── Public API ───────────────────────────────────────────────────

def from_file(path: str) -> dict[str, Any]:
    """Load a ``.locke`` file and return a flat design dict.

    The returned dict has the same shape as ``from_json()`` output,
    including the ``_source_path`` metadata field.
    """
    from pathlib import Path as P

    p = P(path).resolve()
    with open(p) as f:
        source = f.read()

    base_dir = str(p.parent)
    tokens = tokenize(source)
    ast = parse(tokens)
    design = resolve(ast, base_dir)
    design["_source_path"] = str(p)
    return design


def compile(source: str, base_dir: str = ".") -> Any:
    """Full pipeline: parse -> resolve -> elaborate -> CseValue."""
    from husks.designs.transport import elaborate

    tokens = tokenize(source)
    ast = parse(tokens)
    design = resolve(ast, base_dir)
    return elaborate(design)


def compile_bytes(source: str, base_dir: str = ".") -> bytes:
    """Full pipeline: parse -> resolve -> elaborate -> encode -> bytes."""
    from husks.core import encode

    return encode(compile(source, base_dir))
