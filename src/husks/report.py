"""
report.py -- Serializable Report object for Husks builds.

The Report consolidates all build state into a single dict so that
the CLI, Claude Code, and future visual surfaces can render from one
source of truth.

Public API
----------
  assemble(store, trace, design) -> dict
      Build the Report dict from post-build state.

  render_text(report) -> str
      Structured text rendering (labels, tables).

  render_json(report) -> str
      JSON rendering (json.dumps with indent=2).
"""

from __future__ import annotations

import json
import time
from typing import Any

from husks.designs.convergence import convergence_summary, read_history
from husks.manifest import read_seal
from husks.utils.events import BuildTrace


def assemble(
    store: dict[str, Any],
    trace: BuildTrace,
    design: dict[str, Any],
) -> dict:
    """Build the Report dict from post-build state.

    Parameters
    ----------
    store : dict
        The final Store dict from build().
    trace : BuildTrace
        The module-level trace instance with accumulated events.
    design : dict
        The design IR dict.

    Returns
    -------
    dict
        The complete Report dict.
    """
    # Extract usage from Store (accumulated during build)
    usage = store.get("usage", {})
    site = store["site"]
    fuel_start = design.get("fuel", 0)
    elapsed = time.time() - trace._build_t0 if trace._build_t0 else 0.0

    # -- Build rule lookup from design --
    rules_by_name: dict[str, dict] = {}
    for r in design.get("rules", []):
        rules_by_name[r["name"]] = r

    # -- Node event lookup (name -> (name, state, elapsed)) --
    # _node_events stores tuples of (name, state_str, elapsed)
    # state_str is "fired", "reused", or "failed"
    node_state: dict[str, str] = {}
    for name, state, _el in trace._node_events:
        node_state[name] = state

    # Map trace states to report states
    _state_map = {"fired": "fired", "reused": "sealed", "failed": "failed"}

    # -- Collect rule_start events for stale_reason --
    stale_reasons: dict[str, str] = {}
    halt_reasons: dict[str, str] = {}
    for ev in trace._events:
        if ev.get("event") == "rule_start":
            r = ev.get("rule", "")
            sr = ev.get("stale_reason")
            if r and sr:
                stale_reasons[r] = sr
        elif ev.get("event") == "rule_halted":
            r = ev.get("rule", "")
            reason = ev.get("reason", "")
            if r and reason:
                halt_reasons[r] = reason

    # -- Per-rule cost from usage tracker --
    by_rule = usage.get("by_rule", {})

    # -- Build nodes list --
    nodes: list[dict] = []
    cost_reused = 0.0

    # Track which names appear in node_events (only those are in the Report)
    seen_names: set[str] = set()
    for name, raw_state, _el in trace._node_events:
        if name in seen_names:
            continue
        seen_names.add(name)

        state = _state_map.get(raw_state, raw_state)
        rule_ir = rules_by_name.get(name, {})
        kind = rule_ir.get("kind", "action")

        # Convergence
        cs = convergence_summary(name, site)
        classification = cs["classification"]
        fuel_trend = cs.get("fuel_trend")
        prompt_trend = cs.get("prompt_trend")

        # Prompt length (only for oracles)
        prompt_len: int | None = None
        if kind == "oracle":
            prompt_len = len(rule_ir.get("prompt", ""))

        # Fuel consumed from history
        history = read_history(site, name)
        fuel_consumed: int | None = None
        if history:
            fuel_consumed = history[-1].get("fuel_consumed")

        # Output hashes
        cur_hashes: list[str] = []
        if name in trace._artifacts:
            # Gather from artifacts keyed by output filename
            for o in rule_ir.get("outputs", []):
                art = trace._artifacts.get(o)
                if art:
                    cur_hashes.append(art["hash"])
        if not cur_hashes and history:
            cur_hashes = history[-1].get("output_hashes", [])

        # Output changed vs prior run
        output_changed = True
        if len(history) >= 2:
            prev_hashes = history[-2].get("output_hashes", [])
            output_changed = cur_hashes != prev_hashes
        elif state == "sealed":
            output_changed = False

        # Per-node cost (Beta Gate D6: include cached flag)
        rule_usage = by_rule.get(name, {})
        this_run_cost = rule_usage.get("cost_usd", 0.0) if state == "fired" and kind == "oracle" else 0.0
        cached = rule_usage.get("cached", False)
        tokens_in = rule_usage.get("input_tokens", 0)
        tokens_out = rule_usage.get("output_tokens", 0)
        first_paid: float | None = None
        per_rerun: float | None = None
        if history:
            first_paid = history[0].get("cost_usd")
            per_rerun = history[-1].get("cost_usd")

        # Sealed node cost for reused estimate
        if state == "sealed" and history:
            last_cost = history[-1].get("cost_usd")
            if last_cost is not None:
                cost_reused += last_cost

        # Seal info
        seal_info: dict[str, Any] | None = None
        seal_data = read_seal(site, name)
        if seal_data:
            seal_hash = seal_data.get("seal", "")
            cur_recipe_digest = seal_data.get("recipe_digest", "")
            recipe_changed = False
            if len(history) >= 2:
                prev_rd = history[-2].get("recipe_digest")
                if prev_rd is not None and cur_recipe_digest:
                    recipe_changed = cur_recipe_digest != prev_rd
            seal_info = {
                "hash": seal_hash,
                "recipe_changed": recipe_changed,
            }

        node_dict: dict[str, Any] = {
            "name": name,
            "kind": kind,
            "state": state,
            "classification": classification,
            "prompt_len": prompt_len,
            "prompt_trend": prompt_trend,
            "fuel_consumed": fuel_consumed,
            "fuel_trend": fuel_trend,
            "output_hashes": cur_hashes,
            "output_changed": output_changed,
            "cost": {
                "this_run": round(this_run_cost, 6),
                "first_paid": round(first_paid, 6) if first_paid is not None else None,
                "per_rerun": round(per_rerun, 6) if per_rerun is not None else None,
            },
            "cached": cached,  # Beta Gate D6
            "tokens": {  # Beta Gate D6: oracle usage details
                "input": tokens_in,
                "output": tokens_out,
            },
            "seal": seal_info,
        }

        # Diagnosis: only when state == "failed"
        if state == "failed":
            node_dict["diagnosis"] = {
                "error": halt_reasons.get(name, ""),
                "stale_reason": stale_reasons.get(name, ""),
            }

        nodes.append(node_dict)

    # -- Cost --
    cost_paid = usage.get("total_cost_usd", 0.0)
    cost_projected = cost_paid + cost_reused

    # -- Delta --
    changed: list[str] = []
    new: list[str] = []
    unchanged: list[str] = []
    for nd in nodes:
        name = nd["name"]
        history = read_history(site, name)
        if len(history) < 2:
            if nd["state"] != "sealed" or len(history) == 0:
                new.append(name)
            else:
                unchanged.append(name)
        elif nd["output_changed"]:
            changed.append(name)
        else:
            unchanged.append(name)

    # Task 3 (New): Calculate oracle evidence for three-machine proof validation
    # Count oracle calls (nodes that fired in this run) and cache hits (cached nodes)
    oracle_calls = 0
    cache_hits = 0
    cached_node_names: list[str] = []

    for nd in nodes:
        if nd.get("kind") == "oracle":
            # Oracle fired in this run (paid cost)
            if nd.get("state") == "fired" and nd.get("cost", {}).get("this_run", 0) > 0:
                oracle_calls += 1
            # Oracle reused from cache (explicit cached=True flag)
            elif nd.get("cached") is True:
                cache_hits += 1
                cached_node_names.append(nd["name"])

    # -- Build-level diagnosis --
    report: dict[str, Any] = {
        "schema_version": "beta-1",  # Task 9: Stabilized beta report contract
        "status": store["status"],
        "root": store.get("build-root"),
        "run_id": store.get("run-id", ""),
        "build": design.get("name", ""),
        "site": site,
        "elapsed_s": round(elapsed, 3),
        "fuel": {
            "start": fuel_start,
            "end": store.get("fuel", 0),
        },
        "cost": {
            "paid": round(cost_paid, 6),
            # Task 7 (New): Renamed to clarify these are non-authoritative estimates
            "reused_estimate": round(cost_reused, 6),
            "projected_estimate": round(cost_projected, 6),
        },
        "delta": {
            "changed": changed,
            "new": new,
            "unchanged": unchanged,
        },
        "nodes": nodes,
        # Task 3 (New): Include oracle evidence for three-machine proof validation
        "oracle_calls": oracle_calls,
        "cache_hits": cache_hits,
        "cached_nodes": cached_node_names,
    }

    if store["status"] == "halted":
        failed_nodes = [nd["name"] for nd in nodes if nd["state"] == "failed"]
        report["diagnosis"] = {
            "error": store.get("value", ""),
            "failed_nodes": failed_nodes,
        }

    return report


def render_text(report: dict) -> str:
    """Render the Report as structured text (labels, tables)."""
    lines: list[str] = []

    # Header (Task 9: Include schema version)
    root_str = report["root"] if report["root"] else "none"
    lines.append(f"schema:   {report.get('schema_version', 'unknown')}")
    lines.append(f"status:   {report['status']}")
    lines.append(f"root:     {root_str}")
    lines.append(f"run_id:   {report['run_id']}")
    lines.append(f"elapsed:  {report['elapsed_s']}s")
    lines.append(f"fuel:     {report['fuel']['end']} / {report['fuel']['start']}")

    cost = report["cost"]
    # Task 7 (New): Use renamed estimate fields
    reused = cost.get('reused_estimate', cost.get('reused', 0.0))  # Backward compat
    projected = cost.get('projected_estimate', cost.get('projected', 0.0))
    lines.append(
        f"cost:     ${cost['paid']:.4f} paid  "
        f"${reused:.4f} reused  "
        f"${projected:.4f} projected"
    )

    # Delta
    delta = report["delta"]
    lines.append(
        f"\ndelta:    {len(delta['changed'])} changed  "
        f"{len(delta['new'])} new  "
        f"{len(delta['unchanged'])} unchanged"
    )

    # Nodes table
    lines.append("")
    lines.append("nodes:")

    # Column headers
    hdr = f"  {'NAME':<20s} {'STATE':<9s} {'KIND':<9s} {'CLASS':<16s} {'COST':<10s} {'FUEL':<6s} {'PROMPT':<8s} {'OUTPUT'}"
    sep = f"  {'─' * 80}"
    lines.append(hdr)
    lines.append(sep)

    _trend_arrow = {"falling": "\u2193", "rising": "\u2191", "flat": ""}

    for nd in report["nodes"]:
        name = nd["name"]
        state = nd["state"]
        kind = nd["kind"]
        cls = nd["classification"]

        # Cost column
        if kind == "oracle" and state == "fired":
            cost_str = f"${nd['cost']['this_run']:.4f}"
        else:
            cost_str = "--"

        # Fuel column
        if nd["fuel_consumed"] is not None:
            arrow = _trend_arrow.get(nd.get("fuel_trend") or "", "")
            fuel_str = f"{nd['fuel_consumed']}{arrow}"
        else:
            fuel_str = "--"

        # Prompt column
        if nd["prompt_len"] is not None:
            arrow = _trend_arrow.get(nd.get("prompt_trend") or "", "")
            prompt_str = f"{nd['prompt_len']}{arrow}"
        else:
            prompt_str = "--"

        # Output column
        if state == "failed":
            out_str = "FAILED"
        elif nd["output_changed"]:
            out_str = "changed"
        else:
            out_str = "unchanged"

        lines.append(
            f"  {name:<20s} {state:<9s} {kind:<9s} {cls:<16s} "
            f"{cost_str:<10s} {fuel_str:<6s} {prompt_str:<8s} {out_str}"
        )

    lines.append(sep)

    # Build-level diagnosis
    if "diagnosis" in report:
        diag = report["diagnosis"]
        lines.append("")
        lines.append("diagnosis:")
        lines.append(f"  error:         {diag['error']}")
        lines.append(f"  failed_nodes:  {', '.join(diag['failed_nodes'])}")

    # Per-node diagnosis
    for nd in report["nodes"]:
        if "diagnosis" in nd:
            lines.append("")
            lines.append(f"  {nd['name']}:")
            lines.append(f"    error:         {nd['diagnosis']['error']}")
            if nd["diagnosis"].get("stale_reason"):
                lines.append(f"    stale_reason:  {nd['diagnosis']['stale_reason']}")

    return "\n".join(lines)


def render_concise(report: dict) -> str:
    """Render a concise one-line-per-rule summary of the build."""
    lines: list[str] = []

    _state_sym = {"fired": "\u2713", "sealed": "\u25cf", "failed": "\u2717"}

    for nd in report["nodes"]:
        sym = _state_sym.get(nd["state"], "?")
        name = nd["name"]
        kind = nd["kind"]
        cost_str = ""
        if kind == "oracle" and nd["state"] == "fired":
            cost_str = f"  ${nd['cost']['this_run']:.4f}"
        lines.append(f"  {sym} {name}  ({kind}){cost_str}")

    # Trial summaries from nodes (if any trial events exist in the trace)
    for ev in report.get("_trial_summaries", []):
        lines.append(f"  trial: {ev}")

    # Footer
    root = report.get("root", "none") or "none"
    root_short = root[:10] if root != "none" else "none"
    fuel = report["fuel"]
    cost = report["cost"]
    status = report["status"]
    lines.append(
        f"\n  {status}  root {root_short}  "
        f"fuel {fuel['end']}/{fuel['start']}  "
        f"${cost['paid']:.4f}"
    )
    return "\n".join(lines)


def render_json(report: dict) -> str:
    """Render the Report as pretty-printed JSON."""
    return json.dumps(report, indent=2)


def validate_report_schema(report: dict) -> tuple[bool, list[str]]:
    """Validate a Report dict against the beta contract (Beta Gate G3, Task 9).

    The beta report contract defines the expected structure for `husks run --json`
    output. This function checks that all required fields are present and have
    the expected types.

    Schema Version: beta-1 (Task 9: Stabilized)
    --------------------------------------------
    This is the first stabilized beta report contract. All reports must include
    schema_version="beta-1" for compatibility validation.

    Beta Report Schema
    ------------------
    - schema_version: str - "beta-1" (contract version identifier)
    - status: str - "committed" or "halted"
    - root: str | None - build root hash (or None if not committed)
    - run_id: str - unique run identifier
    - build: str - design name
    - site: str - site directory path
    - elapsed_s: float - build elapsed time in seconds
    - fuel: dict - fuel budget tracking
        - start: int - initial fuel
        - end: int - remaining fuel
    - cost: dict - oracle cost tracking (Beta Gate D6)
        - paid: float - cost paid in this run (authoritative)
        - reused_estimate: float - estimated cost saved from cache reuse (non-authoritative)
        - projected_estimate: float - estimated total cost if no cache (non-authoritative)

        NOTE (Task 7 - New): cost.reused_estimate and cost.projected_estimate are LOCAL
        ESTIMATES based on same-site history. For imported cache without cost provenance
        metadata, these will be 0. They are NOT part of seal identity and should not be
        used as authoritative proof of cache savings. Use cache_hits and cached_nodes fields
        for authoritative cache reuse evidence.
    - delta: dict - change summary
        - changed: list[str] - rules with changed outputs
        - new: list[str] - newly fired rules
        - unchanged: list[str] - rules with unchanged outputs
    - nodes: list[dict] - per-rule details
        - name: str - rule name
        - kind: str - "oracle", "trial", or "action"
        - state: str - "fired", "sealed", or "failed"
        - classification: str - convergence classification
        - prompt_len: int | None - prompt length for oracle rules
        - prompt_trend: str | None - prompt evolution trend
        - fuel_consumed: int | None - fuel used by this rule
        - fuel_trend: str | None - fuel evolution trend
        - output_hashes: list[str] - content hashes of outputs
        - output_changed: bool - whether outputs changed vs prior run
        - cost: dict - oracle cost for this node
            - this_run: float - cost paid in this run
            - first_paid: float | None - cost in first run
            - per_rerun: float | None - cost in most recent run
        - cached: bool - whether oracle output came from cache (Beta Gate D6)
        - tokens: dict - token usage (Beta Gate D6)
            - input: int - input tokens
            - output: int - output tokens
        - seal: dict | None - seal information
            - hash: str - seal hash
            - recipe_changed: bool - whether recipe changed vs prior run
        - diagnosis: dict | None - present only if state == "failed"
            - error: str - error message
            - stale_reason: str - why rule was stale
    - diagnosis: dict | None - present only if status == "halted"
        - error: str - build-level error message
        - failed_nodes: list[str] - names of failed rules

    Parameters
    ----------
    report : dict
        The Report dict to validate

    Returns
    -------
    tuple[bool, list[str]]
        (valid, errors) where valid is True if schema is valid,
        and errors is a list of validation error messages
    """
    errors = []

    # Top-level required fields (Task 9: Added schema_version)
    # Beta Hardening Task 1/3: Added oracle evidence fields
    required_top = {
        "schema_version": str,
        "status": str,
        "root": (str, type(None)),
        "run_id": str,
        "build": str,
        "site": str,
        "elapsed_s": (int, float),
        "fuel": dict,
        "cost": dict,
        "delta": dict,
        "nodes": list,
        # Beta Hardening Task 1: Require oracle evidence fields
        "oracle_calls": int,
        "cache_hits": int,
        "cached_nodes": list,
    }

    for field, expected_type in required_top.items():
        if field not in report:
            errors.append(f"missing required field: {field}")
        elif not isinstance(report.get(field), expected_type):
            errors.append(
                f"field '{field}' has wrong type: "
                f"expected {expected_type}, got {type(report.get(field))}"
            )

    # Task 9: Validate schema version is "beta-1"
    if "schema_version" in report:
        if report["schema_version"] != "beta-1":
            errors.append(
                f"unsupported schema_version: {report['schema_version']} "
                f"(expected 'beta-1')"
            )

    # Beta Hardening Task 2: Committed reports must have non-empty root
    if "status" in report and report["status"] == "committed":
        root = report.get("root")
        if not root or not isinstance(root, str) or len(root.strip()) == 0:
            errors.append("committed reports must have non-empty root string")

    # Validate fuel dict
    if "fuel" in report and isinstance(report["fuel"], dict):
        for field in ["start", "end"]:
            if field not in report["fuel"]:
                errors.append(f"fuel.{field} missing")
            elif not isinstance(report["fuel"][field], int):
                errors.append(f"fuel.{field} must be int")

    # Validate cost dict (Beta Gate D6, Task 7 - New)
    if "cost" in report and isinstance(report["cost"], dict):
        # Task 7 (New): Support both old and new field names for backward compatibility
        cost = report["cost"]

        # paid is always required
        if "paid" not in cost:
            errors.append("cost.paid missing")
        elif not isinstance(cost["paid"], (int, float)):
            errors.append("cost.paid must be numeric")

        # reused_estimate (or old 'reused') is required
        if "reused_estimate" not in cost and "reused" not in cost:
            errors.append("cost.reused_estimate (or cost.reused) missing")
        else:
            val = cost.get("reused_estimate", cost.get("reused"))
            if not isinstance(val, (int, float)):
                errors.append("cost.reused_estimate must be numeric")

        # projected_estimate (or old 'projected') is required
        if "projected_estimate" not in cost and "projected" not in cost:
            errors.append("cost.projected_estimate (or cost.projected) missing")
        else:
            val = cost.get("projected_estimate", cost.get("projected"))
            if not isinstance(val, (int, float)):
                errors.append("cost.projected_estimate must be numeric")

    # Validate delta dict
    if "delta" in report and isinstance(report["delta"], dict):
        for field in ["changed", "new", "unchanged"]:
            if field not in report["delta"]:
                errors.append(f"delta.{field} missing")
            elif not isinstance(report["delta"][field], list):
                errors.append(f"delta.{field} must be list")

    # Validate nodes list
    if "nodes" in report and isinstance(report["nodes"], list):
        for i, node in enumerate(report["nodes"]):
            if not isinstance(node, dict):
                errors.append(f"nodes[{i}] must be dict")
                continue

            # Node required fields
            node_required = {
                "name": str,
                "kind": str,
                "state": str,
                "classification": str,
                "prompt_len": (int, type(None)),
                "prompt_trend": (str, type(None)),
                "fuel_consumed": (int, type(None)),
                "fuel_trend": (str, type(None)),
                "output_hashes": list,
                "output_changed": bool,
                "cost": dict,
                "cached": bool,
                "tokens": dict,
                "seal": (dict, type(None)),
            }

            for field, expected_type in node_required.items():
                if field not in node:
                    errors.append(f"nodes[{i}].{field} missing")
                elif not isinstance(node.get(field), expected_type):
                    errors.append(
                        f"nodes[{i}].{field} has wrong type: "
                        f"expected {expected_type}, got {type(node.get(field))}"
                    )

            # Validate node.cost dict
            if "cost" in node and isinstance(node["cost"], dict):
                for field in ["this_run", "first_paid", "per_rerun"]:
                    if field not in node["cost"]:
                        errors.append(f"nodes[{i}].cost.{field} missing")

            # Validate node.tokens dict (Beta Gate D6)
            if "tokens" in node and isinstance(node["tokens"], dict):
                for field in ["input", "output"]:
                    if field not in node["tokens"]:
                        errors.append(f"nodes[{i}].tokens.{field} missing")

    # Validate diagnosis if halted
    if report.get("status") == "halted":
        if "diagnosis" not in report:
            errors.append("status is 'halted' but diagnosis is missing")
        elif isinstance(report["diagnosis"], dict):
            for field in ["error", "failed_nodes"]:
                if field not in report["diagnosis"]:
                    errors.append(f"diagnosis.{field} missing")

    return (len(errors) == 0, errors)
