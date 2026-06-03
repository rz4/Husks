"""
_validation.py -- Design validation.

Provides check and check_categorized functions for validating design dicts.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Callable

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
        "children",   # Child rule names (from Locke nesting)
    }),
    "oracle": frozenset({
        "name", "kind", "inputs", "outputs",
        "prompt", "tools", "fuel",
        "equivalence", # Beta 100: Per-output equivalence relation
        "children",   # Child rule names (from Locke nesting)
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
    # Collect import namespace prefixes so inputs like "ref/data.csv" are recognized
    import_prefixes: list[str] = []
    imports_dict = design.get("imports")
    if isinstance(imports_dict, dict):
        for local_name in imports_dict:
            import_prefixes.append(local_name + "/")
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
                    # Check if input is under an import namespace
                    is_imported = any(inp.startswith(pfx) for pfx in import_prefixes)
                    if is_imported:
                        pass  # Imported paths are resolved at build time
                    elif inp in all_outputs:
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
