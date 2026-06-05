"""L1 forms -- CSE<->JSON bijection, flat-design elaboration, recipe identity, verdict policies.

Sits on L0 (kernel).  Only dependencies: kernel + stdlib (hashlib, inspect, json).
Merges design/transport.py, build/identity.py, and build/policies.py into one
hardened module.  No runtime engine code (no node constructors, Store, Site, shell actions).
"""

from __future__ import annotations

import hashlib
import inspect
import json
from typing import Any, Callable

from husks.kernel import CseValue, NIL, encode, parse

# ── Atom helpers ─────────────────────────────────────────────────

def _a2j(a: bytes) -> str | None:
    """CSE atom -> JSON (NIL becomes None)."""
    return None if a == NIL else a.decode("utf-8")


def _al2j(lst: list[bytes]) -> list[str | None]:
    """CSE atom list -> JSON string list."""
    return [_a2j(a) for a in lst]


def _j2a(v: str | None) -> bytes:
    """JSON string|null -> CSE atom."""
    return NIL if v is None else v.encode("utf-8")


def _j2al(lst: list[str | None]) -> list[bytes]:
    """JSON string list -> CSE atom list."""
    return [_j2a(s) for s in lst]


# ── AST -> JSON ──────────────────────────────────────────────────

def ast_to_json(cse_value: CseValue) -> Any:
    """CSE tree -> canonical JSON-serializable dict.  Raises ValueError on unknown tags."""
    if isinstance(cse_value, bytes):
        return _a2j(cse_value)
    tag: bytes = cse_value[0]
    if tag == b"husk":
        return {"form": "husk", "version": _a2j(cse_value[1]), "build": ast_to_json(cse_value[2])}
    if tag == b"build":
        return {"form": "build", "name": _a2j(cse_value[1]), "fuel": _a2j(cse_value[2]),
                "targets": [ast_to_json(t) for t in cse_value[3:]]}
    if tag == b"rule":
        return {"form": "rule", "name": _a2j(cse_value[1]), "recipe": ast_to_json(cse_value[2]),
                "inputs": _al2j(cse_value[3]), "outputs": _al2j(cse_value[4]),
                "children": [ast_to_json(c) for c in cse_value[5:]]}
    if tag == b"action":
        return {"form": "action"}
    if tag == b"oracle":
        return {"form": "oracle", "name": _a2j(cse_value[1]), "prompt": _a2j(cse_value[2]),
                "tools": _al2j(cse_value[3]), "fuel": _a2j(cse_value[4])}
    if tag == b"trial":
        return {"form": "trial", "branches": [ast_to_json(b) for b in cse_value[1:]]}
    if tag == b"commit":
        return {"form": "commit", "value": _a2j(cse_value[1])}
    if tag == b"halt":
        return {"form": "halt", "reason": _a2j(cse_value[1])}
    if tag == b"cond":
        return {"form": "cond", "predicate": _a2j(cse_value[1]),
                "then": ast_to_json(cse_value[2]), "else": ast_to_json(cse_value[3])}
    if tag == b"let":
        return {"form": "let", "name": _a2j(cse_value[1]), "bound": ast_to_json(cse_value[2])}
    raise ValueError(f"Unknown CSE form tag: {tag!r}")


# ── JSON -> AST ──────────────────────────────────────────────────

def json_to_ast(json_value: Any) -> CseValue:
    """JSON dict -> CSE tree.  Inverse of ast_to_json.  Raises ValueError on unknown forms."""
    if not isinstance(json_value, dict):
        return _j2a(json_value)
    form: str = json_value["form"]
    if form == "husk":
        return [b"husk", _j2a(json_value["version"]), json_to_ast(json_value["build"])]
    if form == "build":
        targets = json_value.get("targets", [])
        if not targets and "target" in json_value:
            targets = [json_value["target"]]
        return [b"build", _j2a(json_value["name"]), _j2a(json_value["fuel"])] + [json_to_ast(t) for t in targets]
    if form == "rule":
        result: list[CseValue] = [b"rule", _j2a(json_value["name"]), json_to_ast(json_value["recipe"]),
                                   _j2al(json_value["inputs"]), _j2al(json_value["outputs"])]
        result.extend(json_to_ast(c) for c in json_value["children"])
        return result
    if form == "action":
        return [b"action"]
    if form == "oracle":
        return [b"oracle", _j2a(json_value["name"]), _j2a(json_value["prompt"]),
                _j2al(json_value["tools"]), _j2a(json_value["fuel"])]
    if form == "trial":
        return [b"trial"] + [json_to_ast(b) for b in json_value["branches"]]
    if form == "commit":
        return [b"commit", _j2a(json_value["value"])]
    if form == "halt":
        return [b"halt", _j2a(json_value["reason"])]
    if form == "cond":
        return [b"cond", _j2a(json_value["predicate"]), json_to_ast(json_value["then"]),
                json_to_ast(json_value["else"])]
    if form == "let":
        return [b"let", _j2a(json_value["name"]), json_to_ast(json_value["bound"])]
    raise ValueError(f"Unknown JSON form: {form!r}")


# ── Convenience ──────────────────────────────────────────────────

def to_json_str(cse_value: CseValue) -> str:
    """CSE tree -> pretty-printed JSON string."""
    return json.dumps(ast_to_json(cse_value), indent=2)


def from_json_str(json_str: str) -> CseValue:
    """JSON string -> CSE tree."""
    return json_to_ast(json.loads(json_str))


def round_trip(cse_bytes: bytes) -> bytes:
    """Full bijection round-trip: parse -> JSON -> AST -> encode.  Output must equal input."""
    return encode(json_to_ast(ast_to_json(parse(cse_bytes))))


# ── Flat-design elaboration ──────────────────────────────────────

def _elaborate_recipe(rule_dict: dict[str, Any]) -> CseValue:
    """Flat rule dict -> CSE recipe form (action/oracle/trial only)."""
    kind: str = rule_dict["kind"]
    if kind == "action":
        return [b"action"]
    if kind == "oracle":
        name = rule_dict.get("oracle_name")
        return [b"oracle", name.encode("utf-8") if name else NIL,
                rule_dict.get("prompt", "").encode("utf-8"),
                [t.encode("utf-8") for t in rule_dict.get("tools", [])],
                str(rule_dict.get("fuel", 8)).encode("utf-8")]
    if kind == "trial":
        return [b"trial"] + [_elaborate_recipe(b) for b in rule_dict.get("branches", [])]
    raise ValueError(f"Unknown recipe kind: {kind!r}")


def elaborate(flat_design: dict[str, Any]) -> CseValue:
    """Flat design dict -> CSE husk tree.  Deterministic, cycle-detecting."""
    rules = flat_design["rules"]
    if "targets" in flat_design:
        val = flat_design["targets"]
        target_names: list[str] = [val] if isinstance(val, str) else list(val)
    else:
        target_names = [flat_design.get("target", rules[-1]["name"])]

    producer: dict[str, str] = {}
    for r in rules:
        for o in r.get("outputs", []):
            producer[o] = r["name"]
    by_name: dict[str, dict] = {r["name"]: r for r in rules}

    def elaborate_node(rule_name: str, ancestors: tuple[str, ...] = ()) -> CseValue:
        """Elaborate a single rule, tracking ancestors for cycle detection."""
        if rule_name in ancestors:
            raise ValueError(f"dependency cycle detected: {' → '.join(ancestors + (rule_name,))}")
        r = by_name[rule_name]
        kind: str = r["kind"]
        new_ancestors = ancestors + (rule_name,)

        # Structural kinds
        if kind == "commit":
            return [b"commit", r.get("value", "ok").encode("utf-8")]
        if kind == "halt":
            return [b"halt", r.get("reason", "halted").encode("utf-8")]
        if kind == "let":
            return [b"let", rule_name.encode("utf-8"), elaborate_node(r["bind"], new_ancestors)]
        if kind == "cond":
            return [b"cond", r.get("predicate", "").encode("utf-8"),
                    elaborate_node(r["then"], new_ancestors), elaborate_node(r["else"], new_ancestors)]

        # Producing kinds
        recipe = _elaborate_recipe(r)
        inputs: list[bytes] = [inp.encode("utf-8") for inp in r.get("inputs", [])]
        outputs: list[bytes] = [o.encode("utf-8") for o in r.get("outputs", [])]

        seen: set[str] = set()
        children: list[CseValue] = []
        for inp in r.get("inputs", []):
            if inp in producer:
                child_name = producer[inp]
                if child_name not in seen:
                    seen.add(child_name)
                    children.append(elaborate_node(child_name, new_ancestors))

        result: list[CseValue] = [b"rule", rule_name.encode("utf-8"), recipe, inputs, outputs]
        result.extend(children)
        return result

    target_cse = [elaborate_node(t) for t in target_names]
    return [b"husk", b"1", [b"build", flat_design["name"].encode("utf-8"),
            str(flat_design["fuel"]).encode("utf-8")] + target_cse]


# ── Behavior digest ──────────────────────────────────────────────

def _fn_behavior_digest(fn: Callable) -> str:
    """SHA-256 hex digest of a callable's source (or bytecode+consts fallback)."""
    try:
        return hashlib.sha256(inspect.getsource(fn).encode()).hexdigest()
    except (OSError, TypeError):
        code = fn.__code__
        return hashlib.sha256(code.co_code + repr(code.co_consts).encode()).hexdigest()


def _pred_identity(predicate: Callable) -> str:
    """Predicate identity: _husks_pred_spec attribute if present, else behavior digest."""
    spec = getattr(predicate, "_husks_pred_spec", None)
    return spec if spec is not None else _fn_behavior_digest(predicate)


# ── Verdict policies ─────────────────────────────────────────────

_FIRST_VALID_NAME = b"first-valid"


def first_valid(results: list[dict[str, Any]]) -> dict[str, Any]:
    """Default verdict: first branch without an 'error' key; falls back to first result."""
    for r in results:
        if "error" not in r:
            return r
    return results[0]


VERDICT_POLICIES: dict[str, Callable] = {"first-valid": first_valid, "first_valid": first_valid}
DEFAULT_VERDICT = first_valid


def verdict_identity(verdict: Any) -> bytes:
    """Canonical identity bytes for a trial verdict policy."""
    if verdict is None or verdict is first_valid or verdict is DEFAULT_VERDICT:
        return _FIRST_VALID_NAME
    if isinstance(verdict, str):
        if verdict in VERDICT_POLICIES and VERDICT_POLICIES[verdict] is first_valid:
            return _FIRST_VALID_NAME
        return verdict.encode()
    return _fn_behavior_digest(verdict).encode()


# ── Recipe -> CSE ────────────────────────────────────────────────

def recipe_to_cse(recipe: dict[str, Any] | None) -> CseValue:
    """Engine recipe dict -> CSE form for sealing.  References fn._husks_cmd (set by engine)."""
    if recipe is None:
        return NIL
    kind: str = recipe["type"]
    if kind == "action":
        fn = recipe["fn"]
        args = recipe.get("args", ())
        cmd: str = getattr(fn, "_husks_cmd", "")
        if cmd:
            return [b"action", cmd.encode()]
        parts: list[CseValue] = [b"action", _fn_behavior_digest(fn).encode()]
        if args:
            parts.append(repr(args).encode())
        return parts
    if kind == "oracle":
        name = recipe.get("name")
        return [b"oracle", name.encode() if name else NIL, recipe.get("prompt", "").encode(),
                [t.encode() for t in sorted(recipe.get("tools", []))],
                str(recipe.get("fuel", 8)).encode()]
    if kind == "trial":
        return [b"trial", verdict_identity(recipe.get("verdict"))] + [recipe_to_cse(b) for b in recipe["branches"]]
    return NIL
