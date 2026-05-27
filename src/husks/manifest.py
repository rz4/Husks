"""
manifest.py -- Manifest reader utilities for Husks CLI commands.

Provides functions to read build manifests, seals, and trial reports
from a site's .traces/ directory, and to compute freshness states for
rules and artifacts.

Consumed by cli.py for the status, diff, and explain commands.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


def read_manifest(site: str) -> dict | None:
    """Read .traces/build.manifest.json from a site directory."""
    p = Path(site) / ".traces" / "build.manifest.json"
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text())
    except Exception:
        return None


def read_seal(site: str, rule_name: str) -> dict | None:
    """Read .traces/{rule_name}.seal from a site directory."""
    p = Path(site) / ".traces" / f"{rule_name}.seal"
    if not p.exists():
        return None
    try:
        data = json.loads(p.read_text())
        if not data.get("v"):
            return None
        return data
    except Exception:
        return None


def read_trial_report(site: str, rule_name: str) -> dict | None:
    """Read .traces/{rule_name}.trial.json from a site directory."""
    p = Path(site) / ".traces" / f"{rule_name}.trial.json"
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text())
    except Exception:
        return None


def file_hash(path: str) -> str | None:
    """SHA-256 hex of file contents, or None if the file is missing."""
    p = Path(path)
    if not p.is_file():
        return None
    return hashlib.sha256(p.read_bytes()).hexdigest()


def compute_rule_state(
    site: str, rule: dict, seal: dict | None
) -> tuple[str, str | None]:
    """Compute the freshness state for a rule.

    Returns (state, reason) where state is one of:
      fresh, stale, missing, dirty, failed, unknown
    and reason is a machine-readable explanation or None.
    """
    outputs = rule.get("outputs", [])

    # Check if any output is missing
    for o in outputs:
        p = Path(site) / o
        if not p.exists():
            return ("missing", f"output_missing:{o}")

    # No seal => never built
    if seal is None:
        return ("stale", "no_seal")

    # Check input hashes
    prior_inputs = seal.get("inputs", {})
    for inp, sealed_hash in prior_inputs.items():
        cur = file_hash(str(Path(site) / inp))
        cur_str = cur if cur is not None else "absent"
        if cur_str != sealed_hash:
            return ("stale", f"input_changed:{inp}")

    # Check recipe digest (we can't recompute it without the recipe,
    # but we can detect output tampering)
    prior_outputs = seal.get("outputs", {})
    for o in outputs:
        cur = file_hash(str(Path(site) / o))
        cur_str = cur if cur is not None else "absent"
        sealed = prior_outputs.get(o, "")
        if cur_str != sealed:
            return ("dirty", f"output_hash_changed:{o}")

    return ("fresh", None)


def compute_artifact_states(
    site: str, manifest: dict
) -> list[dict[str, Any]]:
    """For each declared artifact in the manifest, compute its state.

    Returns a list of dicts with keys: path, rule, state, sealed_hash, current_hash.
    State is one of: fresh, modified, missing.
    """
    results: list[dict[str, Any]] = []
    for rule in manifest.get("rules", []):
        rule_name = rule["name"]
        seal = read_seal(site, rule_name)
        prior_outputs = seal.get("outputs", {}) if seal else {}

        for o in rule.get("outputs", []):
            cur = file_hash(str(Path(site) / o))
            sealed = prior_outputs.get(o)

            if cur is None:
                state = "missing"
            elif sealed is None:
                state = "modified"
            elif cur != sealed:
                state = "modified"
            else:
                state = "fresh"

            results.append({
                "path": o,
                "rule": rule_name,
                "state": state,
                "sealed_hash": sealed,
                "current_hash": cur,
            })
    return results


def compute_rule_states(
    site: str, manifest: dict
) -> list[dict[str, Any]]:
    """Compute freshness state for every rule in a manifest.

    Returns a list of dicts with keys: name, kind, state, reason.
    """
    result: list[dict[str, Any]] = []
    for rule in manifest.get("rules", []):
        seal = read_seal(site, rule["name"])
        state, reason = compute_rule_state(site, rule, seal)
        result.append({
            "name": rule["name"],
            "kind": rule["kind"],
            "state": state,
            "reason": reason,
        })
    return result


def resolve_manifest(
    design_path: str | None, site_flag: str | None
) -> tuple[dict | None, str | None]:
    """Resolve manifest and site directory from CLI args.

    Tries, in order:
    1. --site flag directly
    2. Design file's "site" key
    3. Manifest from the resolved site

    Returns (manifest, site) — either or both may be None.
    """
    site = site_flag

    if design_path and not site:
        try:
            with open(design_path) as f:
                design = json.load(f)
            site = design.get("site")
        except Exception:
            pass

    if not site:
        return None, None

    manifest = read_manifest(site)
    return manifest, site
