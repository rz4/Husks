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

    # -- Build-level diagnosis --
    report: dict[str, Any] = {
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
            "reused": round(cost_reused, 6),
            "projected": round(cost_projected, 6),
        },
        "delta": {
            "changed": changed,
            "new": new,
            "unchanged": unchanged,
        },
        "nodes": nodes,
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

    # Header
    root_str = report["root"] if report["root"] else "none"
    lines.append(f"status:   {report['status']}")
    lines.append(f"root:     {root_str}")
    lines.append(f"run_id:   {report['run_id']}")
    lines.append(f"elapsed:  {report['elapsed_s']}s")
    lines.append(f"fuel:     {report['fuel']['end']} / {report['fuel']['start']}")

    cost = report["cost"]
    lines.append(
        f"cost:     ${cost['paid']:.4f} paid  "
        f"${cost['reused']:.4f} reused  "
        f"${cost['projected']:.4f} projected"
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
