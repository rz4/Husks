"""
transport.py -- Bijective CSE <-> JSON mapping and flat-design elaboration.

Lossless round-trip between CSE byte trees and JSON dicts, plus
deterministic elaboration of flat rule lists into CSE AST trees.
Also defines the OracleBackend typing Protocol.

See docs/architecture.md for CSE form tags, the OracleBackend
protocol, and elaboration semantics.
"""

from __future__ import annotations

import json
from typing import Any, Protocol, runtime_checkable

from husks.core import CseValue, NIL, encode, parse


# ── AST -> JSON ───────────────────────────────────────────────────

def _atom_to_json(a: bytes) -> str | None:
    """Convert a CSE atom to its JSON representation.

    NIL (empty bytes) becomes None; all other atoms are decoded as
    UTF-8 strings.
    """
    if a == NIL:
        return None
    return a.decode("utf-8")


def _atom_list_to_json(lst: list[bytes]) -> list[str | None]:
    """Convert a CSE list of atoms to a JSON list of strings."""
    return [_atom_to_json(a) for a in lst]


def ast_to_json(cse_value: CseValue) -> Any:
    """Convert a parsed CSE tree to a canonical JSON-serializable dict.

    Atoms become strings (or None for NIL).  Tagged lists become dicts
    with a ``"form"`` key.  Raises ValueError on unrecognized tags.
    """
    if isinstance(cse_value, bytes):
        return _atom_to_json(cse_value)

    tag: bytes = cse_value[0]

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
            "targets": [ast_to_json(t) for t in cse_value[3:]],
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

    if tag == b"commit":
        return {
            "form": "commit",
            "value": _atom_to_json(cse_value[1]),
        }

    if tag == b"halt":
        return {
            "form": "halt",
            "reason": _atom_to_json(cse_value[1]),
        }

    if tag == b"cond":
        return {
            "form": "cond",
            "predicate": _atom_to_json(cse_value[1]),
            "then": ast_to_json(cse_value[2]),
            "else": ast_to_json(cse_value[3]),
        }

    if tag == b"let":
        return {
            "form": "let",
            "name": _atom_to_json(cse_value[1]),
            "bound": ast_to_json(cse_value[2]),
        }

    raise ValueError(f"Unknown CSE form tag: {tag!r}")


# ── JSON -> AST ───────────────────────────────────────────────────

def _json_to_atom(value: str | None) -> bytes:
    """Convert a JSON value (string or null) back to a CSE atom."""
    if value is None:
        return NIL
    return value.encode("utf-8")


def _json_to_atom_list(lst: list[str | None]) -> list[bytes]:
    """Convert a JSON list of strings back to a CSE list of atoms."""
    return [_json_to_atom(s) for s in lst]


def json_to_ast(json_value: Any) -> CseValue:
    """Convert a canonical JSON dict back to a CSE tree.

    The inverse of ast_to_json().  Raises ValueError on unrecognized
    form tags or KeyError on missing required fields.
    """
    if not isinstance(json_value, dict):
        return _json_to_atom(json_value)

    form: str = json_value["form"]

    if form == "husk":
        return [
            b"husk",
            _json_to_atom(json_value["version"]),
            json_to_ast(json_value["build"]),
        ]

    if form == "build":
        targets = json_value.get("targets", [])
        # Backward compat: accept legacy single "target" key
        if not targets and "target" in json_value:
            targets = [json_value["target"]]
        return [
            b"build",
            _json_to_atom(json_value["name"]),
            _json_to_atom(json_value["fuel"]),
        ] + [json_to_ast(t) for t in targets]

    if form == "rule":
        result: list[CseValue] = [
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

    if form == "commit":
        return [b"commit", _json_to_atom(json_value["value"])]

    if form == "halt":
        return [b"halt", _json_to_atom(json_value["reason"])]

    if form == "cond":
        return [
            b"cond",
            _json_to_atom(json_value["predicate"]),
            json_to_ast(json_value["then"]),
            json_to_ast(json_value["else"]),
        ]

    if form == "let":
        return [
            b"let",
            _json_to_atom(json_value["name"]),
            json_to_ast(json_value["bound"]),
        ]

    raise ValueError(f"Unknown JSON form: {form!r}")


# ── Convenience ───────────────────────────────────────────────────

def to_json_str(cse_value: CseValue) -> str:
    """Convert a CSE parse tree to a pretty-printed JSON string."""
    return json.dumps(ast_to_json(cse_value), indent=2)


def from_json_str(json_str: str) -> CseValue:
    """Parse a JSON string back to a CSE tree."""
    return json_to_ast(json.loads(json_str))


def round_trip(cse_bytes: bytes) -> bytes:
    """Full round-trip: parse -> JSON -> AST -> encode.

    Returns CSE wire bytes.  The output must be identical to the input
    for any well-formed CSE value -- this is the bijection invariant.
    """
    tree = parse(cse_bytes)
    j = ast_to_json(tree)
    tree2 = json_to_ast(j)
    return encode(tree2)


# ── OracleBackend protocol ────────────────────────────────────────

@runtime_checkable
class OracleBackend(Protocol):
    """Content-keyed oracle interface at the instrumentation boundary.

    The backend receives a CSE recipe form and input file contents,
    and returns output file contents plus non-authoritative provenance.
    Nothing about the backend's identity participates in the seal.

    Parameters
    ----------
    recipe_form : list
        CSE recipe form, e.g. ``[b"oracle", name, prompt, [tools...], fuel]``.
    inputs : dict[str, bytes | None]
        Content of declared input files.  Files marked absent map to None.

    Returns
    -------
    tuple[dict[str, bytes], dict]
        ``(outputs, provenance)`` where *outputs* maps filenames to
        produced bytes, and *provenance* contains advisory metadata
        (model, tokens, cost, elapsed) that never enters verification.
    """

    def __call__(
        self,
        recipe_form: list,
        inputs: dict[str, bytes | None],
    ) -> tuple[dict[str, bytes], dict]: ...


# ── Flat-design elaboration ─────────────────────────────────────────

def _elaborate_recipe(rule_dict: dict[str, Any]) -> CseValue:
    """Convert a flat-design rule's recipe fields to a CSE recipe form.

    Only applies to producing kinds (action, oracle, trial).
    Structural kinds (commit, halt, let, cond) are handled by
    elaborate_node() directly.
    """
    kind: str = rule_dict["kind"]

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
        branches = [
            _elaborate_recipe(b) for b in rule_dict.get("branches", [])
        ]
        return [b"trial"] + branches

    raise ValueError(f"Unknown recipe kind: {kind!r}")


def elaborate(flat_design: dict[str, Any]) -> CseValue:
    """Convert a flat design dict to a CSE AST tree.

    The flat design is the ergonomic input format: a linear list of rules
    with implicit dependencies resolved by output->input edges.  The
    elaborator deterministically converts this into a CSE tree ready
    for ``encode()`` to produce canonical wire bytes.

    Supports all nine forms of the Husks calculus:

      - action, oracle, trial rules are elaborated with their recipe
        and child dependencies resolved from output->input edges.
      - commit and halt produce terminal CSE nodes.
      - let produces a ``(let <name> <bound-node>)`` CSE form that
        names a shared sub-DAG.
      - cond produces a ``(cond <predicate> <then> <else>)`` CSE form.

    Children of producing rules are ordered by first reference
    scanning the parent's input list left-to-right (CSE-v1.md
    section 7).  Shared producers appear as duplicated subtrees
    unless expressed via let.

    This function is deterministic: the same dependency graph always
    produces the same CSE tree regardless of rule ordering in the
    flat list.

    Parameters
    ----------
    flat_design : dict
        Design dict with keys ``name``, ``fuel``, ``target``, ``rules``,
        and optionally ``site_inputs``.

    Returns
    -------
    CseValue
        A CSE tree ``[b"husk", b"1", [b"build", ...]]`` ready for
        ``encode()``.
    """
    rules = flat_design["rules"]
    # Support both "targets" (list) and "target" (string)
    if "targets" in flat_design:
        val = flat_design["targets"]
        target_names: list[str] = [val] if isinstance(val, str) else list(val)
    else:
        target_names = [flat_design.get("target", rules[-1]["name"])]

    # Build output -> producer-name mapping (producing kinds only)
    producer: dict[str, str] = {}
    for r in rules:
        for o in r.get("outputs", []):
            producer[o] = r["name"]

    by_name: dict[str, dict] = {r["name"]: r for r in rules}

    def elaborate_node(rule_name: str) -> CseValue:
        r = by_name[rule_name]
        kind: str = r["kind"]

        # ── structural kinds ──
        if kind == "commit":
            return [b"commit", r.get("value", "ok").encode("utf-8")]

        if kind == "halt":
            return [b"halt", r.get("reason", "halted").encode("utf-8")]

        if kind == "let":
            bind_target: str = r["bind"]
            return [
                b"let",
                rule_name.encode("utf-8"),
                elaborate_node(bind_target),
            ]

        if kind == "cond":
            pred_name: str = r.get("predicate", "")
            then_node = elaborate_node(r["then"])
            else_node = elaborate_node(r["else"])
            return [
                b"cond",
                pred_name.encode("utf-8"),
                then_node,
                else_node,
            ]

        # ── producing kinds ──
        recipe = _elaborate_recipe(r)
        inputs: list[bytes] = [inp.encode("utf-8") for inp in r.get("inputs", [])]
        outputs: list[bytes] = [o.encode("utf-8") for o in r.get("outputs", [])]

        # Find children: rules that produce our inputs.
        # Order by first reference in input list.
        seen: set[str] = set()
        children: list[CseValue] = []
        for inp in r.get("inputs", []):
            if inp in producer:
                child_name = producer[inp]
                if child_name not in seen:
                    seen.add(child_name)
                    children.append(elaborate_node(child_name))

        result: list[CseValue] = [
            b"rule",
            rule_name.encode("utf-8"),
            recipe,
            inputs,
            outputs,
        ]
        result.extend(children)
        return result

    target_cse_nodes = [elaborate_node(t) for t in target_names]
    return [
        b"husk",
        b"1",
        [
            b"build",
            flat_design["name"].encode("utf-8"),
            str(flat_design["fuel"]).encode("utf-8"),
        ] + target_cse_nodes,
    ]
