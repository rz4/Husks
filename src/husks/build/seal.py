"""Seal I/O, freshness, history, trial reports, and build manifest."""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any, Callable

from husks.core import atom, CSE_VERSION, compute_seal, recipe_digest
from husks.utils import trace as T

from husks.build.site import (
    Store, Node, Recipe,
    site_path, ensure_dir, read_text, write_text, file_exists, file_sig,
)
from husks.build.identity import recipe_to_cse


# ── Seal I/O ──────────────────────────────────────────────────────

def compute_cse_seal(S: Store, inputs: list[str], recipe: Recipe) -> str:
    """Compute the CSE-based seal hash for a rule.  Returns hex string."""
    recipe_form = recipe_to_cse(recipe)
    bindings: list[tuple[bytes, bytes]] = [
        (atom(i), file_sig(site_path(S, i))) for i in inputs
    ]
    return compute_seal(CSE_VERSION, recipe_form, bindings)


def seal_file(S: Store, rule_name: str) -> str:
    """Path to the seal file for *rule_name*."""
    return site_path(S, f".traces/{rule_name}.seal")


def read_seal(S: Store, rule_name: str) -> dict | None:
    """Read the stored seal (v1 JSON).

    Returns None if absent, corrupt, or missing the version field.
    """
    sp = seal_file(S, rule_name)
    if not file_exists(sp):
        return None
    try:
        data = json.loads(read_text(sp))
        if not data.get("v"):
            return None
        return data
    except Exception:
        return None


def output_hashes(S: Store, outputs: list[str]) -> list[str]:
    """Compute content hashes of declared outputs as hex strings."""
    return [file_sig(site_path(S, o)).decode() for o in outputs]


# ── Freshness ─────────────────────────────────────────────────────

def freshness_check(
    S: Store,
    rule_name: str,
    inputs: list[str],
    outputs: list[str],
    recipe: Recipe,
) -> str | None:
    """Determine whether a rule is sealed (fresh) or stale.

    Returns None if the rule is sealed and its outputs can be reused.
    Returns a human-readable reason string if the rule is stale and
    must be re-evaluated.

    Freshness is determined by comparing the current seal (computed from
    the recipe and input bindings) against the prior seal. The seal is the
    canonical representation of a rule's dependencies - if seals match,
    nothing changed; if different, we diagnose why for better messages.

    Staleness hierarchy (checked in order):
      1. Any declared output file is missing.
      2. No prior seal exists (first build, or corrupt seal file).
      3. The current seal differs from the prior seal (dependencies changed).
      4. Output files were tampered with (content hash mismatch).
    """
    # Missing outputs
    for o in outputs:
        if not file_exists(site_path(S, o)):
            return f"{o} missing"

    # No prior seal
    prior = read_seal(S, rule_name)
    if prior is None:
        return "no prior build"

    # Compute current seal and compare to prior seal
    # The seal is the authoritative representation of dependencies:
    # seal = hash(recipe_digest + input_bindings)
    current_seal = compute_cse_seal(S, inputs, recipe)
    prior_seal = prior.get("seal", "")

    if current_seal != prior_seal:
        # Dependencies changed - diagnose why for a helpful error message
        return _diagnose_staleness(S, inputs, recipe, prior)

    # Output hash comparison (tamper detection)
    if "outputs" not in prior:
        return "seal missing output hashes"
    prior_outputs: dict[str, str] = prior["outputs"]
    for o in sorted(outputs):
        cur_hash = file_sig(site_path(S, o)).decode()
        old_hash = prior_outputs.get(o, "")
        if cur_hash != old_hash:
            return f"{o} tampered"

    return None


def _diagnose_staleness(
    S: Store,
    inputs: list[str],
    recipe: Recipe,
    prior: dict,
) -> str:
    """Diagnose why a seal changed, returning a specific error message.

    Called when current_seal != prior_seal. Checks recipe and input bindings
    to determine what changed, providing actionable error messages.
    """
    # Check recipe first (common cause of staleness)
    recipe_form = recipe_to_cse(recipe)
    cur_rd = recipe_digest(recipe_form)
    if cur_rd != prior.get("recipe_digest", ""):
        return "recipe changed"

    # Check input set changes
    prior_inputs: dict[str, str] = prior.get("inputs", {})
    current_input_set = set(inputs)
    prior_input_set = set(prior_inputs.keys())

    # Removed inputs (present in prior but not current)
    removed = prior_input_set - current_input_set
    if removed:
        return f"{sorted(removed)[0]} removed"

    # Added inputs (present in current but not prior)
    added = current_input_set - prior_input_set
    if added:
        return f"{sorted(added)[0]} changed"

    # Input content changes (hash mismatch)
    for i in sorted(inputs):
        cur_hash = file_sig(site_path(S, i)).decode()
        old_hash = prior_inputs.get(i, "")
        if cur_hash != old_hash:
            return f"{i} changed"

    # Seal changed but we can't determine why (shouldn't normally happen)
    # This could occur if CSE_VERSION changed or seal computation logic changed
    return "dependencies changed"


def write_seal(
    S: Store,
    rule_name: str,
    inputs: list[str],
    recipe: Recipe,
    outputs: list[str] | None = None,
) -> None:
    """Write the v1 seal: CSE seal + recipe digest + per-input/output hashes."""
    seal = compute_cse_seal(S, inputs, recipe)
    recipe_form = recipe_to_cse(recipe)
    rd = recipe_digest(recipe_form)
    input_sigs = {
        i: file_sig(site_path(S, i)).decode() for i in sorted(inputs)
    }
    seal_data: dict[str, Any] = {
        "v": 1, "seal": seal, "recipe_digest": rd, "inputs": input_sigs,
    }
    if outputs is not None:
        seal_data["outputs"] = {
            o: file_sig(site_path(S, o)).decode() for o in sorted(outputs)
        }
    write_text(
        seal_file(S, rule_name),
        json.dumps(seal_data, indent=2),
    )


# ── Convergence history ───────────────────────────────────────────

def history_file(S: Store, rule_name: str) -> str:
    """Path to the JSONL history log for *rule_name*."""
    return site_path(S, f".traces/{rule_name}.history.jsonl")


def append_history(
    S: Store,
    rule_name: str,
    recipe: Recipe,
    outputs: list[str],
    *,
    fuel_consumed: int = 1,
    satisfaction: bool | None = None,
    cost_usd: float | None = None,
    recipe_digest_hex: str | None = None,
) -> None:
    """Append one convergence record to the rule's history log."""
    prompt_length: int | None = None
    if recipe and recipe.get("type") == "oracle":
        prompt_length = len(recipe.get("prompt", ""))

    # Collect traced reads for this rule from the global trace state.
    traced_reads: list[str] = [
        e[4]["path"] if (isinstance(e[4], dict) and "path" in e[4]) else e[2]
        for e in T._tool_events
        if e[1] == "read-file" and e[0] == rule_name
    ]

    record = {
        "run_id": S["run-id"],
        "ts": time.time(),
        "fuel_consumed": fuel_consumed,
        "prompt_length": prompt_length,
        "satisfaction": satisfaction,
        "traced_reads": traced_reads,
        "output_hashes": output_hashes(S, outputs),
        "cost_usd": cost_usd,
        "recipe_digest": recipe_digest_hex,
    }
    hp = history_file(S, rule_name)
    ensure_dir(str(Path(hp).parent))
    with open(hp, "a") as f:
        f.write(json.dumps(record, default=str) + "\n")


# ── Trial report ──────────────────────────────────────────────────

def write_trial_report(
    S: Store,
    rule_name: str,
    winner_name: str,
    results: list[dict[str, Any]],
    scores: dict[str, float] | None,
    branches_ir: list[dict[str, Any]],
    outputs: list[str],
) -> None:
    """Write .traces/{rule_name}.trial.json after a trial verdict."""
    branch_entries: list[dict[str, Any]] = []
    branch_by_name = {b.get("name", ""): b for b in branches_ir}
    for r in results:
        bname = r["name"]
        br = branch_by_name.get(bname, {})
        kind = br.get("type", "oracle")
        has_error = "error" in r
        entry: dict[str, Any] = {
            "name": bname,
            "kind": kind,
            "selected": bname == winner_name,
            "elapsed_ms": round(r.get("elapsed", 0.0) * 1000, 1),
            "cost_usd": r.get("cost_usd", 0.0) if not has_error else None,
            "outputs": {
                o: hashlib.sha256(r["outputs"][o].encode()).hexdigest()
                for o in outputs if o in r.get("outputs", {})
            },
        }
        if scores and bname in scores:
            entry["score"] = scores[bname]
        if has_error:
            entry["error"] = r["error"]
        branch_entries.append(entry)

    report = {
        "schema": "husks.trial.v1",
        "rule": rule_name,
        "run_id": S["run-id"],
        "winner": winner_name,
        "branches": branch_entries,
    }
    write_text(
        site_path(S, f".traces/{rule_name}.trial.json"),
        json.dumps(report, indent=2),
    )


# ── Build manifest ────────────────────────────────────────────────

def _collect_rules(node: Node, seen: set[str] | None = None) -> list[dict[str, Any]]:
    """Walk a node tree and collect rule info for the build manifest."""
    if seen is None:
        seen = set()
    results: list[dict[str, Any]] = []
    ntype = node.get("type", "")
    if ntype == "rule":
        name = node["name"]
        if name not in seen:
            seen.add(name)
            recipe = node.get("recipe")
            kind = recipe["type"] if recipe else "action"
            results.append({
                "name": name,
                "kind": kind,
                "inputs": node.get("inputs", []),
                "outputs": node.get("outputs", []),
            })
        for child in node.get("children", []):
            results.extend(_collect_rules(child, seen))
    elif ntype == "cond":
        results.extend(_collect_rules(node["then"], seen))
        results.extend(_collect_rules(node["else"], seen))
    return results


def write_build_manifest(
    S: Store,
    name: str,
    nodes: tuple[Node, ...],
    *,
    design_source: str | None = None,
    design_kind: str | None = None,
) -> None:
    """Write .traces/build.manifest.json after a successful build."""
    seen: set[str] = set()
    rules: list[dict[str, Any]] = []
    for node in nodes:
        rules.extend(_collect_rules(node, seen))

    manifest = {
        "schema": "husks.build.manifest.v1",
        "name": name,
        "root": S.get("build-root"),
        "site": S["site"],
        "run_id": S["run-id"],
        "rules": rules,
    }
    if design_source:
        manifest["design_source"] = design_source
    if design_kind:
        manifest["design_kind"] = design_kind

    write_text(
        site_path(S, ".traces/build.manifest.json"),
        json.dumps(manifest, indent=2),
    )
