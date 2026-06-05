"""L5 locke -- Locke compiler: tokenizer, parser, resolver, validator, executor.

Sits on L0 (kernel) + L2 (seal) + L3 (engine) + stdlib.  Single module
merging _tokenizer.py, _parser.py, _resolver.py, _validation.py, _executor.py,
_compiler.py, _io.py, _show.py, and __init__.py.  Engine/seal imports are
deferred to executor functions so tokenizer/parser/resolver/validator work
with stdlib only.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any, Callable


# ════════════════════════════════════════════════════════════════════
# §1  TOKENIZER
# ════════════════════════════════════════════════════════════════════

class _TT:
    IDENT    = "IDENT"
    BIND     = "BIND"       # :-
    DECL     = "DECL"       # :=
    LBRACKET = "LBRACKET"   # [
    RBRACKET = "RBRACKET"   # ]
    STRING   = "STRING"
    INT      = "INT"
    FLOAT    = "FLOAT"
    BAREWORD = "BAREWORD"
    EOF      = "EOF"


class Token:
    __slots__ = ("type", "value", "line", "col")
    def __init__(self, type: str, value: str, line: int = 0, col: int = 0):
        self.type, self.value, self.line, self.col = type, value, line, col
    def __repr__(self) -> str:
        return f"Token({self.type}, {self.value!r}, L{self.line})"


_RULE_KEYWORDS = frozenset({"oracle", "action", "trial", "commit", "halt", "cond", "let"})
_DECL_KEYWORDS = frozenset({
    "public", "fuel", "site-inputs", "cost-tolerance", "design", "tolerance", "site",
})
_BLOCK_LABELS = frozenset({
    "inputs", "outputs", "free", "exact", "prompt", "tools", "fuel", "run",
    "value", "reason", "predicate", "then", "else",
})


def _is_bareword_char(c: str) -> bool:
    return c.isalnum() or c in "_./-"


def _looks_like_int(w: str) -> bool:
    return w.isdigit()


def _looks_like_float(w: str) -> bool:
    parts = w.split(".")
    return len(parts) == 2 and parts[0].isdigit() and parts[1].isdigit()


def tokenize(source: str) -> list[Token]:
    """Lex source into a flat list of tokens."""
    tokens: list[Token] = []
    i, line, col, n = 0, 1, 1, len(source)
    while i < n:
        c = source[i]
        if c == "\n":
            i += 1; line += 1; col = 1; continue
        if c in " \t\r":
            i += 1; col += 1; continue
        if c == "#":
            while i < n and source[i] != "\n": i += 1
            continue
        if c == ":" and i + 1 < n and source[i + 1] == "=":
            tokens.append(Token(_TT.DECL, ":=", line, col)); i += 2; col += 2; continue
        if c == ":" and i + 1 < n and source[i + 1] == "-":
            tokens.append(Token(_TT.BIND, ":-", line, col)); i += 2; col += 2; continue
        if c == "[":
            tokens.append(Token(_TT.LBRACKET, "[", line, col)); i += 1; col += 1; continue
        if c == "]":
            tokens.append(Token(_TT.RBRACKET, "]", line, col)); i += 1; col += 1; continue
        if c == '"':
            sl, sc = line, col
            if i + 2 < n and source[i+1] == '"' and source[i+2] == '"':
                i += 3; col += 3; buf = []
                while i < n:
                    if source[i] == '"' and i+2 < n and source[i+1] == '"' and source[i+2] == '"':
                        i += 3; col += 3; break
                    if source[i] == "\n": line += 1; col = 0
                    buf.append(source[i]); i += 1; col += 1
                else:
                    raise SyntaxError(f"unterminated triple-quoted string at line {sl}, col {sc}")
                tokens.append(Token(_TT.STRING, "".join(buf), sl, sc)); continue
            i += 1; col += 1; buf = []
            while i < n and source[i] != '"':
                if source[i] == "\n": line += 1; col = 0
                buf.append(source[i]); i += 1; col += 1
            if i >= n:
                raise SyntaxError(f"unterminated string at line {sl}, col {sc}")
            i += 1; col += 1
            tokens.append(Token(_TT.STRING, "".join(buf), sl, sc)); continue
        if c.isdigit() or _is_bareword_char(c):
            sc = col; buf = []
            while i < n and _is_bareword_char(source[i]):
                buf.append(source[i]); i += 1; col += 1
            w = "".join(buf)
            if _looks_like_float(w):
                tokens.append(Token(_TT.FLOAT, w, line, sc))
            elif _looks_like_int(w):
                tokens.append(Token(_TT.INT, w, line, sc))
            else:
                tokens.append(Token(_TT.BAREWORD, w, line, sc))
            continue
        raise SyntaxError(f"unexpected character {c!r} at line {line}, col {col}")
    tokens.append(Token(_TT.EOF, "", line, col))
    return tokens


# ════════════════════════════════════════════════════════════════════
# §2  PARSER
# ════════════════════════════════════════════════════════════════════

class DeclNode:
    """Top-level realization: value := label."""
    __slots__ = ("label", "value")
    def __init__(self, label: str, value: Any):
        self.label, self.value = label, value
    def __repr__(self) -> str:
        return f"DeclNode({self.value!r} := {self.label})"


class RuleNode:
    """Rule definition: name :- kind [block] or name := kind [block]."""
    __slots__ = ("name", "kind", "decls", "children", "refs", "is_target")
    def __init__(self, name: str, kind: str, decls=None, children=None,
                 refs=None, is_target: bool = False):
        self.name, self.kind = name, kind
        self.decls = decls or []
        self.children = children or []
        self.refs = refs or []
        self.is_target = is_target


class LetNode:
    """Let scope: :- let [bindings... body...]."""
    __slots__ = ("items",)
    def __init__(self, items=None):
        self.items = items or []


class BindNode:
    """Plain top-level binding: name :- expr."""
    __slots__ = ("name", "expr")
    def __init__(self, name: str, expr: Any):
        self.name, self.expr = name, expr


class _Parser:
    def __init__(self, tokens: list[Token]):
        self.tokens, self.pos = tokens, 0

    def peek(self) -> Token: return self.tokens[self.pos]
    def peek2(self) -> Token | None:
        return self.tokens[self.pos + 1] if self.pos + 1 < len(self.tokens) else None
    def advance(self) -> Token:
        t = self.tokens[self.pos]; self.pos += 1; return t
    def expect(self, type: str) -> Token:
        t = self.advance()
        if t.type != type:
            raise SyntaxError(f"expected {type}, got {t.type} ({t.value!r}) at line {t.line}, col {t.col}")
        return t
    def at_end(self) -> bool: return self.peek().type == _TT.EOF

    def parse_program(self) -> list:
        nodes = []
        while not self.at_end(): nodes.append(self._parse_top_level())
        return nodes

    def _parse_top_level(self):
        t, t2 = self.peek(), self.peek2()
        if t.type == _TT.BIND and t2 and t2.type == _TT.BAREWORD and t2.value == "let":
            self.advance(); self.advance()
            return self._parse_let_block()
        first = self._parse_lead()
        op = self.peek()
        if op.type == _TT.DECL:
            self.advance()
            return self._parse_decl_rhs(first)
        if op.type == _TT.BIND:
            self.advance()
            return self._parse_bind_rhs(self._lead_to_str(first))
        raise SyntaxError(f"expected := or :-, got {op.type} ({op.value!r}) at line {op.line}, col {op.col}")

    def _parse_lead(self):
        return self._parse_cell() if self.peek().type == _TT.LBRACKET else self._parse_atom()

    def _lead_to_str(self, val) -> str:
        if isinstance(val, (str, int, float)): return str(val)
        raise SyntaxError(f"expected identifier, got {val!r}")

    def _parse_decl_rhs(self, value):
        t = self.advance()
        if t.type != _TT.BAREWORD:
            raise SyntaxError(f"expected label after :=, got {t.type} ({t.value!r}) at line {t.line}, col {t.col}")
        label = t.value
        if label in _DECL_KEYWORDS:
            if label == "site" and self.peek().type == _TT.LBRACKET:
                return DeclNode(label, (value, self._parse_cell()))
            return DeclNode(label, value)
        if label in _RULE_KEYWORDS:
            name = self._lead_to_str(value)
            block = self._parse_block()
            return RuleNode(name, label, *self._unpack_block(block), is_target=True)
        raise SyntaxError(f"unknown label {label!r} after := at line {t.line}, col {t.col}")

    def _parse_bind_rhs(self, name: str):
        t = self.peek()
        if t.type == _TT.BAREWORD and t.value in _RULE_KEYWORDS:
            kind = self.advance().value
            if kind == "let":
                return RuleNode(name, "let", children=[self._parse_let_block()])
            block = self._parse_block()
            return RuleNode(name, kind, *self._unpack_block(block))
        return BindNode(name, self._parse_expr())

    def _parse_block(self) -> list:
        self.expect(_TT.LBRACKET)
        items = []
        while self.peek().type != _TT.RBRACKET: items.append(self._parse_block_item())
        self.expect(_TT.RBRACKET)
        return items

    def _parse_block_item(self):
        t, t2 = self.peek(), self.peek2()
        if t.type == _TT.BIND:
            self.advance(); kw = self.peek()
            if kw.type == _TT.BAREWORD and kw.value == "let":
                self.advance(); return ("let", self._parse_let_block())
            raise SyntaxError(f"expected 'let' after bare :- in block, got {kw.value!r} at line {kw.line}")
        first = self._parse_lead()
        op = self.peek()
        if op.type == _TT.DECL:
            self.advance(); lt = self.advance()
            if lt.type != _TT.BAREWORD:
                raise SyntaxError(f"expected label after :=, got {lt.type} at line {lt.line}")
            return ("decl", lt.value, first)
        if op.type == _TT.BIND:
            self.advance(); name = self._lead_to_str(first); kw = self.peek()
            if kw.type == _TT.BAREWORD and kw.value in _RULE_KEYWORDS:
                kind = self.advance().value
                if kind == "let":
                    return ("rule", RuleNode(name, "let", children=[self._parse_let_block()]))
                d, c, r = self._unpack_block(self._parse_block())
                return ("rule", RuleNode(name, kind, d, c, r))
            raise SyntaxError(f"expected rule keyword after :-, got {kw.value!r} at line {kw.line}")
        if isinstance(first, str) and op.type not in (_TT.DECL, _TT.BIND):
            return ("ref", first)
        raise SyntaxError(f"unexpected block item at line {op.line}, col {op.col}")

    def _parse_let_block(self) -> LetNode:
        self.expect(_TT.LBRACKET); items = []
        while self.peek().type != _TT.RBRACKET:
            item = self._parse_block_item()
            if item[0] in ("rule", "let"): items.append(item[1])
            elif item[0] == "ref": items.append(item[1])
            else: raise SyntaxError(f"unexpected {item[0]} inside let block")
        self.expect(_TT.RBRACKET)
        return LetNode(items)

    def _unpack_block(self, items: list) -> tuple[list, list, list]:
        decls, children, refs = [], [], []
        for item in items:
            if item[0] == "decl": decls.append((item[1], item[2]))
            elif item[0] == "rule": children.append(item[1])
            elif item[0] == "let": children.append(item[1])
            elif item[0] == "ref": refs.append(item[1])
        return decls, children, refs

    def _parse_expr(self):
        return self._parse_cell() if self.peek().type == _TT.LBRACKET else self._parse_atom()

    def _parse_cell(self) -> list:
        self.expect(_TT.LBRACKET); items = []
        while self.peek().type != _TT.RBRACKET: items.append(self._parse_expr())
        self.expect(_TT.RBRACKET)
        return items

    def _parse_atom(self):
        t = self.advance()
        if t.type == _TT.STRING: return t.value
        if t.type == _TT.INT: return int(t.value)
        if t.type == _TT.FLOAT: return float(t.value)
        if t.type == _TT.BAREWORD: return t.value
        raise SyntaxError(f"expected atom, got {t.type} ({t.value!r}) at line {t.line}, col {t.col}")


def parse(tokens: list[Token]) -> list:
    """Parse a token list into a list of AST nodes."""
    return _Parser(tokens).parse_program()


# ════════════════════════════════════════════════════════════════════
# §3  RESOLVER
# ════════════════════════════════════════════════════════════════════

def resolve(ast: list, base_dir: str = ".") -> dict[str, Any]:
    """Resolve AST nodes into a flat design dict."""
    design: dict[str, Any] = {}
    rules: list[dict[str, Any]] = []
    seen_decls: set[str] = set()
    target_name: str | None = None

    for node in ast:
        if isinstance(node, DeclNode):
            if node.label in seen_decls and node.label != "site": continue
            seen_decls.add(node.label)
            if node.label in ("public", "design"):
                design["name"] = node.value
            elif node.label == "fuel":
                design["fuel"] = node.value
            elif node.label == "site-inputs":
                design["site_inputs"] = _cell_to_site_inputs(node.value)
            elif node.label in ("cost-tolerance", "tolerance"):
                design["cost_tolerance"] = {"ratio": node.value}
            elif node.label == "site":
                si = design.get("site_inputs", {})
                if isinstance(node.value, tuple):
                    root, imports = node.value
                    root_str = str(root)
                    if len(imports) == 1:
                        # Single file: LHS = local name, bracket = source path
                        si[root_str] = str(imports[0])
                    else:
                        # Directory prefix: LHS/file for each file
                        for f in imports:
                            si[str(f)] = root_str + "/" + str(f)
                else:
                    # Bare site: file := site (identity mapping)
                    name = str(node.value)
                    si[name] = name
                design["site_inputs"] = si
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

    if target_name: design["target"] = target_name
    if rules: design["rules"] = rules
    return design


def _cell_to_site_inputs(cell: list) -> dict[str, str]:
    if not isinstance(cell, list) or len(cell) % 2 != 0:
        raise ValueError(f"site-inputs must be a cell with even elements, got {cell!r}")
    return {str(cell[i]): str(cell[i+1]) for i in range(0, len(cell), 2)}


def _collect_outputs(node) -> set[str]:
    if not isinstance(node, RuleNode): return set()
    paths: set[str] = set()
    for label, val in node.decls:
        if label in ("outputs", "free", "exact"):
            paths.update(str(v) for v in val) if isinstance(val, list) else paths.add(str(val))
    return paths


def _collect_inputs(node) -> set[str]:
    if not isinstance(node, RuleNode): return set()
    paths: set[str] = set()
    for label, val in node.decls:
        if label == "inputs":
            paths.update(str(v) for v in val) if isinstance(val, list) else paths.add(str(val))
    return paths


def _topo_sort_children(children: list) -> list:
    """Sort siblings so producers come before consumers, conds last."""
    if len(children) <= 1: return children
    output_to_idx: dict[str, int] = {}
    for i, child in enumerate(children):
        for path in _collect_outputs(child): output_to_idx[path] = i
    n = len(children)
    deps: list[set[int]] = [set() for _ in range(n)]
    for i, child in enumerate(children):
        for path in _collect_inputs(child):
            j = output_to_idx.get(path)
            if j is not None and j != i: deps[i].add(j)
        if isinstance(child, RuleNode) and child.kind == "cond":
            for j in range(n):
                if j != i: deps[i].add(j)
    # Kahn's algorithm
    in_deg = [len(d) for d in deps]
    rdeps: list[set[int]] = [set() for _ in range(n)]
    for i in range(n):
        for j in deps[i]: rdeps[j].add(i)
    queue = sorted(i for i in range(n) if in_deg[i] == 0)
    order: list[int] = []
    while queue:
        i = queue.pop(0); order.append(i)
        for k in rdeps[i]:
            in_deg[k] -= 1
            if in_deg[k] == 0: queue.append(k)
        queue.sort()
    return [children[i] for i in order] if len(order) == n else children


def _flatten_rule(node: RuleNode, rules: list[dict], base_dir: str,
                  _seen: set[str] | None = None) -> None:
    """Recursively flatten a RuleNode tree into the flat rules list."""
    if _seen is None: _seen = set()
    if node.name in _seen: return
    _seen.add(node.name)
    to_flat = [c for c in node.children
               if not (node.kind == "trial" and isinstance(c, RuleNode))]
    to_flat = _topo_sort_children(to_flat)
    for child in to_flat:
        if isinstance(child, RuleNode): _flatten_rule(child, rules, base_dir, _seen)
        elif isinstance(child, LetNode): _flatten_let(child, rules, base_dir, _seen)

    child_names = [c.name for c in node.children if isinstance(c, RuleNode)]
    rule: dict[str, Any] = {"name": node.name, "kind": node.kind}
    if child_names: rule["children"] = child_names

    free_list: list[str] = []
    exact_list: list[str] = []
    for label, val in node.decls:
        if label == "inputs": rule["inputs"] = _to_str_list(val)
        elif label == "outputs": rule["outputs"] = _to_str_list(val)
        elif label == "free": free_list = _to_str_list(val)
        elif label == "exact": exact_list = _to_str_list(val)
        elif label == "tools": rule["tools"] = _to_str_list(val)
        elif label == "fuel": rule["fuel"] = int(val) if not isinstance(val, int) else val
        elif label == "prompt": rule["prompt"] = _resolve_prompt(val, base_dir)
        elif label == "run": rule["run"] = str(val)
        elif label == "value": rule["value"] = str(val)
        elif label == "reason": rule["reason"] = str(val)
        else: rule[label] = val

    if free_list or exact_list:
        rule["outputs"] = free_list + exact_list
        if node.kind != "trial":
            equiv = {p: "free" for p in free_list}
            equiv.update({p: "exact" for p in exact_list})
            if equiv: rule["equivalence"] = equiv

    if node.kind == "cond": _resolve_cond(node, rule, base_dir)
    if node.kind == "trial": _resolve_trial(node, rule, base_dir)
    if node.kind == "let" and node.children:
        child = node.children[0]
        if isinstance(child, LetNode) and child.items:
            first = child.items[0]
            rule["bind"] = first.name if isinstance(first, RuleNode) else str(first)
        elif isinstance(child, RuleNode):
            rule["bind"] = child.name
    rules.append(rule)


def _flatten_let(node: LetNode, rules: list[dict], base_dir: str,
                 _seen: set[str] | None = None) -> None:
    if _seen is None: _seen = set()
    for item in node.items:
        if isinstance(item, RuleNode): _flatten_rule(item, rules, base_dir, _seen)
        elif isinstance(item, LetNode): _flatten_let(item, rules, base_dir, _seen)


def _resolve_cond(node: RuleNode, rule: dict, base_dir: str) -> None:
    for label, val in node.decls:
        if label in ("predicate", "then", "else"): rule[label] = str(val)
    if "predicate" not in rule and node.refs: rule["predicate"] = node.refs[0]
    children = [c for c in node.children if isinstance(c, RuleNode)]
    if "then" not in rule and len(children) >= 1: rule["then"] = children[0].name
    if "else" not in rule and len(children) >= 2: rule["else"] = children[1].name


def _resolve_trial(node: RuleNode, rule: dict, base_dir: str) -> None:
    branches = []
    for child in node.children:
        if isinstance(child, RuleNode):
            branch: dict[str, Any] = {"kind": child.kind}
            for label, val in child.decls:
                if label == "prompt": branch["prompt"] = _resolve_prompt(val, base_dir)
                elif label == "tools": branch["tools"] = _to_str_list(val)
                elif label == "fuel": branch["fuel"] = int(val) if not isinstance(val, int) else val
                elif label == "run": branch["run"] = str(val)
            branches.append(branch)
    if branches: rule["branches"] = branches


def _resolve_prompt(val: Any, base_dir: str) -> str:
    if isinstance(val, str):
        full = os.path.join(base_dir, val)
        if os.path.isfile(full):
            with open(full) as f: return f.read()
        return val
    return str(val)


def _to_str_list(val: Any) -> list[str]:
    return [str(v) for v in val] if isinstance(val, list) else [str(val)]


def from_file(path: str) -> dict[str, Any]:
    """Load a .locke file and return a flat design dict."""
    p = Path(path).resolve()
    with open(p) as f: source = f.read()
    tokens = tokenize(source)
    ast = parse(tokens)
    design = resolve(ast, str(p.parent))
    design["_source_path"] = str(p)
    return design


# ════════════════════════════════════════════════════════════════════
# §4  VALIDATION
# ════════════════════════════════════════════════════════════════════

Design = dict[str, Any]

_RULE_KINDS = frozenset({"action", "oracle", "trial", "commit", "halt", "let", "cond"})
_PRODUCING_KINDS = frozenset({"action", "oracle", "trial"})
_BUILTIN_PREFIXES = frozenset({"file-exists", "file-nonempty", "exit-zero"})

_ALLOWED_DESIGN_FIELDS = frozenset({
    "name", "fuel", "rules", "target", "targets", "site_inputs", "site",
    "oracle_backend", "oracle_model", "oracle_config", "imports", "predicates",
    "cost_tolerance", "_source_path",
})

_ALLOWED_RULE_FIELDS = {
    "action": frozenset({"name", "kind", "inputs", "outputs", "run", "action_fn", "equivalence", "children"}),
    "oracle": frozenset({"name", "kind", "inputs", "outputs", "prompt", "tools", "fuel", "equivalence", "children"}),
    "trial": frozenset({"name", "kind", "inputs", "outputs", "branches", "verdict"}),
    "commit": frozenset({"name", "kind", "value"}),
    "halt": frozenset({"name", "kind", "reason"}),
    "let": frozenset({"name", "kind", "bind"}),
    "cond": frozenset({"name", "kind", "predicate", "then", "else"}),
}


def _validate_rule_name(name: str) -> str | None:
    if not name: return "rule name is empty"
    if "/" in name or "\\" in name: return f"rule name contains path separator: {name}"
    if name == ".." or name.startswith(".."): return f"rule name contains '..': {name}"
    for i, c in enumerate(name):
        if ord(c) < 0x20 or ord(c) == 0x7F:
            return f"rule name contains control character at position {i}: {name}"
    if name in {"build.manifest"}: return f"rule name collides with internal file: {name}"
    if name.endswith(".seal") or name.endswith(".trial") or name.endswith(".history"):
        return f"rule name uses reserved extension: {name}"
    return None


def _validate_path(name: str) -> str | None:
    if os.path.isabs(name): return f"path must be relative, got absolute: {name}"
    parts = Path(name).parts
    if ".." in parts: return f"path contains '..': {name}"
    if not parts: return None
    if parts[0] in (".traces", ".husks"): return f"path targets reserved directory: {name}"
    if name.endswith(".husk"): return f"path targets generated .husk file: {name}"
    return None


def _resolve_targets(design: Design) -> list[str] | None:
    if "targets" in design:
        val = design["targets"]
        return [val] if isinstance(val, str) else list(val)
    if "target" in design:
        val = design["target"]
        return list(val) if isinstance(val, list) else [val]
    return None


def check(design: Design, *, unsafe: bool = False) -> list[str]:
    """Validate a design IR.  Returns list of error strings (empty = ok)."""
    errors: list[str] = []
    for field in design:
        if field not in _ALLOWED_DESIGN_FIELDS:
            errors.append(f"unknown design field: '{field}'")
    if not design.get("name"): errors.append("design has no name")
    fuel = design.get("fuel")
    if fuel is None or fuel <= 0: errors.append("design has no fuel budget")

    cost_tol = design.get("cost_tolerance")
    if cost_tol is not None:
        if not isinstance(cost_tol, dict):
            errors.append("cost_tolerance must be a dict")
        else:
            ratio = cost_tol.get("ratio")
            if ratio is None: errors.append("cost_tolerance must have 'ratio' field")
            elif not isinstance(ratio, list) or len(ratio) != 2:
                errors.append("cost_tolerance.ratio must be a two-element list [min, max]")
            elif not all(isinstance(x, (int, float)) and x > 0 for x in ratio):
                errors.append("cost_tolerance.ratio bounds must be positive numbers")
            elif ratio[0] > ratio[1]:
                errors.append("cost_tolerance.ratio minimum must be <= maximum")

    rules = design.get("rules", [])
    if not rules: errors.append("design has no rules"); return errors

    names: set[str] = set()
    si = design.get("site_inputs", [])
    produced: set[str] = set(si.keys()) if isinstance(si, dict) else {
        Path(p).name if Path(p).is_absolute() else p for p in si}
    import_prefixes = [k + "/" for k in design.get("imports", {}) if isinstance(design.get("imports"), dict)]
    predicates = design.get("predicates", {})
    output_producers: dict[str, str] = {}
    all_outputs: set[str] = set()
    rule_inputs: dict[str, list[str]] = {}
    rule_outputs_map: dict[str, list[str]] = {}

    for r in rules:
        tag = r.get("name", f"rule[?]")
        kind = r.get("kind", "")
        if kind in _PRODUCING_KINDS:
            outputs = r.get("outputs", [])
            rule_outputs_map[tag] = outputs
            for o in outputs: all_outputs.add(o)

    for i, r in enumerate(rules):
        tag = r.get("name", f"rule[{i}]")
        if not r.get("name"): errors.append(f"{tag}: missing name")
        else:
            name_err = _validate_rule_name(r["name"])
            if name_err: errors.append(f"{tag}: {name_err}")
            elif r["name"] in names: errors.append(f"{tag}: duplicate name")
        names.add(r.get("name", ""))

        kind = r.get("kind", "")
        if kind not in _RULE_KINDS:
            errors.append(f"{tag}: kind must be one of {sorted(_RULE_KINDS)}, got '{kind}'"); continue

        allowed_fields = _ALLOWED_RULE_FIELDS.get(kind)
        if allowed_fields:
            for field in r:
                if field not in allowed_fields:
                    errors.append(f"{tag}: unknown field '{field}' for {kind} rule")

        if kind in _PRODUCING_KINDS:
            outputs = r.get("outputs", [])
            if not outputs: errors.append(f"{tag}: no declared outputs")
            for o in outputs:
                pe = _validate_path(o)
                if pe: errors.append(f"{tag}: output {pe}")
                if import_prefixes and any(o == pfx.rstrip("/") or o.startswith(pfx) for pfx in import_prefixes):
                    errors.append(f"{tag}: output '{o}' is under an import prefix (imported paths are read-only)")
                if o in produced:
                    fp = output_producers.get(o, "unknown")
                    errors.append(f"{tag}: output '{o}' already produced by rule '{fp}'")
                else:
                    produced.add(o); output_producers[o] = tag
            equiv = r.get("equivalence", {})
            if equiv:
                if not isinstance(equiv, dict): errors.append(f"{tag}: equivalence must be a dict")
                else:
                    for path, rel in equiv.items():
                        if path not in outputs: errors.append(f"{tag}: equivalence key '{path}' not in declared outputs")
                        if rel not in ("exact", "free"): errors.append(f"{tag}: equivalence value must be 'exact' or 'free', got '{rel}'")
            inputs = r.get("inputs", [])
            rule_inputs[tag] = inputs
            for inp in inputs:
                pe = _validate_path(inp)
                if pe: errors.append(f"{tag}: input {pe}")
                if inp not in produced:
                    is_imported = any(inp.startswith(pfx) for pfx in import_prefixes)
                    if not is_imported:
                        if inp in all_outputs:
                            errors.append(f"{tag}: input '{inp}' is a forward reference (produced by a later rule)")
                        else:
                            errors.append(f"{tag}: input '{inp}' not produced by any rule")

        if kind == "oracle":
            if r.get("fuel", 0) <= 0: errors.append(f"{tag}: oracle rule has no fuel")
            if not r.get("prompt"): errors.append(f"{tag}: oracle rule has no prompt")
        elif kind == "trial":
            if not r.get("branches"): errors.append(f"{tag}: trial has no branches")
            verdict = r.get("verdict")
            if verdict is not None and not callable(verdict) and not isinstance(verdict, str):
                errors.append(f"{tag}: verdict must be a callable or a policy name string")
        elif kind == "commit":
            if "value" not in r: errors.append(f"{tag}: commit has no value")
        elif kind == "halt":
            if "reason" not in r: errors.append(f"{tag}: halt has no reason")
        elif kind == "let":
            if not r.get("bind"): errors.append(f"{tag}: let has no bind target")
            elif r["bind"] not in names: errors.append(f"{tag}: let bind target '{r['bind']}' not defined yet")
        elif kind == "cond":
            for fld, msg in [("predicate", "cond has no predicate"), ("then", "cond has no 'then' branch"), ("else", "cond has no 'else' branch")]:
                if not r.get(fld): errors.append(f"{tag}: {msg}")
            for fld, label in [("then", "'then' target"), ("else", "'else' target")]:
                val = r.get(fld)
                if val and val not in names: errors.append(f"{tag}: cond {label} '{val}' not defined yet")
            pred_name = r.get("predicate")
            if pred_name and not callable(pred_name) and pred_name not in predicates:
                if ":" in pred_name:
                    prefix = pred_name.split(":", 1)[0]
                    if prefix not in _BUILTIN_PREFIXES:
                        errors.append(f"{tag}: unknown built-in predicate prefix '{prefix}'")
                else:
                    errors.append(f"{tag}: predicate '{pred_name}' not in design predicates")

    # Circular dependency detection
    def _detect_cycle(node, visited, rec_stack, path):
        visited.add(node); rec_stack.add(node); path.append(node)
        for inp in rule_inputs.get(node, []):
            producer = output_producers.get(inp)
            if producer and producer in rule_outputs_map:
                if producer not in visited:
                    cycle = _detect_cycle(producer, visited, rec_stack, path)
                    if cycle: return cycle
                elif producer in rec_stack:
                    return path[path.index(producer):] + [producer]
        path.pop(); rec_stack.remove(node)
        return None

    visited: set[str] = set()
    for rn in rule_inputs:
        if rn not in visited:
            cycle = _detect_cycle(rn, visited, set(), [])
            if cycle:
                errors.append(f"circular dependency detected: {' -> '.join(cycle)}"); break

    imports = design.get("imports")
    if imports is not None:
        if not isinstance(imports, dict):
            errors.append("imports must be a dict mapping local names to absolute paths")
        else:
            rule_outputs = {o for r in rules for o in r.get("outputs", [])}
            for local_name, ext_path in imports.items():
                le = _validate_path(local_name)
                if le: errors.append(f"import '{local_name}': local name {le}")
                if not isinstance(ext_path, str):
                    errors.append(f"import '{local_name}': value must be a string path")
                elif not os.path.isabs(ext_path):
                    errors.append(f"import '{local_name}': path must be absolute, got '{ext_path}'")
                if local_name in rule_outputs:
                    errors.append(f"import '{local_name}' collides with a rule output name")

    rules_by_name: dict[str, dict] = {r["name"]: r for r in rules if r.get("name")}

    targets = _resolve_targets(design)
    if targets is None: errors.append("design has no target (must provide 'target' or 'targets')")
    elif len(targets) == 0: errors.append("'targets' list is empty")
    else:
        for t in targets:
            if t not in names:
                errors.append(f"target '{t}' does not match any rule name")
            else:
                target_rule = rules_by_name[t]
                if target_rule.get("kind") == "oracle" and not unsafe:
                    errors.append(
                        f"target '{t}' is an oracle — root must be an action "
                        f"(use --unsafe to override)")
    return errors


def check_categorized(design: Design) -> dict[str, Any]:
    """Validate a design and return errors grouped by category."""
    all_errors = check(design)
    cats = {k: {"ok": True, "errors": []} for k in
            ("syntax", "names", "paths", "inputs", "outputs", "fuel", "targets", "imports", "other")}
    for err in all_errors:
        el = err.lower()
        if "name" in el or "duplicate" in el: cat = "names"
        elif "path" in el or "absolute" in el or "'..'" in el: cat = "paths"
        elif "input" in el and "not produced" in el: cat = "inputs"
        elif "output" in el and ("produced" in el or "no declared" in el): cat = "outputs"
        elif "fuel" in el: cat = "fuel"
        elif "target" in el: cat = "targets"
        elif "import" in el: cat = "imports"
        elif "kind" in el or "no rules" in el or "has no" in el: cat = "syntax"
        else: cat = "other"
        cats[cat]["errors"].append(err); cats[cat]["ok"] = False
    return {"ok": len(all_errors) == 0, "categories": cats, "errors": all_errors}


# ════════════════════════════════════════════════════════════════════
# §5  SHOW
# ════════════════════════════════════════════════════════════════════

_KIND_MARKERS = {
    "oracle": "\u25b8", "action": "\u25cf", "trial": "\u25e6",
    "commit": "\u2713", "halt": "\u2717", "let": "\u2192", "cond": "?",
}


def show(design: Design) -> str:
    """Return a human-readable summary of the design."""
    name = design.get("name", "?")
    fuel = design.get("fuel", "?")
    targets = _resolve_targets(design) or ["?"]
    rules = design.get("rules", [])
    si = design.get("site_inputs", [])
    target_set = set(targets)
    lines = [f"\n  design: {name}  (fuel {fuel})  targets: {', '.join(targets)}",
             f"  {'─' * 50}"]
    if si:
        si_names = list(si.keys()) if isinstance(si, dict) else [Path(p).name for p in si]
        lines.append(f"  site inputs: {', '.join(si_names)}"); lines.append("")
    for r in rules:
        kind = r.get("kind", "?")
        rname = r.get("name", "?")
        marker = _KIND_MARKERS.get(kind, "?")
        tag = "  \u25c0 target" if rname in target_set else ""
        if kind == "oracle": lines.append(f"  {marker} {rname}  ({kind}  fuel {r.get('fuel', '?')}){tag}")
        elif kind == "trial": lines.append(f"  {marker} {rname}  ({kind}  {len(r.get('branches', []))} branches){tag}")
        elif kind == "commit": lines.append(f"  {marker} {rname}  (commit: {r.get('value', '?')}){tag}")
        elif kind == "halt": lines.append(f"  {marker} {rname}  (halt: {r.get('reason', '?')}){tag}")
        elif kind == "let": lines.append(f"  {marker} {rname}  (let -> {r.get('bind', '?')}){tag}")
        elif kind == "cond": lines.append(f"  {marker} {rname}  (cond: {r.get('predicate', '?')}  then={r.get('then', '?')}  else={r.get('else', '?')}){tag}")
        else: lines.append(f"  {marker} {rname}  ({kind}){tag}")
        inputs, outputs = r.get("inputs", []), r.get("outputs", [])
        if inputs: lines.append(f"    in:  {', '.join(inputs)}")
        if outputs: lines.append(f"    out: {', '.join(outputs)}")
        if kind == "action" and r.get("run"): lines.append(f"    run: {r['run']}")
    lines.append(f"  {'─' * 50}\n")
    return "\n".join(lines)


# ════════════════════════════════════════════════════════════════════
# §6  I/O
# ════════════════════════════════════════════════════════════════════

def from_json(path: str | Path) -> Design:
    """Load a design from a JSON file."""
    with open(path) as f: design = json.load(f)
    design["_source_path"] = str(Path(path).resolve())
    return design


def from_locke(path: str | Path) -> Design:
    """Load a design from a .locke file."""
    return from_file(str(path))


def normalize_site_inputs(site_inputs: list[str] | dict[str, str] | None,
                          design_source_path: str | None = None) -> dict[str, str]:
    """Normalize site_inputs to dict of local_name -> resolved_path."""
    if site_inputs is None: return {}
    design_dir = Path(design_source_path).parent.resolve() if design_source_path else None
    result = {}
    if isinstance(site_inputs, list):
        for entry in site_inputs:
            p = Path(entry)
            if p.is_absolute():
                local_name, resolved = p.name, p.resolve()
            else:
                if design_dir is None:
                    raise ValueError(f"Relative site_input '{entry}' requires design source path")
                local_name, resolved = entry, (design_dir / entry).resolve()
            if not resolved.exists():
                raise ValueError(f"Declared site_input does not exist: {entry}\n  Resolved path: {resolved}")
            result[local_name] = str(resolved)
    elif isinstance(site_inputs, dict):
        for local_name, source_path in site_inputs.items():
            p = Path(source_path)
            if p.is_absolute(): resolved = p.resolve()
            else:
                if design_dir is None:
                    raise ValueError(f"Relative site_input source '{source_path}' requires design source path")
                resolved = (design_dir / source_path).resolve()
            if not resolved.exists():
                raise ValueError(f"Declared site_input does not exist: {source_path}\n  Resolved path: {resolved}")
            result[local_name] = str(resolved)
    return result


def to_json(design: Design, path: str | Path | None = None) -> str:
    """Serialize a design to JSON.  If path given, write to file."""
    s = json.dumps(design, indent=2)
    if path:
        with open(path, "w") as f: f.write(s)
    return s


# ════════════════════════════════════════════════════════════════════
# §7  EXECUTOR  (deferred L2/L3 imports)
# ════════════════════════════════════════════════════════════════════

def _resolve_predicate(spec: str | Callable,
                       predicates: dict[str, Callable]) -> Callable[[dict], bool]:
    """Turn a predicate spec into a callable (Store) -> bool."""
    if callable(spec): return spec
    if spec in predicates: return predicates[spec]
    if ":" in spec:
        prefix, arg = spec.split(":", 1)
        if prefix == "file-exists":
            def _fe(S):
                from husks.seal import site_path
                return os.path.exists(site_path(S, arg))
            _fe._husks_pred_spec = spec; return _fe
        if prefix == "file-nonempty":
            def _fne(S):
                from husks.seal import site_path
                p = site_path(S, arg)
                return os.path.exists(p) and os.path.getsize(p) > 0
            _fne._husks_pred_spec = spec; return _fne
        if prefix == "exit-zero":
            def _ez(S):
                r = subprocess.run(arg, shell=True, cwd=S["site"], capture_output=True, timeout=120)
                return r.returncode == 0
            _ez._husks_pred_spec = spec; return _ez
    raise ValueError(f"unknown predicate: {spec!r}")


def _make_touch_action(outputs: list[str]):
    """Create an action that writes "ok\n" to declared outputs that don't exist."""
    def touch(S):
        from husks.seal import site_path, write_text
        for o in outputs:
            p = Path(site_path(S, o, write=True))
            if not p.exists():
                p.parent.mkdir(parents=True, exist_ok=True)
                write_text(site_path(S, o, write=True), "ok\n")
    touch._husks_cmd = "__touch__"
    return touch


def compile_design(design: Design) -> tuple[str, int, list[dict], dict[str, Any]]:
    """Lower design IR to (name, fuel, terminal_nodes, kwargs) for build()."""
    from husks.engine import (
        rule, action, oracle, trial as trial_recipe,
        cond as cond_node, commit as commit_node, halt as halt_node,
        _make_shell_action,
    )

    rules = design.get("rules", [])
    targets = _resolve_targets(design) or ([rules[-1]["name"]] if rules else [])
    predicates: dict[str, Callable] = design.get("predicates", {})
    name_to_node: dict[str, dict] = {}

    for r in rules:
        rname, kind = r["name"], r["kind"]

        if kind == "let":
            name_to_node[rname] = name_to_node[r["bind"]]; continue
        if kind == "commit":
            name_to_node[rname] = commit_node(r.get("value", "ok")); continue
        if kind == "halt":
            name_to_node[rname] = halt_node(r.get("reason", "halted")); continue
        if kind == "cond":
            pred_fn = _resolve_predicate(r["predicate"], predicates)
            name_to_node[rname] = cond_node(pred_fn, name_to_node[r["then"]], name_to_node[r["else"]]); continue

        # Producing kinds: action, oracle, trial
        inputs, outputs = r.get("inputs", []), r.get("outputs", [])
        children = []
        for inp in inputs:
            for pn, pnode in name_to_node.items():
                if inp in pnode.get("outputs", []) and pnode not in children:
                    children.append(pnode)

        if kind == "action":
            run_cmd = r.get("run")
            if run_cmd: recipe = action(_make_shell_action(run_cmd, outputs))
            elif r.get("action_fn") and callable(r["action_fn"]): recipe = action(r["action_fn"])
            else: recipe = action(_make_touch_action(outputs))
        elif kind == "oracle":
            recipe = oracle(prompt=r.get("prompt", ""),
                            tools=r.get("tools", ["read-file", "write-file", "list-dir", "tree"]),
                            fuel=r.get("fuel", 8))
        elif kind == "trial":
            compiled_branches = []
            for b in r.get("branches", []):
                bk = b.get("type", b.get("kind", "oracle"))
                if bk == "oracle":
                    compiled_branches.append({"type": "oracle", "name": b.get("name"),
                        "prompt": b.get("prompt", ""),
                        "tools": b.get("tools", ["read-file", "write-file", "list-dir", "tree"]),
                        "fuel": b.get("fuel", 8)})
                elif bk == "action":
                    compiled_branches.append({"type": "action", "fn": b.get("action_fn") or _make_touch_action(outputs)})
                else:
                    compiled_branches.append(b)
            recipe = trial_recipe(*compiled_branches, verdict=r.get("verdict"))
        else:
            raise ValueError(f"unknown producing kind: {kind!r}")

        name_to_node[rname] = rule(rname, *children, inputs=inputs, outputs=outputs, recipe=recipe)

    terminals = [name_to_node[t] for t in targets]
    kwargs: dict[str, Any] = {}
    for k, dk in [("site", "site"), ("oracle_backend", "oracle_backend"),
                  ("oracle_model", "oracle_model"), ("oracle_config", "oracle_config"),
                  ("site_inputs", "site_inputs")]:
        if design.get(dk): kwargs[k] = design[dk]
    return design["name"], design["fuel"], terminals, kwargs


def setup_imports(site: str, imports: dict[str, str]) -> list[str]:
    """Create symlinks in the site for each declared import."""
    from husks.seal import setup_links
    return setup_links(site, imports)


def run(design: Design, **overrides: Any) -> dict[str, Any]:
    """Check, compile, and execute a design.  Returns the Store."""
    unsafe = overrides.pop("unsafe", False)
    errs = check(design, unsafe=unsafe)
    if errs: raise ValueError("design check failed:\n  " + "\n  ".join(errs))
    from husks.engine import build

    name, fuel, terminals, kwargs = compile_design(design)
    kwargs.update(overrides)
    if design.get("_source_path"):
        kwargs["design_source"] = design["_source_path"]
        kwargs["design_kind"] = "locke" if design["_source_path"].endswith(".locke") else "json"
    if "site_inputs" in kwargs and design.get("_source_path"):
        kwargs["site_inputs"] = normalize_site_inputs(kwargs["site_inputs"], design["_source_path"])
    imports = design.get("imports")
    site = kwargs.get("site")
    if imports and site:
        kwargs["readonly_dirs"] = setup_imports(site, imports)
    kwargs["design"] = design
    return build(name, fuel, *terminals, **kwargs)
