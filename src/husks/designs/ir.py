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


def _validate_path(name: str) -> str | None:
    """Return an error string if *name* is an unsafe relative path, else None."""
    if os.path.isabs(name):
        return f"path must be relative, got absolute: {name}"
    parts = Path(name).parts
    if ".." in parts:
        return f"path contains '..': {name}"
    return None

# All valid rule kinds in the Husks calculus.
_RULE_KINDS = frozenset({"action", "oracle", "trial", "commit", "halt", "let", "cond"})

# Kinds that produce outputs and participate in the dependency DAG.
_PRODUCING_KINDS = frozenset({"action", "oracle", "trial"})

# Kinds that are structural (no inputs/outputs).
_STRUCTURAL_KINDS = frozenset({"commit", "halt", "let", "cond"})

# Built-in predicate prefixes that can be used in JSON designs.
_BUILTIN_PREFIXES = frozenset({"file-exists", "file-nonempty", "exit-zero"})


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

    if not design.get("name"):
        errors.append("design has no name")

    fuel = design.get("fuel")
    if fuel is None or fuel <= 0:
        errors.append("design has no fuel budget")

    rules = design.get("rules", [])
    if not rules:
        errors.append("design has no rules")
        return errors

    names: set[str] = set()
    produced: set[str] = set(design.get("site_inputs", []))
    predicates = design.get("predicates", {})

    for i, r in enumerate(rules):
        tag: str = r.get("name", f"rule[{i}]")

        # name
        if not r.get("name"):
            errors.append(f"{tag}: missing name")
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
                    errors.append(f"{tag}: output '{o}' already produced by another rule")
                produced.add(o)
            for inp in r.get("inputs", []):
                path_err = _validate_path(inp)
                if path_err:
                    errors.append(f"{tag}: input {path_err}")
                if inp not in produced:
                    errors.append(f"{tag}: input '{inp}' not produced by any prior rule")

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

    # oracle fuel budget: total oracle fuel must not exceed global fuel
    if fuel is not None and fuel > 0:
        total_oracle_fuel = sum(
            r.get("fuel", 0) for r in rules if r.get("kind") == "oracle"
        )
        if total_oracle_fuel > fuel:
            errors.append(
                f"total oracle fuel ({total_oracle_fuel}) exceeds "
                f"global fuel budget ({fuel})"
            )

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
        print(f"  site inputs: {', '.join(site_inputs)}")
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

    return design["name"], design["fuel"], terminals, kwargs


# ── Action factories ──────────────────────────────────────────────

def _make_shell_action(cmd: str, outputs: list[str]):
    """Create an action function that runs a shell command.

    The command runs in the site directory.  If the first declared
    output does not yet exist, stdout (and stderr on failure) are
    captured into it.  A nonzero exit code raises RuntimeError,
    which halts the build.
    """
    def shell_action(S: dict) -> None:
        from husks.build import site_path, write_text

        site = S["site"]
        result = subprocess.run(
            cmd,
            shell=True,
            cwd=site,
            capture_output=True,
            text=True,
            timeout=120,
        )
        if outputs and not Path(site_path(S, outputs[0])).exists():
            content = result.stdout
            if result.returncode != 0:
                content += f"\n--- STDERR (exit {result.returncode}) ---\n"
                content += result.stderr
            write_text(site_path(S, outputs[0]), content)
        if result.returncode != 0:
            raise RuntimeError(
                f"command failed (exit {result.returncode}): {cmd}\n"
                f"{result.stderr[:500]}"
            )

    shell_action._husks_cmd = cmd
    return shell_action


def _make_touch_action(outputs: list[str]):
    """Create an action that touches declared outputs.

    Used for terminal/gate nodes that have no explicit action.  Writes
    ``"ok\\n"`` into each output that does not yet exist.
    """
    def touch_action(S: dict) -> None:
        from husks.build import site_path, write_text

        for o in outputs:
            p = Path(site_path(S, o))
            if not p.exists():
                p.parent.mkdir(parents=True, exist_ok=True)
                write_text(site_path(S, o), "ok\n")

    touch_action._husks_cmd = "__touch__"
    return touch_action


# ── Imports setup ─────────────────────────────────────────────

def _setup_imports(site: str, imports: dict[str, str]) -> list[str]:
    """Create symlinks in the site for each declared import.

    Parameters
    ----------
    site : str
        Absolute path to the site directory.
    imports : dict
        Mapping of local names (relative to site) to external absolute paths.

    Returns
    -------
    list of str
        Resolved absolute paths of the external targets (for read-only
        sandbox registration).

    Raises
    ------
    ValueError
        If an external path does not exist.
    """
    readonly_dirs: list[str] = []
    for local_name, ext_path in imports.items():
        ext = Path(ext_path).resolve()
        if not ext.exists():
            raise ValueError(
                f"import '{local_name}': external path does not exist: {ext_path}"
            )
        link = Path(site) / local_name
        link.parent.mkdir(parents=True, exist_ok=True)
        if link.exists() or link.is_symlink():
            # Remove stale link from a previous run
            link.unlink()
        os.symlink(str(ext), str(link))
        readonly_dirs.append(str(ext))
    return readonly_dirs


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


def to_json(design: Design, path: str | Path | None = None) -> str:
    """Serialize a design to JSON.  If *path* is given, write to file."""
    s = json.dumps(design, indent=2)
    if path:
        with open(path, "w") as f:
            f.write(s)
    return s
