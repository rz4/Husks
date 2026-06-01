"""
ir.py -- Design intermediate representation for Husks builds.

JSON-native build graph: static validation (check), pretty-print (show),
compilation to runtime nodes (compile), and end-to-end execution (run).
Imports from build.py for node constructors; does not import core.py
directly.

See docs/architecture.md for the full IR schema, operations reference,
and supported rule kinds.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any, Callable


# ── Type alias ────────────────────────────────────────────────────

Design = dict[str, Any]


def _validate_rule_name(name: str) -> str | None:
    """Return an error string if *name* is an unsafe rule name, else None.

    Rule names are used to construct internal trace paths like
    .traces/{name}.seal, so they must not contain path separators,
    control characters, or reserved filenames.
    """
    if not name:
        return "rule name is empty"

    # Reject path separators (Unix / and Windows \)
    if "/" in name or "\\" in name:
        return f"rule name contains path separator: {name}"

    # Reject path traversal
    if name == ".." or name.startswith(".."):
        return f"rule name contains '..': {name}"

    # Reject control characters (0x00-0x1F, 0x7F)
    for i, c in enumerate(name):
        if ord(c) < 0x20 or ord(c) == 0x7F:
            return f"rule name contains control character at position {i}: {name}"

    # Reject reserved internal filenames
    reserved = {"build.manifest"}
    if name in reserved:
        return f"rule name collides with internal file: {name}"

    # Reject names that would create reserved extensions
    if name.endswith(".seal") or name.endswith(".trial") or name.endswith(".history"):
        return f"rule name uses reserved extension: {name}"

    return None


def _validate_path(name: str) -> str | None:
    """Return an error string if *name* is an unsafe relative path, else None."""
    if os.path.isabs(name):
        return f"path must be relative, got absolute: {name}"
    parts = Path(name).parts
    if ".." in parts:
        return f"path contains '..': {name}"

    # Reject internal/reserved paths
    if not parts:
        return None

    first = parts[0]

    # Reject specific system metadata directories
    if first in (".traces", ".husks"):
        return f"path targets reserved directory: {name}"

    # Reject .husk files anywhere in the path
    if name.endswith(".husk"):
        return f"path targets generated .husk file: {name}"

    return None

# All valid rule kinds in the Husks calculus.
_RULE_KINDS = frozenset({"action", "oracle", "trial", "commit", "halt", "let", "cond"})

# Kinds that produce outputs and participate in the dependency DAG.
_PRODUCING_KINDS = frozenset({"action", "oracle", "trial"})

# Kinds that are structural (no inputs/outputs).
_STRUCTURAL_KINDS = frozenset({"commit", "halt", "let", "cond"})

# Built-in predicate prefixes that can be used in JSON designs.
_BUILTIN_PREFIXES = frozenset({"file-exists", "file-nonempty", "exit-zero"})

# Top-level design fields that are allowed.
_ALLOWED_DESIGN_FIELDS = frozenset({
    "name",           # Build name
    "fuel",           # Global fuel budget
    "rules",          # List of rules
    "target",         # Single target (converted to targets)
    "targets",        # List of targets
    "site_inputs",    # External files to import
    "site",           # Site directory path (usually from overrides)
    "oracle_backend", # Oracle backend (usually from overrides)
    "oracle_model",   # Model identifier
    "imports",        # Import mappings
    "predicates",     # Named predicates for cond rules
    "cost_tolerance", # Beta 100: Cost comparability tolerance
    "_source_path",   # Internal: source file path (added by from_json)
})

# Rule fields allowed for each kind.
_ALLOWED_RULE_FIELDS = {
    "action": frozenset({
        "name", "kind", "inputs", "outputs",
        "run",        # Shell command
        "action_fn",  # Python callable (programmatic use only)
        "equivalence", # Beta 100: Per-output equivalence relation
    }),
    "oracle": frozenset({
        "name", "kind", "inputs", "outputs",
        "prompt", "tools", "fuel",
        "equivalence", # Beta 100: Per-output equivalence relation
    }),
    "trial": frozenset({
        "name", "kind", "inputs", "outputs",
        "branches", "verdict",
    }),
    "commit": frozenset({
        "name", "kind", "value",
    }),
    "halt": frozenset({
        "name", "kind", "reason",
    }),
    "let": frozenset({
        "name", "kind", "bind",
    }),
    "cond": frozenset({
        "name", "kind", "predicate", "then", "else",
    }),
}


# ── Target resolution ─────────────────────────────────────────────

def _resolve_targets(design: Design) -> list[str] | None:
    """Return the list of target names from a design.

    Accepts either ``"targets": [...]`` (list of strings) or
    ``"target": "x"`` (single string, wrapped into a one-element list).
    Returns None if neither key is present.
    """
    if "targets" in design:
        val = design["targets"]
        if isinstance(val, str):
            return [val]
        return list(val)
    if "target" in design:
        val = design["target"]
        if isinstance(val, list):
            return list(val)  # tolerate list in "target" key
        return [val]
    return None


# ── Rule-spec table & custom validators ──────────────────────────

def _validate_trial(tag: str, r: dict, errors: list[str], _pred: dict) -> None:
    verdict = r.get("verdict")
    if verdict is not None:
        if not callable(verdict) and not isinstance(verdict, str):
            errors.append(f"{tag}: verdict must be a callable or a policy name string")


def _validate_cond(tag: str, r: dict, errors: list[str], predicates: dict) -> None:
    pred_name = r.get("predicate")
    if pred_name and not callable(pred_name) and pred_name not in predicates:
        if ":" in pred_name:
            prefix = pred_name.split(":", 1)[0]
            if prefix not in _BUILTIN_PREFIXES:
                errors.append(f"{tag}: unknown built-in predicate prefix '{prefix}'")
        else:
            errors.append(f"{tag}: predicate '{pred_name}' not in design predicates")


_RULE_SPECS: dict[str, dict] = {
    "action":  {"producing": True},
    "oracle":  {"producing": True,
                "positive": {"fuel": "oracle rule has no fuel"},
                "required": {"prompt": "oracle rule has no prompt"}},
    "trial":   {"producing": True,
                "required": {"branches": "trial has no branches"},
                "validator": _validate_trial},
    "commit":  {"present": {"value": "commit has no value"}},
    "halt":    {"present": {"reason": "halt has no reason"}},
    "let":     {"required": {"bind": "let has no bind target"},
                "refs": {"bind": ("bind target", "not defined yet")}},
    "cond":    {"required": {"predicate": "cond has no predicate",
                             "then": "cond has no 'then' branch",
                             "else": "cond has no 'else' branch"},
                "refs": {"then": ("'then' target", "not defined yet"),
                         "else": ("'else' target", "not defined yet")},
                "validator": _validate_cond},
}


# ── Static checks ────────────────────────────────────────────────

def check(design: Design) -> list[str]:
    """Validate a design IR.  Returns a list of error strings (empty = ok)."""
    errors: list[str] = []

    # Check for unknown top-level fields
    for field in design:
        if field not in _ALLOWED_DESIGN_FIELDS:
            errors.append(f"unknown design field: '{field}'")

    if not design.get("name"):
        errors.append("design has no name")

    fuel = design.get("fuel")
    if fuel is None or fuel <= 0:
        errors.append("design has no fuel budget")

    # Beta 100: Validate cost_tolerance if present
    cost_tol = design.get("cost_tolerance")
    if cost_tol is not None:
        if not isinstance(cost_tol, dict):
            errors.append("cost_tolerance must be a dict")
        else:
            ratio = cost_tol.get("ratio")
            if ratio is None:
                errors.append("cost_tolerance must have 'ratio' field")
            elif not isinstance(ratio, list) or len(ratio) != 2:
                errors.append("cost_tolerance.ratio must be a two-element list [min, max]")
            elif not all(isinstance(x, (int, float)) and x > 0 for x in ratio):
                errors.append("cost_tolerance.ratio bounds must be positive numbers")
            elif ratio[0] > ratio[1]:
                errors.append("cost_tolerance.ratio minimum must be <= maximum")

    rules = design.get("rules", [])
    if not rules:
        errors.append("design has no rules")
        return errors

    names: set[str] = set()
    si = design.get("site_inputs", [])
    # For validation: extract local names from site_inputs
    # - dict form: keys are the local names (what rules reference)
    # - list form:
    #     - Absolute paths: basenames become the local names (e.g., /tmp/data.txt → data.txt)
    #     - Relative paths: full paths are the local names (e.g., ref/data.csv → ref/data.csv)
    if isinstance(si, dict):
        produced: set[str] = set(si.keys())
    else:
        produced: set[str] = set()
        for p in si:
            if Path(p).is_absolute():
                produced.add(Path(p).name)
            else:
                produced.add(p)
    predicates = design.get("predicates", {})

    # Track which rule produces each output (for better error messages)
    output_producers: dict[str, str] = {}
    # Track all outputs declared by all rules (for forward reference detection)
    all_outputs: set[str] = set()
    # Track inputs for each rule (for circular dependency detection)
    rule_inputs: dict[str, list[str]] = {}
    rule_outputs_map: dict[str, list[str]] = {}

    # First pass: collect all outputs and detect duplicates
    for i, r in enumerate(rules):
        tag: str = r.get("name", f"rule[{i}]")
        kind: str = r.get("kind", "")

        if kind in _PRODUCING_KINDS:
            outputs = r.get("outputs", [])
            rule_outputs_map[tag] = outputs
            for o in outputs:
                if o in all_outputs:
                    # Will be reported in second pass with both producer names
                    pass
                all_outputs.add(o)

    for i, r in enumerate(rules):
        tag: str = r.get("name", f"rule[{i}]")

        # name
        if not r.get("name"):
            errors.append(f"{tag}: missing name")
        else:
            name_err = _validate_rule_name(r["name"])
            if name_err:
                errors.append(f"{tag}: {name_err}")
            elif r["name"] in names:
                errors.append(f"{tag}: duplicate name")
        names.add(r.get("name", ""))

        # kind
        kind: str = r.get("kind", "")
        if kind not in _RULE_KINDS:
            errors.append(
                f"{tag}: kind must be one of {sorted(_RULE_KINDS)}, got '{kind}'"
            )
            continue

        # Check for unknown rule-level fields
        allowed_fields = _ALLOWED_RULE_FIELDS.get(kind)
        if allowed_fields:
            for field in r:
                if field not in allowed_fields:
                    errors.append(f"{tag}: unknown field '{field}' for {kind} rule")

        spec = _RULE_SPECS.get(kind)
        if not spec:
            continue

        # producing-kind validation (outputs, inputs)
        if spec.get("producing"):
            outputs = r.get("outputs", [])
            if not outputs:
                errors.append(f"{tag}: no declared outputs")
            for o in outputs:
                path_err = _validate_path(o)
                if path_err:
                    errors.append(f"{tag}: output {path_err}")
                if o in produced:
                    # Improved error: name both producers
                    first_producer = output_producers.get(o, "unknown")
                    errors.append(
                        f"{tag}: output '{o}' already produced by rule '{first_producer}'"
                    )
                else:
                    produced.add(o)
                    output_producers[o] = tag

            # Beta 100: Validate equivalence map if present
            equiv = r.get("equivalence", {})
            if equiv:
                if not isinstance(equiv, dict):
                    errors.append(f"{tag}: equivalence must be a dict")
                else:
                    for path, relation in equiv.items():
                        if path not in outputs:
                            errors.append(f"{tag}: equivalence key '{path}' not in declared outputs")
                        if relation not in ("exact", "free"):
                            errors.append(f"{tag}: equivalence value must be 'exact' or 'free', got '{relation}'")

            inputs = r.get("inputs", [])
            rule_inputs[tag] = inputs
            for inp in inputs:
                path_err = _validate_path(inp)
                if path_err:
                    errors.append(f"{tag}: input {path_err}")
                if inp not in produced:
                    # Check if this is a forward reference
                    if inp in all_outputs:
                        errors.append(
                            f"{tag}: input '{inp}' is a forward reference "
                            f"(produced by a later rule)"
                        )
                    else:
                        errors.append(f"{tag}: input '{inp}' not produced by any rule")

        # present fields (key must exist in dict)
        for field, msg in spec.get("present", {}).items():
            if field not in r:
                errors.append(f"{tag}: {msg}")

        # positive fields (> 0)
        for field, msg in spec.get("positive", {}).items():
            if r.get(field, 0) <= 0:
                errors.append(f"{tag}: {msg}")

        # required fields (value must be truthy)
        for field, msg in spec.get("required", {}).items():
            if not r.get(field):
                errors.append(f"{tag}: {msg}")

        # reference fields (value must be in names set)
        for field, (label, suffix) in spec.get("refs", {}).items():
            val = r.get(field)
            if val and val not in names:
                errors.append(f"{tag}: {kind} {label} '{val}' {suffix}")

        # custom validator
        if "validator" in spec:
            spec["validator"](tag, r, errors, predicates)

    # Circular dependency detection
    def _detect_cycle(
        node: str,
        visited: set[str],
        rec_stack: set[str],
        path: list[str]
    ) -> list[str] | None:
        """DFS to detect cycles. Returns cycle path if found, else None."""
        visited.add(node)
        rec_stack.add(node)
        path.append(node)

        # Get dependencies: rules that produce this node's inputs
        node_inputs = rule_inputs.get(node, [])
        for inp in node_inputs:
            # Find which rule produces this input
            producer = output_producers.get(inp)
            if producer and producer in rule_outputs_map:  # producing rule
                if producer not in visited:
                    cycle = _detect_cycle(producer, visited, rec_stack, path)
                    if cycle:
                        return cycle
                elif producer in rec_stack:
                    # Found a cycle - return the path from producer to current
                    cycle_start = path.index(producer)
                    return path[cycle_start:] + [producer]

        path.pop()
        rec_stack.remove(node)
        return None

    visited: set[str] = set()
    for rule_name in rule_inputs:
        if rule_name not in visited:
            cycle = _detect_cycle(rule_name, visited, set(), [])
            if cycle:
                cycle_str = " -> ".join(cycle)
                errors.append(f"circular dependency detected: {cycle_str}")
                break  # Report first cycle found

    # imports
    imports = design.get("imports")
    if imports is not None:
        if not isinstance(imports, dict):
            errors.append("imports must be a dict mapping local names to absolute paths")
        else:
            rule_outputs: set[str] = set()
            for r in rules:
                for o in r.get("outputs", []):
                    rule_outputs.add(o)
            for local_name, ext_path in imports.items():
                local_err = _validate_path(local_name)
                if local_err:
                    errors.append(f"import '{local_name}': local name {local_err}")
                if not isinstance(ext_path, str):
                    errors.append(f"import '{local_name}': value must be a string path")
                elif not os.path.isabs(ext_path):
                    errors.append(
                        f"import '{local_name}': path must be absolute, got '{ext_path}'"
                    )
                if local_name in rule_outputs:
                    errors.append(
                        f"import '{local_name}' collides with a rule output name"
                    )

    # target(s)
    targets = _resolve_targets(design)
    if targets is None:
        errors.append("design has no target (must provide 'target' or 'targets')")
    elif len(targets) == 0:
        errors.append("'targets' list is empty")
    else:
        for t in targets:
            if t not in names:
                errors.append(f"target '{t}' does not match any rule name")

    return errors


# ── Categorized check ─────────────────────────────────────────────

def check_categorized(design: Design) -> dict[str, Any]:
    """Validate a design and return errors grouped by category.

    Returns a dict with keys: ok, categories, errors.
    Each category has: ok (bool), errors (list[str]).
    """
    all_errors = check(design)

    categories: dict[str, dict[str, Any]] = {
        "syntax": {"ok": True, "errors": []},
        "names": {"ok": True, "errors": []},
        "paths": {"ok": True, "errors": []},
        "inputs": {"ok": True, "errors": []},
        "outputs": {"ok": True, "errors": []},
        "fuel": {"ok": True, "errors": []},
        "targets": {"ok": True, "errors": []},
        "imports": {"ok": True, "errors": []},
        "other": {"ok": True, "errors": []},
    }

    for err in all_errors:
        el = err.lower()
        if "name" in el or "duplicate" in el:
            cat = "names"
        elif "path" in el or "absolute" in el or "'..'" in el:
            cat = "paths"
        elif "input" in el and "not produced" in el:
            cat = "inputs"
        elif "output" in el and ("produced" in el or "no declared" in el):
            cat = "outputs"
        elif "fuel" in el:
            cat = "fuel"
        elif "target" in el:
            cat = "targets"
        elif "import" in el:
            cat = "imports"
        elif "kind" in el or "no rules" in el or "has no" in el:
            cat = "syntax"
        else:
            cat = "other"
        categories[cat]["errors"].append(err)
        categories[cat]["ok"] = False

    return {
        "ok": len(all_errors) == 0,
        "categories": categories,
        "errors": all_errors,
    }


# ── Pretty-print ──────────────────────────────────────────────────

_KIND_MARKERS = {
    "oracle": "\u25b8",   # ▸
    "action": "\u25cf",   # ●
    "trial":  "\u25e6",   # ◦
    "commit": "\u2713",   # ✓
    "halt":   "\u2717",   # ✗
    "let":    "\u2192",   # →
    "cond":   "?",
}


def show(design: Design) -> None:
    """Print a human-readable summary of the design."""
    name = design.get("name", "?")
    fuel = design.get("fuel", "?")
    targets = _resolve_targets(design) or ["?"]
    rules = design.get("rules", [])
    site_inputs = design.get("site_inputs", [])
    target_set = set(targets)

    targets_str = ", ".join(targets)
    print(f"\n  design: {name}  (fuel {fuel})  targets: {targets_str}")
    print(f"  {'─' * 50}")

    if site_inputs:
        if isinstance(site_inputs, dict):
            si_names = list(site_inputs.keys())
        else:
            # For list form, show basenames (the local names in the site)
            si_names = [Path(p).name for p in site_inputs]
        print(f"  site inputs: {', '.join(si_names)}")
        print()

    for r in rules:
        kind = r.get("kind", "?")
        rname = r.get("name", "?")
        inputs = r.get("inputs", [])
        outputs = r.get("outputs", [])
        is_target = rname in target_set
        marker = _KIND_MARKERS.get(kind, "?")
        target_tag = "  \u25c0 target" if is_target else ""

        if kind == "oracle":
            print(f"  {marker} {rname}  ({kind}  fuel {r.get('fuel', '?')}){target_tag}")
        elif kind == "trial":
            branches = r.get("branches", [])
            print(f"  {marker} {rname}  ({kind}  {len(branches)} branches){target_tag}")
        elif kind == "commit":
            print(f"  {marker} {rname}  (commit: {r.get('value', '?')}){target_tag}")
        elif kind == "halt":
            print(f"  {marker} {rname}  (halt: {r.get('reason', '?')}){target_tag}")
        elif kind == "let":
            print(f"  {marker} {rname}  (let -> {r.get('bind', '?')}){target_tag}")
        elif kind == "cond":
            print(f"  {marker} {rname}  (cond: {r.get('predicate', '?')}"
                  f"  then={r.get('then', '?')}  else={r.get('else', '?')}){target_tag}")
        else:
            print(f"  {marker} {rname}  ({kind}){target_tag}")

        if inputs:
            print(f"    in:  {', '.join(inputs)}")
        if outputs:
            print(f"    out: {', '.join(outputs)}")
        if kind == "action" and r.get("run"):
            print(f"    run: {r['run']}")

    print(f"  {'─' * 50}\n")


# ── Predicate resolution ─────────────────────────────────────────

def _resolve_predicate(
    spec: str | Callable,
    predicates: dict[str, Callable],
) -> Callable[[dict], bool]:
    """Turn a predicate spec into a callable ``(Store) -> bool``.

    Resolution order:

    1. If *spec* is already callable, return it.
    2. If *spec* is a key in *predicates*, return the mapped callable.
    3. If *spec* matches ``prefix:arg`` with a known built-in prefix,
       build and return the corresponding closure.
    4. Otherwise raise ``ValueError``.
    """
    if callable(spec):
        return spec

    if spec in predicates:
        return predicates[spec]

    if ":" in spec:
        prefix, arg = spec.split(":", 1)
        if prefix == "file-exists":
            def _file_exists(S: dict) -> bool:
                from husks.build import site_path
                return os.path.exists(site_path(S, arg))
            _file_exists._husks_pred_spec = spec
            return _file_exists

        if prefix == "file-nonempty":
            def _file_nonempty(S: dict) -> bool:
                from husks.build import site_path
                p = site_path(S, arg)
                return os.path.exists(p) and os.path.getsize(p) > 0
            _file_nonempty._husks_pred_spec = spec
            return _file_nonempty

        if prefix == "exit-zero":
            def _exit_zero(S: dict) -> bool:
                result = subprocess.run(
                    arg, shell=True, cwd=S["site"],
                    capture_output=True, timeout=120,
                )
                return result.returncode == 0
            _exit_zero._husks_pred_spec = spec
            return _exit_zero

    raise ValueError(f"unknown predicate: {spec!r}")


# ── Compiler ──────────────────────────────────────────────────────

def compile(design: Design) -> tuple[str, int, list[dict], dict[str, Any]]:
    """Lower design IR to runtime arguments for build().

    Returns (name, fuel, terminal_nodes, kwargs) ready for::

        build(name, fuel, *terminal_nodes, **kwargs)

    Handles all nine forms:
      - action/oracle/trial: compiled into rule nodes with recipes.
      - let: resolved to the already-compiled node for the bind
        target.  The same node dict instance is shared, so the
        evaluator visits it once and seals it once.
      - cond: compiled into a cond node with resolved predicate
        callable and then/else child nodes.
      - commit/halt: compiled into terminal nodes.

    Dependency resolution: for each producing rule, any previously
    compiled rule whose outputs overlap with this rule's inputs
    becomes a child node.  Children are ordered by first input
    reference (left-to-right).
    """
    from husks.build import (
        rule,
        action,
        oracle,
        trial as trial_recipe,
        cond as cond_node,
        commit as commit_node,
        halt as halt_node,
    )

    rules = design.get("rules", [])
    targets = _resolve_targets(design) or ([rules[-1]["name"]] if rules else [])
    predicates: dict[str, Callable] = design.get("predicates", {})
    name_to_node: dict[str, dict] = {}
    name_to_ir: dict[str, dict] = {r["name"]: r for r in rules}

    for r in rules:
        rname: str = r["name"]
        kind: str = r["kind"]

        # ── let: alias to an already-compiled node ──
        if kind == "let":
            bind_target: str = r["bind"]
            name_to_node[rname] = name_to_node[bind_target]
            continue

        # ── commit / halt: terminal nodes ──
        if kind == "commit":
            name_to_node[rname] = commit_node(r.get("value", "ok"))
            continue

        if kind == "halt":
            name_to_node[rname] = halt_node(r.get("reason", "halted"))
            continue

        # ── cond: conditional branch ──
        if kind == "cond":
            pred_fn = _resolve_predicate(r["predicate"], predicates)
            then = name_to_node[r["then"]]
            else_ = name_to_node[r["else"]]
            name_to_node[rname] = cond_node(pred_fn, then, else_)
            continue

        # ── producing kinds: action, oracle, trial ──
        inputs: list[str] = r.get("inputs", [])
        outputs: list[str] = r.get("outputs", [])

        # Resolve children: any prior rule whose outputs are in our inputs.
        children: list[dict] = []
        for inp in inputs:
            for prev_name, prev_node in name_to_node.items():
                prev_outputs = prev_node.get("outputs", [])
                if inp in prev_outputs and prev_node not in children:
                    children.append(prev_node)

        if kind == "action":
            run_cmd = r.get("run")
            if run_cmd:
                recipe = action(_make_shell_action(run_cmd, outputs))
            elif r.get("action_fn") and callable(r["action_fn"]):
                recipe = action(r["action_fn"])
            else:
                recipe = action(_make_touch_action(outputs))
        elif kind == "oracle":
            recipe = oracle(
                prompt=r.get("prompt", ""),
                tools=r.get("tools", ["read-file", "write-file", "list-dir", "tree"]),
                fuel=r.get("fuel", 8),
            )
        elif kind == "trial":
            branches = r.get("branches", [])
            verdict_fn = r.get("verdict")
            # Each branch is a recipe dict; compile them
            compiled_branches = []
            for b in branches:
                bkind = b.get("type", b.get("kind", "oracle"))
                if bkind == "oracle":
                    compiled_branches.append({
                        "type": "oracle",
                        "name": b.get("name"),
                        "prompt": b.get("prompt", ""),
                        "tools": b.get("tools", ["read-file", "write-file", "list-dir", "tree"]),
                        "fuel": b.get("fuel", 8),
                    })
                elif bkind == "action":
                    fn = b.get("action_fn") or _make_touch_action(outputs)
                    compiled_branches.append({"type": "action", "fn": fn})
                else:
                    compiled_branches.append(b)
            recipe = trial_recipe(*compiled_branches, verdict=verdict_fn)
        else:
            raise ValueError(f"unknown producing kind: {kind!r}")

        node = rule(rname, *children, inputs=inputs, outputs=outputs, recipe=recipe)
        name_to_node[rname] = node

    terminals = [name_to_node[t] for t in targets]

    kwargs: dict[str, Any] = {}
    if design.get("site"):
        kwargs["site"] = design["site"]
    if design.get("oracle_backend"):
        kwargs["oracle_backend"] = design["oracle_backend"]
    if design.get("oracle_model"):
        kwargs["oracle_model"] = design["oracle_model"]
    if design.get("site_inputs"):
        kwargs["site_inputs"] = design["site_inputs"]

    return design["name"], design["fuel"], terminals, kwargs


# ── Action factories ──────────────────────────────────────────────

from husks.build import _make_shell_action  # re-exported for tests


def _make_touch_action(outputs: list[str]):
    """Create an action that touches declared outputs.

    Used for terminal/gate nodes that have no explicit action.  Writes
    ``"ok\\n"`` into each output that does not yet exist.
    """
    def touch_action(S: dict) -> None:
        from husks.build import site_path, write_text

        for o in outputs:
            p = Path(site_path(S, o, write=True))
            if not p.exists():
                p.parent.mkdir(parents=True, exist_ok=True)
                write_text(site_path(S, o, write=True), "ok\n")

    touch_action._husks_cmd = "__touch__"
    return touch_action


# ── Imports setup ─────────────────────────────────────────────

def _setup_imports(site: str, imports: dict[str, str]) -> list[str]:
    """Create symlinks in the site for each declared import.

    Delegates to :func:`husks.build.site.setup_links`.
    """
    from husks.build.site import setup_links
    return setup_links(site, imports)


# ── Run ───────────────────────────────────────────────────────────

def run(design: Design, **overrides: Any) -> dict[str, Any]:
    """Check, compile, and execute a design.  Returns the Store."""
    errs = check(design)
    if errs:
        raise ValueError("design check failed:\n  " + "\n  ".join(errs))

    from husks.build import build

    name, fuel, terminals, kwargs = compile(design)
    kwargs.update(overrides)

    # Pass design source metadata for the build manifest
    if design.get("_source_path"):
        kwargs["design_source"] = design["_source_path"]
        kwargs["design_kind"] = "json"

    # Beta Gate A1/A2: Normalize site_inputs against design source path
    # Only normalize if design has a source path (loaded from file via CLI).
    # For programmatic/API usage without _source_path, assume site_inputs
    # are already valid paths (absolute or in-site).
    if "site_inputs" in kwargs:
        design_source = design.get("_source_path")
        if design_source is not None:
            # Design loaded from file - normalize relative paths
            kwargs["site_inputs"] = normalize_site_inputs(
                kwargs["site_inputs"], design_source
            )
        # else: programmatic design with no source path - skip normalization

    # Set up imports (symlinks + read-only roots) before building
    imports = design.get("imports")
    site = kwargs.get("site")
    if imports and site:
        readonly_dirs = _setup_imports(site, imports)
        kwargs["readonly_dirs"] = readonly_dirs

    return build(name, fuel, *terminals, **kwargs)


# ── Load / save ───────────────────────────────────────────────────

def from_json(path: str | Path) -> Design:
    """Load a design from a JSON file."""
    with open(path) as f:
        design = json.load(f)
    design["_source_path"] = str(Path(path).resolve())
    return design


def normalize_site_inputs(
    site_inputs: list[str] | dict[str, str] | None,
    design_source_path: str | None = None,
) -> dict[str, str]:
    """Normalize site_inputs to a dict of local_name → resolved_path.

    **Beta Gate A1/A2**: Resolves relative paths against the design file's
    directory and validates that all declared inputs exist.

    Parameters
    ----------
    site_inputs : list, dict, or None
        - List form: ["prompt.txt", "/abs/path.txt"]
          Relative paths are resolved against design_source_path.
          Absolute paths are used as-is.
          Local name is the basename for absolute paths, or the full relative
          path for relative paths.
        - Dict form: {"local_name": "source_path"}
          Source paths are resolved against design_source_path if relative.
        - None: returns empty dict

    design_source_path : str, optional
        Path to the design.json file (from design["_source_path"]).
        Required for resolving relative paths.

    Returns
    -------
    dict
        Mapping of local_name (relative path in site) → resolved_absolute_path.

    Raises
    ------
    ValueError
        If a relative path is given without design_source_path, or if a
        declared input file does not exist.

    Examples
    --------
    >>> # List form with relative path
    >>> normalize_site_inputs(["prompt.txt"], "/path/to/design.json")
    {"prompt.txt": "/path/to/prompt.txt"}

    >>> # Dict form with explicit mapping
    >>> normalize_site_inputs({"input.txt": "data.txt"}, "/path/to/design.json")
    {"input.txt": "/path/to/data.txt"}

    >>> # Absolute path
    >>> normalize_site_inputs(["/tmp/data.txt"], None)
    {"data.txt": "/tmp/data.txt"}
    """
    if site_inputs is None:
        return {}

    design_dir = None
    if design_source_path:
        design_dir = Path(design_source_path).parent.resolve()

    result = {}

    if isinstance(site_inputs, list):
        for entry in site_inputs:
            p = Path(entry)
            if p.is_absolute():
                # Absolute path: local name is basename
                local_name = p.name
                resolved = p.resolve()
            else:
                # Relative path: resolve against design directory
                if design_dir is None:
                    raise ValueError(
                        f"Relative site_input '{entry}' requires design source path"
                    )
                local_name = entry
                resolved = (design_dir / entry).resolve()

            # Validate that the file exists
            if not resolved.exists():
                raise ValueError(
                    f"Declared site_input does not exist: {entry}\n"
                    f"  Resolved path: {resolved}"
                )

            result[local_name] = str(resolved)

    elif isinstance(site_inputs, dict):
        for local_name, source_path in site_inputs.items():
            p = Path(source_path)
            if p.is_absolute():
                resolved = p.resolve()
            else:
                if design_dir is None:
                    raise ValueError(
                        f"Relative site_input source '{source_path}' requires design source path"
                    )
                resolved = (design_dir / source_path).resolve()

            # Validate that the file exists
            if not resolved.exists():
                raise ValueError(
                    f"Declared site_input does not exist: {source_path}\n"
                    f"  Local name: {local_name}\n"
                    f"  Resolved path: {resolved}"
                )

            result[local_name] = str(resolved)

    return result


def to_json(design: Design, path: str | Path | None = None) -> str:
    """Serialize a design to JSON.  If *path* is given, write to file."""
    s = json.dumps(design, indent=2)
    if path:
        with open(path, "w") as f:
            f.write(s)
    return s
