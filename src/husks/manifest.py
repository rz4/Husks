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

# Beta Gate C2: Manifest and seal schema validation
SUPPORTED_MANIFEST_SCHEMAS = {"husks.build.manifest.v1"}
SUPPORTED_SEAL_VERSIONS = {1}


def _validate_manifest(data: dict) -> tuple[bool, str | None]:
    """Validate manifest schema and required fields.

    Beta Gate C2: Strict validation of manifest structure.

    Returns:
        (valid, error_msg) where valid is True if manifest is valid,
        and error_msg describes the problem if invalid.
    """
    # Check schema field
    schema = data.get("schema")
    if schema is None:
        return (False, "missing required field: schema")
    if schema not in SUPPORTED_MANIFEST_SCHEMAS:
        return (False, f"unsupported manifest schema: {schema}")

    # Check required fields for v1 manifest
    required = ["name", "root", "site", "run_id", "rules"]
    for field in required:
        if field not in data:
            return (False, f"missing required field: {field}")

    # Validate rules is a list
    if not isinstance(data["rules"], list):
        return (False, "field 'rules' must be a list")

    return (True, None)


def read_manifest(site: str) -> dict | None:
    """Read .traces/build.manifest.json from a site directory.

    Beta Gate C2: Returns None for missing, corrupt, or unsupported manifests.
    """
    p = Path(site) / ".traces" / "build.manifest.json"
    if not p.exists():
        return None
    try:
        data = json.loads(p.read_text())
        valid, error_msg = _validate_manifest(data)
        if not valid:
            # Log validation error but return None for backward compatibility
            # Callers should check for None to detect invalid manifests
            return None
        return data
    except Exception:
        return None


def _validate_seal(data: dict) -> tuple[bool, str | None]:
    """Validate seal version and required fields.

    Beta Gate C2: Strict validation of seal structure.

    Returns:
        (valid, error_msg) where valid is True if seal is valid,
        and error_msg describes the problem if invalid.
    """
    # Check version field
    version = data.get("v")
    if version is None:
        return (False, "missing required field: v")
    if not isinstance(version, int):
        return (False, "field 'v' must be an integer")
    if version not in SUPPORTED_SEAL_VERSIONS:
        return (False, f"unsupported seal version: {version}")

    # Check required fields for seal format v1
    # (v1 refers to seal format version, independent of CSE wire version)
    required = ["seal", "recipe_digest", "inputs"]
    for field in required:
        if field not in data:
            return (False, f"missing required field: {field}")

    # Validate inputs is a dict
    if not isinstance(data["inputs"], dict):
        return (False, "field 'inputs' must be a dict")

    # Validate outputs if present
    if "outputs" in data and not isinstance(data["outputs"], dict):
        return (False, "field 'outputs' must be a dict")

    return (True, None)


def read_seal(site: str, rule_name: str) -> dict | None:
    """Read .traces/{rule_name}.seal from a site directory.

    Beta Gate C2: Returns None for missing, corrupt, or unsupported seals.
    """
    p = Path(site) / ".traces" / f"{rule_name}.seal"
    if not p.exists():
        return None
    try:
        data = json.loads(p.read_text())
        valid, error_msg = _validate_seal(data)
        if not valid:
            # Log validation error but return None for backward compatibility
            # Callers should check for None to detect invalid seals
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


def compare_artifacts(
    site_a: str,
    site_b: str,
    *,
    check_roots: bool = True,
    check_hashes: bool = True,
) -> dict[str, Any]:
    """Compare two build sites for equivalence (Beta Gate C6).

    Compares build roots, output hashes, and seal validity to determine
    if two sites produced equivalent artifacts. Used for cross-machine
    verification in the three-machine beta test.

    Parameters
    ----------
    site_a : str
        Path to first site directory
    site_b : str
        Path to second site directory
    check_roots : bool
        If True, compare build roots (default True)
    check_hashes : bool
        If True, compare output content hashes (default True)

    Returns
    -------
    dict
        Comparison result with keys:
        - equivalent: bool - True if sites are equivalent
        - differences: list of str - descriptions of differences found
        - details: dict - detailed comparison data

    Examples
    --------
    >>> result = compare_artifacts("/tmp/site1", "/tmp/site2")
    >>> if result["equivalent"]:
    ...     print("Sites are equivalent!")
    >>> else:
    ...     for diff in result["differences"]:
    ...         print(f"Difference: {diff}")
    """
    from husks.core import recompute_root

    differences = []
    details = {}

    # Read manifests
    manifest_a = read_manifest(site_a)
    manifest_b = read_manifest(site_b)

    if manifest_a is None:
        differences.append(f"site A missing manifest: {site_a}")
    if manifest_b is None:
        differences.append(f"site B missing manifest: {site_b}")

    if manifest_a is None or manifest_b is None:
        return {
            "equivalent": False,
            "differences": differences,
            "details": {},
        }

    # Compare build roots
    if check_roots:
        root_a = manifest_a.get("root")
        root_b = manifest_b.get("root")
        details["root_a"] = root_a
        details["root_b"] = root_b

        if root_a != root_b:
            differences.append(f"build roots differ: {root_a[:16]}... vs {root_b[:16]}...")

        # Verify roots against .husk files
        build_name_a = manifest_a.get("name")
        build_name_b = manifest_b.get("name")

        if build_name_a and root_a:
            husk_path_a = Path(site_a) / f"{build_name_a}.husk"
            if husk_path_a.exists():
                try:
                    recomputed_a = recompute_root(husk_path_a.read_bytes(), site_a)
                    details["root_a_valid"] = (recomputed_a == root_a)
                    if recomputed_a != root_a:
                        differences.append(f"site A root invalid (recomputed {recomputed_a[:16]}...)")
                except Exception as e:
                    details["root_a_valid"] = False
                    differences.append(f"site A root verification failed: {e}")

        if build_name_b and root_b:
            husk_path_b = Path(site_b) / f"{build_name_b}.husk"
            if husk_path_b.exists():
                try:
                    recomputed_b = recompute_root(husk_path_b.read_bytes(), site_b)
                    details["root_b_valid"] = (recomputed_b == root_b)
                    if recomputed_b != root_b:
                        differences.append(f"site B root invalid (recomputed {recomputed_b[:16]}...)")
                except Exception as e:
                    details["root_b_valid"] = False
                    differences.append(f"site B root verification failed: {e}")

    # Compare output hashes
    if check_hashes:
        outputs_a = {}
        outputs_b = {}

        for rule in manifest_a.get("rules", []):
            rule_name = rule["name"]
            seal = read_seal(site_a, rule_name)
            if seal and "outputs" in seal:
                outputs_a.update(seal["outputs"])

        for rule in manifest_b.get("rules", []):
            rule_name = rule["name"]
            seal = read_seal(site_b, rule_name)
            if seal and "outputs" in seal:
                outputs_b.update(seal["outputs"])

        details["outputs_a"] = outputs_a
        details["outputs_b"] = outputs_b

        # Find differences in output hashes
        all_outputs = set(outputs_a.keys()) | set(outputs_b.keys())
        for output in sorted(all_outputs):
            hash_a = outputs_a.get(output)
            hash_b = outputs_b.get(output)

            if hash_a != hash_b:
                differences.append(
                    f"output '{output}' differs: "
                    f"{hash_a[:16] if hash_a else 'missing'}... vs "
                    f"{hash_b[:16] if hash_b else 'missing'}..."
                )

    return {
        "equivalent": len(differences) == 0,
        "differences": differences,
        "details": details,
    }


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
