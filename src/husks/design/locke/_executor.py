"""
_executor.py -- Design compilation and execution.

Provides compile_design and run functions for executing designs.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Any, Callable

from ._validation import _resolve_targets, check

Design = dict[str, Any]


# Runtime dependencies (hoisted from deferred imports per architecture doc)
from husks.build import (
    rule, action, oracle, trial as trial_recipe,
    cond as cond_node, commit as commit_node, halt as halt_node,
    _make_shell_action,
)
from husks.build.site import setup_links, site_path, write_text


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

def compile_design(design: Design) -> tuple[str, int, list[dict], dict[str, Any]]:
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
    from ._io import normalize_site_inputs

    name, fuel, terminals, kwargs = compile_design(design)
    kwargs.update(overrides)

    # Pass design source metadata for the build manifest
    if design.get("_source_path"):
        kwargs["design_source"] = design["_source_path"]
        source_path = design["_source_path"]
        if source_path.endswith(".locke"):
            kwargs["design_kind"] = "locke"
        else:
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
