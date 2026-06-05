"""
convergence.py -- Post-execution analysis of rule history.

Reads JSONL history logs from .traces/<rule>.history.jsonl and
classifies rule behavior: stable, converging, prompt-loading,
volatile, or no-data.  Self-contained (stdlib only).

See docs/architecture.md for classification definitions and history
record schema.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


# ── History I/O ───────────────────────────────────────────────────

def read_history(site: str, rule_name: str) -> list[dict[str, Any]]:
    """Read JSONL history entries for a rule.

    Returns a list of dicts, one per run, in chronological order.
    Returns an empty list if no history file exists.
    """
    p = Path(site) / ".traces" / f"{rule_name}.history.jsonl"
    if not p.exists():
        return []
    entries: list[dict[str, Any]] = []
    for line in p.read_text().strip().splitlines():
        if line.strip():
            entries.append(json.loads(line))
    return entries


# ── Trend analysis ────────────────────────────────────────────────

def _trend(values: list[int | float]) -> str:
    """Classify a numeric sequence as 'falling', 'rising', or 'flat'.

    A sequence is 'falling' if every successive difference is <= 0
    and at least one is < 0.  'Rising' if every difference is >= 0
    and at least one is > 0.  'Flat' otherwise (including mixed
    directions and single-element sequences).
    """
    if len(values) <= 1:
        return "flat"
    diffs = [values[i + 1] - values[i] for i in range(len(values) - 1)]
    if all(d <= 0 for d in diffs):
        if all(d == 0 for d in diffs):
            return "flat"
        return "falling"
    if all(d >= 0 for d in diffs):
        return "rising"
    return "flat"


# ── Convergence summary ──────────────────────────────────────────

def convergence_summary(
    rule_name: str,
    site: str,
    n: int = 5,
) -> dict[str, Any]:
    """Analyze the last *n* history entries for a rule.

    Returns a dict with:

      fuel_trend      str | None   -- "falling", "flat", "rising", or None
      prompt_trend    str | None   -- "falling", "flat", "rising", or None
      output_stable   bool | None  -- True if all output hashes identical
      classification  str          -- "stable", "converging",
                                      "prompt-loading", "volatile",
                                      or "no-data"
      entries         list[dict]   -- the raw history entries used
    """
    entries = read_history(site, rule_name)
    if not entries:
        return {
            "fuel_trend": None,
            "prompt_trend": None,
            "output_stable": None,
            "classification": "no-data",
            "entries": [],
        }

    recent = entries[-n:]

    # Fuel trend
    fuels = [e.get("fuel_consumed", 0) for e in recent]
    fuel_trend = _trend(fuels)

    # Prompt length trend
    prompts = [e.get("prompt_length") for e in recent]
    if all(p is None for p in prompts):
        prompt_trend: str | None = None
    else:
        prompt_trend = _trend([p or 0 for p in prompts])

    # Output stability
    hashes = [tuple(e.get("output_hashes", [])) for e in recent]
    output_stable = len(set(hashes)) <= 1 if hashes else False

    # Classification
    if output_stable and len(recent) > 1:
        classification = "stable"
    elif fuel_trend in ("falling", "flat") and prompt_trend in (
        "falling",
        "flat",
        None,
    ):
        classification = "converging"
    elif fuel_trend in ("falling", "flat") and prompt_trend == "rising":
        classification = "prompt-loading"
    else:
        classification = "volatile"

    return {
        "fuel_trend": fuel_trend,
        "prompt_trend": prompt_trend,
        "output_stable": output_stable,
        "classification": classification,
        "entries": recent,
    }


# ── Declared vs. traced inputs ────────────────────────────────────

def declared_vs_traced(
    design: dict[str, Any],
    site: str,
) -> dict[str, list[str]]:
    """Diff declared inputs against actual traced reads.

    For each rule, compares the ``inputs`` declared in the design against
    the ``traced_reads`` recorded in the most recent history entry.
    Returns a dict mapping rule names to lists of paths that were read
    by the oracle but not declared as inputs.

    An empty return dict means all reads were declared -- the design
    accurately captures the oracle's actual dependencies.

    Parameters
    ----------
    design : dict
        The design IR (as loaded by ir.from_json).
    site : str
        Path to the site directory containing ``.traces/``.

    Returns
    -------
    dict[str, list[str]]
        ``{rule_name: [undeclared_paths, ...]}`` for rules with
        undeclared reads.  Rules with no undeclared reads are omitted.
    """
    result: dict[str, list[str]] = {}
    for r in design.get("rules", []):
        rname: str = r["name"]
        declared = set(r.get("inputs", []))
        entries = read_history(site, rname)
        if not entries:
            continue
        latest = entries[-1]
        traced = set(latest.get("traced_reads", []))
        undeclared = sorted(traced - declared)
        if undeclared:
            result[rname] = undeclared
    return result
