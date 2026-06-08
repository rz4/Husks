"""L7 gamma -- Condensation orchestrator.

Runs the full condensation gate: design check → M1 fresh build →
cache export → M2 reuse-only → M3 independent fresh build →
three-machine proof with acceptance anchor → CONDENSE or REJECT.

Dependencies: locke (L5), report (L6), engine (L3), kernel (L0) + stdlib.
"""

from __future__ import annotations

import hashlib
import json
import tempfile
from pathlib import Path
from typing import Any


def _output_rule_map(design: dict) -> dict[str, dict]:
    """Map each output path to its producing rule dict."""
    out_to_rule: dict[str, dict] = {}
    for r in design.get("rules", []):
        for o in r.get("outputs", []):
            out_to_rule[o] = r
    return out_to_rule


def _resolve_verdict_predicate(spec, design: dict):
    """Resolve a verdict spec to a callable (Store) -> bool.

    Uses the same resolution as locke._resolve_predicate but avoids
    importing from locke at module level.
    """
    from husks.locke import _resolve_predicate
    predicates = design.get("predicates", {})
    return _resolve_predicate(spec, predicates)


def _eval_verdict_on_site(verdict_fn, site_dir: str) -> bool:
    """Evaluate a verdict predicate against a site directory."""
    S = {"site": site_dir}
    try:
        return bool(verdict_fn(S))
    except Exception:
        return False


def _reject(site, anchor, checks=None, errors=None):
    """Build a REJECT result dict."""
    return {
        "verdict": "REJECT",
        "site": site,
        "acceptance_anchor": anchor or {},
        "checks": checks or [],
        "errors": errors or [],
    }


def condense(
    design: dict,
    accepted_outputs: dict[str, str],
    *,
    site: str | None = None,
    oracle_backend=None,
    oracle_backend_name: str = "litellm",
    oracle_config: dict | None = None,
    stub: bool = False,
) -> dict:
    """Run the condensation gate on a design.

    Parameters
    ----------
    design : dict
        Parsed design IR (from locke.from_file or locke.from_json).
    accepted_outputs : dict[str, str]
        Mapping of output_path -> absolute file path of accepted output.
    site : str | None
        Base directory for machine sites.  Defaults to a tempdir.
    oracle_backend : callable | None
        Oracle backend function (e.g. run_oracle from husks.oracle).
    oracle_backend_name : str
        Name of the oracle backend.
    oracle_config : dict | None
        Oracle configuration dict.
    stub : bool
        If True, run in stub mode (no oracle backend).

    Returns
    -------
    dict with keys: verdict, site, acceptance_anchor, checks, errors.
    """
    from husks.locke import check, run as locke_run
    from husks.engine import cache_export, cache_import
    from husks.seal import fresh_store
    from husks.report import (
        build_site_residue, compare_artifacts, three_machine_checks,
    )
    from husks.forms import _pred_identity

    errors: list[str] = []

    # 1. Validate design (unsafe=True: condense gate itself validates oracle output)
    check_errors = check(design, unsafe=True)
    if check_errors:
        return _reject(None, {}, errors=[f"design check: {e}" for e in check_errors])

    # 2. Classify outputs by producing rule kind and build acceptance anchor
    out_to_rule = _output_rule_map(design)
    anchor: dict[str, Any] = {}
    oracle_verdicts: dict[str, Any] = {}  # out_path -> {"verdict": spec, "fn": callable}

    for out_path, file_path in accepted_outputs.items():
        p = Path(file_path)
        if not p.is_file():
            errors.append(f"accepted output not found: {file_path}")
            continue

        rule = out_to_rule.get(out_path)
        if rule is None:
            errors.append(f"accepted output '{out_path}' not declared in any rule")
            continue

        if rule.get("kind") == "oracle":
            # C.b: Oracle must have a verdict predicate for condensation
            verdict_spec = rule.get("verdict")
            if not verdict_spec:
                errors.append(
                    f"unverdictable oracle: rule '{rule.get('name', '?')}' "
                    f"has no verdict predicate (required for condensation)"
                )
                continue

            # Resolve verdict to callable
            try:
                verdict_fn = _resolve_verdict_predicate(verdict_spec, design)
            except Exception as e:
                errors.append(
                    f"oracle rule '{rule.get('name', '?')}': "
                    f"cannot resolve verdict predicate '{verdict_spec}': {e}"
                )
                continue

            # C.c: Oracle anchor is verdict identity, not bytes
            verdict_id = _pred_identity(verdict_fn)
            anchor[out_path] = {"type": "verdict", "verdict": verdict_id}
            oracle_verdicts[out_path] = {
                "verdict_spec": verdict_spec if isinstance(verdict_spec, str) else verdict_id,
                "fn": verdict_fn,
            }

            # Validate accepted output satisfies verdict
            accepted_site = str(p.parent)
            if not _eval_verdict_on_site(verdict_fn, accepted_site):
                errors.append(
                    f"accepted output '{out_path}' does not satisfy verdict "
                    f"predicate '{verdict_spec}'"
                )
        else:
            # Action (deterministic): anchor is content hash
            anchor[out_path] = hashlib.sha256(p.read_bytes()).hexdigest()

    if errors:
        return _reject(None, anchor, errors=errors)

    # Prepare site directories
    if site is None:
        base = tempfile.mkdtemp(prefix="husks-condense-")
    else:
        base = site
        Path(base).mkdir(parents=True, exist_ok=True)
    m1_dir = str(Path(base) / "m1")
    m2_dir = str(Path(base) / "m2")
    m3_dir = str(Path(base) / "m3")

    # Common build overrides
    def _build_overrides(site_dir: str, **extra) -> dict:
        ov: dict[str, Any] = {"site": site_dir, "sandbox": True, "unsafe": True}
        if not stub:
            if oracle_backend is not None:
                ov["oracle_backend"] = oracle_backend
                ov["oracle_backend_name"] = oracle_backend_name
            if oracle_config is not None:
                ov["oracle_config"] = oracle_config
        return {**ov, **extra}

    # 3. M1 fresh build
    try:
        S1 = locke_run(design, **_build_overrides(m1_dir))
    except Exception as e:
        return _reject(m1_dir, anchor, errors=[f"M1 fresh build failed: {e}"])
    if S1.get("status") != "committed":
        return _reject(m1_dir, anchor, errors=[f"M1 build not committed: {S1.get('status')}"])

    # 4. Cache export from M1
    cache_bundle = str(Path(base) / "cache.tar.gz")
    try:
        cache_export(S1, cache_bundle)
    except Exception as e:
        return _reject(m1_dir, anchor, errors=[f"cache export failed: {e}"])

    # 5. Cache import into M2 + reuse-only run
    try:
        S2_pre = fresh_store(m2_dir, fuel=1)
        cache_import(S2_pre, cache_bundle)
        S2 = locke_run(design, **_build_overrides(m2_dir, cache_reuse_only=True))
    except Exception as e:
        return _reject(m1_dir, anchor, errors=[f"M2 reuse-only build failed: {e}"])
    if S2.get("status") != "committed":
        return _reject(m1_dir, anchor, errors=[f"M2 build not committed: {S2.get('status')}"])

    # 6. M3 independent fresh build
    try:
        S3 = locke_run(design, **_build_overrides(m3_dir))
    except Exception as e:
        return _reject(m1_dir, anchor, errors=[f"M3 independent build failed: {e}"])
    if S3.get("status") != "committed":
        return _reject(m1_dir, anchor, errors=[f"M3 build not committed: {S3.get('status')}"])

    # 7. Build residues for M1/M2/M3
    r1, _ = build_site_residue(m1_dir)
    r2, _ = build_site_residue(m2_dir)
    r3, _ = build_site_residue(m3_dir)
    if r1 is None or r2 is None or r3 is None:
        return _reject(m1_dir, anchor,
                       errors=["failed to build site residue for one or more machines"])

    # 8. Pairwise comparisons
    cmp_m1_m2 = compare_artifacts(
        m1_dir, m2_dir,
        check_root_equality=True, check_root_validity=True,
        check_hashes=True, respect_free=False,
    )
    cmp_m1_m2["site_a"], cmp_m1_m2["site_b"] = m1_dir, m2_dir
    cmp_m1_m2["comparison_type"] = "cache"

    cmp_m1_m3 = compare_artifacts(
        m1_dir, m3_dir,
        check_root_equality=False, check_root_validity=False,
        check_hashes=True, respect_free=True,
    )
    cmp_m1_m3["site_a"], cmp_m1_m3["site_b"] = m1_dir, m3_dir
    cmp_m1_m3["comparison_type"] = "realization"

    cmp_m2_m3 = compare_artifacts(
        m2_dir, m3_dir,
        check_root_equality=False, check_root_validity=False,
        check_hashes=True, respect_free=True,
    )
    cmp_m2_m3["site_a"], cmp_m2_m3["site_b"] = m2_dir, m3_dir
    cmp_m2_m3["comparison_type"] = "observational"

    comparisons = [cmp_m1_m2, cmp_m1_m3, cmp_m2_m3]

    # Build the acceptance anchor for three_machine_checks.
    # For action outputs: content hash (checked by hash equality).
    # For oracle outputs: run verdict on cold output separately below.
    action_anchor: dict[str, str] = {}
    for out_path, anc in anchor.items():
        if isinstance(anc, str):
            # Action: content hash
            action_anchor[out_path] = anc

    # 9. Three-machine proof checks with action-only anchor
    checks = three_machine_checks(
        [r1, r2, r3], comparisons,
        acceptance_anchor=action_anchor if action_anchor else None,
    )

    # 10. Oracle verdict checks (C.c)
    # For each oracle output, verify the verdict predicate passes on the cold output.
    for out_path, vinfo in oracle_verdicts.items():
        verdict_fn = vinfo["fn"]
        verdict_spec = vinfo["verdict_spec"]

        # M1 cold output must satisfy verdict
        m1_ok = _eval_verdict_on_site(verdict_fn, m1_dir)
        # M3 cold output must also satisfy verdict (independent realization)
        m3_ok = _eval_verdict_on_site(verdict_fn, m3_dir)

        both_pass = m1_ok and m3_ok
        checks.append((
            f"oracle verdict '{verdict_spec}' on '{out_path}'",
            both_pass,
            True,  # required
        ))

    # 11. Verdict
    proof_satisfied = all(passed for _, passed, required in checks if required)
    verdict = "CONDENSE" if proof_satisfied else "REJECT"

    result = {
        "verdict": verdict,
        "site": m1_dir,
        "acceptance_anchor": anchor,
        "checks": [(label, passed, required) for label, passed, required in checks],
        "errors": [] if proof_satisfied else [
            f"check failed: {label}"
            for label, passed, required in checks
            if required and not passed
        ],
    }

    # 12. On CONDENSE: enrich M1 manifest with gamma metadata
    if verdict == "CONDENSE":
        manifest_path = Path(m1_dir) / ".traces" / "build.manifest.json"
        if manifest_path.is_file():
            try:
                manifest = json.loads(manifest_path.read_text())
                # Serialize anchor: convert verdict anchors for JSON
                serializable_anchor = {}
                for out_path, anc in anchor.items():
                    if isinstance(anc, dict):
                        serializable_anchor[out_path] = anc
                    else:
                        serializable_anchor[out_path] = anc
                manifest["acceptance_anchor"] = serializable_anchor
                manifest["condensed_in_flight"] = True
                manifest["proposal_source"] = "manual"
                manifest_path.write_text(json.dumps(manifest, indent=2))
            except Exception:
                pass

    return result
