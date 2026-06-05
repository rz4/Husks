"""
_show.py -- Pretty-printing for designs.

Provides the show function for human-readable design summaries.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ._validation import _resolve_targets

Design = dict[str, Any]


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
