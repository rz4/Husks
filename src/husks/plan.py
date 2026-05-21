#- plan.py — Husk Plan IR
#
# The plan is a Husk: a machine-checkable, auditable build graph
# that agents can propose and humans can edit.
#
# Three operations:
#   check(plan)   — static validation before execution
#   compile(plan) — lower Plan IR → Husks runtime nodes
#   run(plan)     — compile + execute, return store with trace
#
# Plan IR is plain JSON/dict:
#
#   {
#     "name": "my-build",
#     "fuel": 40,
#     "target": "final-step",
#     "rules": [
#       {"name": "step-1", "kind": "action", "outputs": ["a.txt"]},
#       {"name": "step-2", "kind": "oracle", "inputs": ["a.txt"],
#        "outputs": ["b.txt"], "prompt": "...", "tools": [...], "fuel": 5},
#       {"name": "final-step", "kind": "action",
#        "inputs": ["a.txt", "b.txt"], "outputs": [".complete"]}
#     ]
#   }

import json
import subprocess
from pathlib import Path


# ── Static checks ────────────────────────────────────────────

def check(plan):
    """Validate a plan IR. Returns a list of error strings (empty = ok)."""
    errors = []

    if not plan.get("name"):
        errors.append("plan has no name")

    fuel = plan.get("fuel")
    if fuel is None or fuel <= 0:
        errors.append("plan has no fuel budget")

    rules = plan.get("rules", [])
    if not rules:
        errors.append("plan has no rules")
        return errors

    names = set()
    produced = set()
    oracle_fuel = 0

    for i, r in enumerate(rules):
        tag = r.get("name", f"rule[{i}]")

        # name
        if not r.get("name"):
            errors.append(f"{tag}: missing name")
        elif r["name"] in names:
            errors.append(f"{tag}: duplicate name")
        names.add(r.get("name", ""))

        # kind
        kind = r.get("kind", "")
        if kind not in ("action", "oracle"):
            errors.append(f"{tag}: kind must be 'action' or 'oracle', got '{kind}'")

        # outputs
        outputs = r.get("outputs", [])
        if not outputs:
            errors.append(f"{tag}: no declared outputs")
        for o in outputs:
            if o in produced:
                errors.append(f"{tag}: output '{o}' already produced by another rule")
            produced.add(o)

        # inputs available
        for inp in r.get("inputs", []):
            if inp not in produced:
                errors.append(f"{tag}: input '{inp}' not produced by any prior rule")

        # oracle-specific
        if kind == "oracle":
            rf = r.get("fuel", 0)
            if rf <= 0:
                errors.append(f"{tag}: oracle rule has no fuel")
            oracle_fuel += rf
            if not r.get("prompt"):
                errors.append(f"{tag}: oracle rule has no prompt")

    # target
    target = plan.get("target")
    if target:
        if target not in names:
            errors.append(f"target '{target}' does not match any rule name")
    else:
        errors.append("plan has no target (must name the terminal rule)")

    # fuel budget
    if fuel and oracle_fuel > fuel:
        errors.append(
            f"total oracle fuel ({oracle_fuel}) exceeds build fuel ({fuel})")

    return errors


# ── Pretty-print ─────────────────────────────────────────────

def show(plan):
    """Print a human-readable summary of the plan."""
    name = plan.get("name", "?")
    fuel = plan.get("fuel", "?")
    target = plan.get("target", "?")
    rules = plan.get("rules", [])

    print(f"\n  plan: {name}  (fuel {fuel})  target: {target}")
    print(f"  {'─' * 50}")

    for r in rules:
        kind = r.get("kind", "?")
        rname = r.get("name", "?")
        inputs = r.get("inputs", [])
        outputs = r.get("outputs", [])
        is_target = rname == target
        marker = "▸" if kind == "oracle" else "●"
        fuel_tag = f"  fuel {r['fuel']}" if kind == "oracle" else ""
        target_tag = "  ◀ target" if is_target else ""
        print(f"  {marker} {rname}  ({kind}{fuel_tag}){target_tag}")
        if inputs:
            print(f"    in:  {', '.join(inputs)}")
        if outputs:
            print(f"    out: {', '.join(outputs)}")
        if kind == "action" and r.get("run"):
            print(f"    run: {r['run']}")

    print(f"  {'─' * 50}\n")


# ── Compiler ─────────────────────────────────────────────────

def compile(plan):
    """Lower Plan IR → arguments for husks.build.build().

    Returns (name, fuel, terminal_node, kwargs) ready for:
        build(name, fuel, terminal_node, **kwargs)
    """
    import hy  # noqa: F401
    from husks.build import rule, action, oracle

    rules = plan.get("rules", [])
    target = plan.get("target", rules[-1]["name"] if rules else None)
    name_to_node = {}
    name_to_ir = {r["name"]: r for r in rules}

    for r in rules:
        rname = r["name"]
        kind = r["kind"]
        inputs = r.get("inputs", [])
        outputs = r.get("outputs", [])

        # resolve children: any rule whose outputs are in our inputs
        children = []
        for inp in inputs:
            for prev_name, prev_node in name_to_node.items():
                prev_outputs = prev_node.get("outputs", [])
                if inp in prev_outputs and prev_node not in children:
                    children.append(prev_node)

        if kind == "action":
            # check for shell command
            run_cmd = r.get("run")
            if run_cmd:
                recipe = action(_make_shell_action(run_cmd, outputs))
            elif r.get("action_fn") and callable(r["action_fn"]):
                recipe = action(r["action_fn"])
            else:
                # default action: touch outputs (for terminal/gate nodes)
                recipe = action(_make_touch_action(outputs))
        elif kind == "oracle":
            recipe = oracle(
                prompt=r.get("prompt", ""),
                tools=r.get("tools", ["read-file", "write-file", "list-dir", "tree"]),
                fuel=r.get("fuel", 8),
            )

        node = rule(rname, *children,
                    inputs=inputs, outputs=outputs, recipe=recipe)
        name_to_node[rname] = node

    # terminal node is the target
    terminal = name_to_node[target]

    kwargs = {}
    if plan.get("site"):
        kwargs["site"] = plan["site"]
    if plan.get("oracle_backend"):
        kwargs["oracle_backend"] = plan["oracle_backend"]
    if plan.get("oracle_model"):
        kwargs["oracle_model"] = plan["oracle_model"]

    return plan["name"], plan["fuel"], terminal, kwargs


def _make_shell_action(cmd, outputs):
    """Create an action function that runs a shell command."""
    def shell_action(S):
        site = S["site"]
        result = subprocess.run(
            cmd, shell=True, cwd=site,
            capture_output=True, text=True, timeout=120,
        )
        from husks.build import site_path, write_text
        # capture output to first declared output if it doesn't exist yet
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
    return shell_action


def _make_touch_action(outputs):
    """Create an action that touches declared outputs (for gate nodes)."""
    def touch_action(S):
        from husks.build import site_path, write_text
        for o in outputs:
            p = Path(site_path(S, o))
            if not p.exists():
                p.parent.mkdir(parents=True, exist_ok=True)
                write_text(site_path(S, o), "ok\n")
    return touch_action


# ── Run ──────────────────────────────────────────────────────

def run(plan, **overrides):
    """Check, compile, and execute a plan. Returns the store."""
    errs = check(plan)
    if errs:
        raise ValueError("plan check failed:\n  " + "\n  ".join(errs))

    import hy  # noqa: F401
    from husks.build import build

    name, fuel, terminal, kwargs = compile(plan)
    kwargs.update(overrides)
    return build(name, fuel, terminal, **kwargs)


# ── Load/save ────────────────────────────────────────────────

def from_json(path):
    """Load a plan from a JSON file."""
    with open(path) as f:
        return json.load(f)


def to_json(plan, path=None):
    """Serialize a plan to JSON. If path given, write to file."""
    s = json.dumps(plan, indent=2)
    if path:
        with open(path, "w") as f:
            f.write(s)
    return s
