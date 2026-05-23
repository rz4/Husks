"""
transport.py — Canonical JSON ↔ CSE AST bijection + flat-plan elaboration.

Provides a lossless, bijective mapping between CSE parse trees
(bytes/lists as produced by core.parse) and canonical JSON dicts.
Round-tripping through JSON and back reproduces the original CSE
bytes exactly.

Also provides elaborate() to deterministically convert a flat rule-list
plan into a CSE AST. Flat-plan is an input-only dialect — it is lossy
upward (cannot reconstruct which sharing was intended vs. inferred).
"""

import json
from typing import Protocol, runtime_checkable

from husks.core import encode, parse, NIL


# ── AST → JSON ────────────────────────────────────────────────────

def _atom_to_json(atom):
    """Convert a CSE atom (bytes) to its JSON representation."""
    if atom == NIL:
        return None
    return atom.decode("utf-8")


def _atom_list_to_json(lst):
    """Convert a CSE list of atoms to a JSON list of strings."""
    return [_atom_to_json(a) for a in lst]


def ast_to_json(cse_value):
    """Convert a parsed CSE tree (bytes/lists) to a canonical JSON dict."""
    if isinstance(cse_value, bytes):
        return _atom_to_json(cse_value)

    tag = cse_value[0]

    if tag == b"husk":
        return {
            "form": "husk",
            "version": _atom_to_json(cse_value[1]),
            "build": ast_to_json(cse_value[2]),
        }

    if tag == b"build":
        return {
            "form": "build",
            "name": _atom_to_json(cse_value[1]),
            "fuel": _atom_to_json(cse_value[2]),
            "target": ast_to_json(cse_value[3]),
        }

    if tag == b"rule":
        return {
            "form": "rule",
            "name": _atom_to_json(cse_value[1]),
            "recipe": ast_to_json(cse_value[2]),
            "inputs": _atom_list_to_json(cse_value[3]),
            "outputs": _atom_list_to_json(cse_value[4]),
            "children": [ast_to_json(c) for c in cse_value[5:]],
        }

    if tag == b"action":
        return {"form": "action"}

    if tag == b"oracle":
        return {
            "form": "oracle",
            "name": _atom_to_json(cse_value[1]),
            "prompt": _atom_to_json(cse_value[2]),
            "tools": _atom_list_to_json(cse_value[3]),
            "fuel": _atom_to_json(cse_value[4]),
        }

    if tag == b"trial":
        return {
            "form": "trial",
            "branches": [ast_to_json(b) for b in cse_value[1:]],
        }

    raise ValueError(f"Unknown CSE form tag: {tag!r}")


# ── JSON → AST ────────────────────────────────────────────────────

def _json_to_atom(value):
    """Convert a JSON value (string or null) back to a CSE atom."""
    if value is None:
        return NIL
    return value.encode("utf-8")


def _json_to_atom_list(lst):
    """Convert a JSON list of strings back to a CSE list of atoms."""
    return [_json_to_atom(s) for s in lst]


def json_to_ast(json_value):
    """Convert a canonical JSON dict back to a CSE tree (bytes/lists)."""
    if not isinstance(json_value, dict):
        return _json_to_atom(json_value)

    form = json_value["form"]

    if form == "husk":
        return [
            b"husk",
            _json_to_atom(json_value["version"]),
            json_to_ast(json_value["build"]),
        ]

    if form == "build":
        return [
            b"build",
            _json_to_atom(json_value["name"]),
            _json_to_atom(json_value["fuel"]),
            json_to_ast(json_value["target"]),
        ]

    if form == "rule":
        result = [
            b"rule",
            _json_to_atom(json_value["name"]),
            json_to_ast(json_value["recipe"]),
            _json_to_atom_list(json_value["inputs"]),
            _json_to_atom_list(json_value["outputs"]),
        ]
        for child in json_value["children"]:
            result.append(json_to_ast(child))
        return result

    if form == "action":
        return [b"action"]

    if form == "oracle":
        return [
            b"oracle",
            _json_to_atom(json_value["name"]),
            _json_to_atom(json_value["prompt"]),
            _json_to_atom_list(json_value["tools"]),
            _json_to_atom(json_value["fuel"]),
        ]

    if form == "trial":
        return [b"trial"] + [json_to_ast(b) for b in json_value["branches"]]

    raise ValueError(f"Unknown JSON form: {form!r}")


# ── Convenience ───────────────────────────────────────────────────

def to_json_str(cse_value):
    """Convert a CSE parse tree to a pretty-printed JSON string."""
    return json.dumps(ast_to_json(cse_value), indent=2)


def from_json_str(json_str):
    """Parse a JSON string back to a CSE tree (bytes/lists)."""
    return json_to_ast(json.loads(json_str))


def round_trip(cse_bytes):
    """Full round-trip: parse → JSON → AST → encode. Returns CSE bytes."""
    tree = parse(cse_bytes)
    j = ast_to_json(tree)
    tree2 = json_to_ast(j)
    return encode(tree2)


# ── OracleBackend protocol ────────────────────────────────────────
#
# The instrumentation boundary. Everything above this line (core,
# transport) is permanent and dependency-free. Everything below
# (engine, instrument) is volatile and replaceable.
#
# The backend receives only the canonical recipe form and input
# file contents, and returns output file contents plus a provenance
# blob. It is keyed entirely by content — model name, token counts,
# cost, wall time, and backend identity do not cross this boundary.

@runtime_checkable
class OracleBackend(Protocol):
    """Content-keyed oracle interface at the instrumentation boundary.

    The backend receives a CSE recipe form and input file contents,
    and returns output file contents plus non-authoritative provenance.
    Nothing about the backend's identity participates in the seal.

    Args:
        recipe_form: CSE recipe form, e.g.
            [b"oracle", name, prompt, [tools...], fuel]
        inputs: {filename: file_bytes} — content of declared input files.
            Files marked absent map to None.

    Returns:
        (outputs, provenance) where:
            outputs: {filename: output_bytes} — produced output files
            provenance: dict with advisory metadata (model, tokens,
                cost, elapsed, etc.) — never part of verification
    """

    def __call__(
        self,
        recipe_form: list,
        inputs: dict[str, bytes | None],
    ) -> tuple[dict[str, bytes], dict]:
        ...


# ── Flat-plan elaboration ─────────────────────────────────────────
#
# A flat plan is the ergonomic input format: a linear list of rules
# with implicit dependencies resolved by output→input edges. The
# elaborator converts this deterministically into a CSE AST tree.
#
# Flat-plan is INPUT-ONLY and LOSSY UPWARD: you cannot reconstruct
# the original flat ordering or distinguish intended sharing from
# inferred sharing. The canonical form is the CSE tree, not the
# flat plan that produced it.

def _elaborate_recipe(rule_dict):
    """Convert a flat-plan rule's recipe fields to a CSE recipe form."""
    kind = rule_dict["kind"]

    if kind == "action":
        return [b"action"]

    if kind == "oracle":
        name = rule_dict.get("oracle_name")
        return [
            b"oracle",
            name.encode("utf-8") if name else NIL,
            rule_dict.get("prompt", "").encode("utf-8"),
            [t.encode("utf-8") for t in rule_dict.get("tools", [])],
            str(rule_dict.get("fuel", 8)).encode("utf-8"),
        ]

    if kind == "trial":
        branches = [_elaborate_recipe(b) for b in rule_dict.get("branches", [])]
        return [b"trial"] + branches

    raise ValueError(f"Unknown recipe kind: {kind!r}")


def elaborate(flat_plan):
    """Convert a flat plan dict to a CSE AST (bytes/lists).

    The flat plan format:
        {
          "name": "build-name",
          "fuel": 10,
          "target": "terminal-rule-name",
          "site_inputs": ["pre-existing.txt"],
          "rules": [
            {"name": "r1", "kind": "action",
             "inputs": ["pre-existing.txt"], "outputs": ["a.txt"]},
            {"name": "r2", "kind": "oracle", "inputs": ["a.txt"],
             "outputs": ["b.txt"], "prompt": "...", "tools": [...], "fuel": 5},
          ]
        }

    Returns a CSE tree: [b"husk", b"1", [b"build", ...]] ready for
    encode() to produce canonical CSE bytes.

    Children are ordered by first reference scanning the parent's
    input list left-to-right (CSE-v1.md §7). Shared producers appear
    as duplicated subtrees (CSE v1 has no let-binding).

    This function is deterministic: the same dependency graph always
    produces the same CSE tree regardless of rule ordering in the
    flat list.
    """
    rules = flat_plan["rules"]
    target_name = flat_plan.get("target", rules[-1]["name"])

    # Build output→producer-name mapping
    producer = {}
    for r in rules:
        for o in r.get("outputs", []):
            producer[o] = r["name"]

    by_name = {r["name"]: r for r in rules}

    def elaborate_rule(rule_name):
        r = by_name[rule_name]
        recipe = _elaborate_recipe(r)
        inputs = [inp.encode("utf-8") for inp in r.get("inputs", [])]
        outputs = [o.encode("utf-8") for o in r.get("outputs", [])]

        # Find children: rules that produce our inputs.
        # Order by first reference in input list (CSE-v1.md §7).
        seen = set()
        children = []
        for inp in r.get("inputs", []):
            if inp in producer:
                child_name = producer[inp]
                if child_name not in seen:
                    seen.add(child_name)
                    children.append(elaborate_rule(child_name))

        result = [b"rule", rule_name.encode("utf-8"), recipe, inputs, outputs]
        result.extend(children)
        return result

    target_rule = elaborate_rule(target_name)
    return [
        b"husk", b"1",
        [
            b"build",
            flat_plan["name"].encode("utf-8"),
            str(flat_plan["fuel"]).encode("utf-8"),
            target_rule,
        ],
    ]
