"""Evaluation engine: eval_node, eval_rule, eval_recipe, oracle, trial, Merkle root."""

from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
import time
from pathlib import Path
from typing import Any, Callable

from husks.core import atom, CseValue, compute_node_digest, encode, recipe_digest
from husks.utils import trace as T

from husks.build.site import (
    Store, Node, Recipe, OracleBackend,
    Stop, site_path, write_text, file_exists, read_text,
    fresh_store, burn, file_sig,
)
from husks.build.identity import _pred_identity, recipe_to_cse, VERDICT_POLICIES
from husks.build.seal import (
    compute_cse_seal, output_hashes, freshness_check, write_seal,
    append_history, history_file, ensure_dir, write_trial_report,
)


# ── Output guard ──────────────────────────────────────────────────

def _check_declared_outputs(
    S: Store,
    rule_name: str,
    outputs: list[str],
    recipe: Recipe,
) -> None:
    """Guard: all declared outputs must exist; oracle outputs must be nonempty.

    Raises RuntimeError if the guard fails — preventing the rule from sealing.
    """
    require_nonempty = recipe is not None and recipe.get("type") == "oracle"
    for o in outputs:
        op = Path(site_path(S, o))
        if not op.exists():
            raise RuntimeError(
                f"rule '{rule_name}' did not produce declared output: {o}"
            )
        if require_nonempty and op.stat().st_size == 0:
            raise RuntimeError(
                f"oracle '{rule_name}' produced empty output: {o}"
            )


# ── Evaluator ─────────────────────────────────────────────────────

def eval_node(S: Store, node: Node) -> None:
    """Dispatch evaluation by node type."""
    kind: str = node["type"]
    if kind == "rule":
        eval_rule(S, node)
    elif kind == "cond":
        eval_cond(S, node)
    elif kind == "commit":
        S["status"] = "committed"
        S["value"] = node["value"]
        raise Stop("commit", node["value"])
    elif kind == "halt":
        S["status"] = "halted"
        S["value"] = node["reason"]
        raise Stop("halt", node["reason"])
    else:
        raise ValueError(f"unknown node type: {kind}")


def eval_cond(S: Store, node: Node) -> None:
    """Evaluate a conditional branch node.

    Calls the predicate with the current Store.  If True, evaluates
    the ``then`` branch; otherwise evaluates the ``else`` branch.
    Only one branch is ever evaluated.
    """
    predicate: Callable[[Store], bool] = node["predicate"]
    result = predicate(S)
    S["trace"].append({
        "event": "cond",
        "result": bool(result),
    })
    if result:
        eval_node(S, node["then"])
    else:
        eval_node(S, node["else"])


def eval_rule(S: Store, node: Node) -> None:
    """Evaluate a rule node: prerequisites, freshness, dispatch."""
    name: str = node["name"]
    inputs: list[str] = node["inputs"]
    outputs: list[str] = node["outputs"]
    recipe: Recipe = node["recipe"]

    # 1. Resolve prerequisites (with parent tracking for diamond annotations)
    T.push_rule(name)
    for child in node["children"]:
        eval_node(S, child)
    T.pop_rule()

    # 2. Freshness check
    reason = freshness_check(S, name, inputs, outputs, recipe)
    if reason is None:
        # Sealed -- reuse outputs
        S["trace"].append({"event": "sealed", "rule": name})
        T.rule_sealed(name, outputs=outputs, output_hashes=output_hashes(S, outputs))
        return

    # 3. Stale -- fire
    burn(S, name)
    T.rule_start(name, stale_reason=reason)
    try:
        usage = eval_recipe(S, name, recipe, inputs, outputs)

        # Output guard: all recipe types require declared outputs to exist.
        # Oracle outputs must additionally be nonempty.
        _check_declared_outputs(S, name, outputs, recipe)

        write_seal(S, name, inputs, recipe, outputs=outputs)

        fuel_consumed = 1
        if usage and usage.get("fuel_steps", 0):
            fuel_consumed = usage["fuel_steps"]

        # Compute recipe digest and extract cost for history record
        rd_hex: str | None = None
        if recipe is not None:
            rd_hex = recipe_digest(recipe_to_cse(recipe))
        cost: float | None = None
        if usage and "cost_usd" in usage:
            cost = usage["cost_usd"]

        append_history(S, name, recipe, outputs, fuel_consumed=fuel_consumed,
                       cost_usd=cost, recipe_digest_hex=rd_hex)
        S["trace"].append({"event": "fired", "rule": name, "outputs": outputs})
        T.rule_done(name, outputs=outputs, output_hashes=output_hashes(S, outputs))
    except Stop:
        raise
    except Exception as e:
        T.rule_halted(name, str(e))
        raise


def eval_recipe(
    S: Store,
    rule_name: str,
    recipe: Recipe,
    inputs: list[str],
    outputs: list[str],
) -> dict[str, Any] | None:
    """Evaluate a recipe.  Returns usage dict with fuel_steps, or None."""
    if recipe is None:
        return None
    kind: str = recipe["type"]
    if kind == "action":
        recipe["fn"](S, *recipe.get("args", ()))
        return None
    if kind == "oracle":
        return eval_oracle(S, rule_name, recipe, outputs)
    if kind == "trial":
        eval_trial(S, rule_name, recipe, outputs)
        return None
    raise ValueError(f"unknown recipe type: {kind}")


# ── Oracle evaluation ─────────────────────────────────────────────

def default_oracle_backend(
    S: Store,
    rule_name: str,
    recipe: dict[str, Any],
    outputs: list[str],
) -> dict[str, Any]:
    """Stub oracle backend that writes placeholder outputs."""
    for o in outputs:
        write_text(
            site_path(S, o),
            f"# oracle output: {rule_name}\n"
            f"# prompt: {recipe.get('prompt', '')}\n",
        )
    return {"tokens_in": 840, "tokens_out": 320, "cost_usd": 0.0008, "fuel_steps": 1}


def eval_oracle(
    S: Store,
    rule_name: str,
    recipe: dict[str, Any],
    outputs: list[str],
) -> dict[str, Any]:
    """Evaluate an oracle recipe.  Returns usage dict."""
    oname: str = recipe.get("name") or "oracle"
    T.oracle_start(rule_name, oname, recipe.get("prompt"))
    t0 = time.time()
    backend: OracleBackend = S.get("oracle-backend") or default_oracle_backend
    usage = backend(S, rule_name, recipe, outputs)
    elapsed = time.time() - t0
    u = usage or {}
    T.oracle_done(
        rule_name,
        oname,
        tokens_in=u.get("tokens_in", 0),
        tokens_out=u.get("tokens_out", 0),
        cost_usd=u.get("cost_usd", 0.0),
        elapsed=elapsed,
    )
    return u


# ── Trial evaluation ──────────────────────────────────────────────

def first_valid(results: list[dict[str, Any]]) -> dict[str, Any]:
    """Default verdict function: pick the first branch without an error."""
    valid = [r for r in results if "error" not in r]
    if not valid:
        raise ValueError("trial: all branches failed")
    if len(valid) > 1:
        rname = valid[0].get("name", "?")
        T.trial_note(
            rname,
            f"first-valid: chose {valid[0]['name']} among {len(valid)} viable branches",
        )
    scores = {r["name"]: r.get("score", 1.0) for r in valid}
    return {"winner": valid[0], "scores": scores}


# Populate the registry now that first_valid is defined.
VERDICT_POLICIES["first-valid"] = first_valid


def eval_trial(
    S: Store,
    rule_name: str,
    recipe: dict[str, Any],
    outputs: list[str],
) -> None:
    """Evaluate a trial recipe: fork, run branches, verdict, merge."""
    branches = recipe["branches"]
    verdict_fn = recipe.get("verdict") or first_valid
    if isinstance(verdict_fn, str):
        verdict_fn = VERDICT_POLICIES[verdict_fn]
    results: list[dict[str, Any]] = []

    for branch in branches:
        if S["fuel"] <= 0:
            break
        bname: str = branch.get("name") or f"branch-{len(results)}"

        # Charge 1 global fuel per branch fired
        burn(S, f"{rule_name}:{bname}")

        tmp = tempfile.mkdtemp(prefix=f"trial-{bname}-")
        t0 = time.time()
        try:
            shutil.copytree(S["site"], tmp, dirs_exist_ok=True)
            BS = fresh_store(tmp, S["fuel"], oracle_backend=S.get("oracle-backend"))

            # Fire branch
            eval_recipe(BS, bname, branch, [], outputs)
            branch_elapsed = time.time() - t0

            # Collect outputs
            out_data: dict[str, str] = {}
            for o in outputs:
                op = site_path(BS, o)
                if file_exists(op):
                    out_data[o] = read_text(op)

            # Collect oracle cost for this branch from trace state
            branch_cost = sum(
                e[4] for e in T._oracle_events if e[1] == bname
            )
            branch_toks_in = sum(
                e[2] for e in T._oracle_events if e[1] == bname
            )
            branch_toks_out = sum(
                e[3] for e in T._oracle_events if e[1] == bname
            )
            results.append({
                "name": bname,
                "outputs": out_data,
                "elapsed": branch_elapsed,
                "tokens_in": branch_toks_in,
                "tokens_out": branch_toks_out,
                "cost_usd": branch_cost,
            })
        except Exception as e:
            results.append({"name": bname, "error": str(e), "outputs": {}})
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    # Verdict (supports both legacy and dict protocol)
    vresult = verdict_fn(results)
    if isinstance(vresult, dict) and "winner" in vresult:
        winner = vresult["winner"]
        scores = vresult.get("scores")
    else:
        winner = vresult
        scores = None

    # Report branches with scores
    for r in results:
        rname = r["name"]
        score = scores.get(rname) if scores else None
        T.trial_branch(
            rule_name,
            rname,
            score=score,
            tokens_in=r.get("tokens_in", 0),
            tokens_out=r.get("tokens_out", 0),
            cost_usd=r.get("cost_usd", 0.0),
            elapsed=r.get("elapsed", 0.0),
        )

    wname: str = winner["name"]
    T.trial_verdict(rule_name, wname, scores=scores)

    # Record convergence history for each branch
    branch_by_name = {b.get("name", ""): b for b in branches}
    for r in results:
        rname = r["name"]
        is_winner = rname == wname
        has_error = "error" in r
        if is_winner:
            satisfaction: bool | None = True
        elif has_error:
            satisfaction = None
        else:
            satisfaction = False

        branch_recipe = branch_by_name.get(rname)
        prompt_length: int | None = None
        if branch_recipe and branch_recipe.get("type", "") == "oracle":
            prompt_length = len(branch_recipe.get("prompt", ""))

        # Compute recipe digest and extract cost for branch history
        branch_rd: str | None = None
        if branch_recipe is not None:
            branch_rd = recipe_digest(recipe_to_cse(branch_recipe))
        branch_cost_val: float | None = r.get("cost_usd") if not has_error else None

        record = {
            "run_id": S["run-id"],
            "ts": time.time(),
            "fuel_consumed": 1,
            "prompt_length": prompt_length,
            "satisfaction": satisfaction,
            "traced_reads": [],
            "output_hashes": [
                hashlib.sha256(r["outputs"][o].encode()).hexdigest()
                for o in outputs
                if o in r.get("outputs", {})
            ],
            "cost_usd": branch_cost_val,
            "recipe_digest": branch_rd,
        }
        hp = history_file(S, f"{rule_name}.{rname}")
        ensure_dir(str(Path(hp).parent))
        with open(hp, "a") as f:
            f.write(json.dumps(record, default=str) + "\n")

    # Copy winner outputs to site
    for o in outputs:
        if o in winner["outputs"]:
            write_text(site_path(S, o), winner["outputs"][o])

    # Write trial report
    write_trial_report(S, rule_name, wname, results, scores, branches, outputs)

    S["trace"].append({"event": "trial", "rule": rule_name, "winner": wname})


# ── CSE husk serialization + Merkle root ──────────────────────────

def node_to_cse(node: Node) -> CseValue:
    """Serialize an engine node tree to its CSE form."""
    ntype = node["type"]
    if ntype == "commit":
        return [b"commit", atom(node["value"])]
    if ntype == "halt":
        return [b"halt", atom(node["reason"])]
    if ntype == "cond":
        return [
            b"cond",
            atom(_pred_identity(node["predicate"])),
            node_to_cse(node["then"]),
            node_to_cse(node["else"]),
        ]
    # rule node
    recipe_form = recipe_to_cse(node["recipe"])
    inp_list: list[bytes] = [atom(i) for i in node["inputs"]]
    out_list: list[bytes] = [atom(o) for o in node["outputs"]]
    children: list[CseValue] = [node_to_cse(c) for c in node["children"]]
    return [b"rule", atom(node["name"]), recipe_form, inp_list, out_list] + children


def compute_build_root(S: Store, node: Node) -> str:
    """Walk the node tree depth-first, computing seals and digests bottom-up.

    Returns the hex digest string for this node (the build-root when
    called on the target node).
    """
    ntype = node["type"]

    # Terminal nodes: digest is just the hash of their CSE form
    if ntype in ("commit", "halt"):
        cse_form = node_to_cse(node)
        return hashlib.sha256(encode(cse_form)).hexdigest()

    if ntype == "cond":
        then_digest = compute_build_root(S, node["then"])
        else_digest = compute_build_root(S, node["else"])
        cse_form = [
            b"cond",
            atom(_pred_identity(node["predicate"])),
            atom(then_digest),
            atom(else_digest),
        ]
        return hashlib.sha256(encode(cse_form)).hexdigest()

    # Rule node
    # Recurse children
    child_digests: list[bytes] = [
        atom(compute_build_root(S, c)) for c in node["children"]
    ]
    # Input bindings
    inp_bindings: list[tuple[bytes, bytes]] = [
        (atom(i), file_sig(site_path(S, i))) for i in node["inputs"]
    ]
    # Seal
    seal = compute_cse_seal(S, node["inputs"], node["recipe"])
    # Output bindings
    out_bindings: list[tuple[bytes, bytes]] = [
        (atom(o), file_sig(site_path(S, o))) for o in node["outputs"]
    ]
    return compute_node_digest(atom(node["name"]), atom(seal), out_bindings, child_digests)
