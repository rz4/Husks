"""
_resolver.py -- AST resolution and flattening.

Converts parsed AST nodes into flat design dict format.
"""

from __future__ import annotations

import os
from typing import Any

from ._parser import DeclNode, RuleNode, LetNode, BindNode


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

            if node.label in ("public", "design"):
                design["name"] = node.value
            elif node.label == "fuel":
                design["fuel"] = node.value
            elif node.label == "site-inputs":
                design["site_inputs"] = _cell_to_site_inputs(node.value)
            elif node.label in ("cost-tolerance", "tolerance"):
                design["cost_tolerance"] = {"ratio": node.value}
            elif node.label == "site":
                # site form: (root_path, [import1, import2, ...])
                root, imports = node.value
                root_str = str(root)
                design["site"] = root_str
                design["site_inputs"] = {
                    str(f): root_str + str(f) for f in imports
                }

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

    # Record child rule names (preserves syntactic nesting from .locke)
    child_names = [c.name for c in node.children if isinstance(c, RuleNode)]

    # Build the rule dict
    rule: dict[str, Any] = {"name": node.name, "kind": node.kind}
    if child_names:
        rule["children"] = child_names

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
    from ._tokenizer import tokenize
    from ._parser import parse

    p = P(path).resolve()
    with open(p) as f:
        source = f.read()

    base_dir = str(p.parent)
    tokens = tokenize(source)
    ast = parse(tokens)
    design = resolve(ast, base_dir)
    design["_source_path"] = str(p)
    return design
