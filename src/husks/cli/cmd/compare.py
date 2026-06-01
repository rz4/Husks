"""Compare command: pairwise artifact equivalence + three-machine proof."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from husks.cli.helpers import EXIT_OK, EXIT_BUILD_FAIL, EXIT_USAGE
from husks.utils.console import (
    BOLD, DIM, RESET, GREEN, RED, CYAN, W,
    render_banner, _visible_len,
)


def _load_site_reports(sites, *, json_output: bool):
    """Load .traces/report.json from each site directory.

    Returns a list of {"path": ..., "data": ...} dicts for sites that have
    reports.  Sites missing reports are returned in a separate skip list.
    """
    from husks.report import validate_report_schema

    reports = []
    skipped = []

    for site in sites:
        report_path = Path(site) / ".traces" / "report.json"
        if not report_path.exists():
            skipped.append(site)
            continue
        try:
            data = json.loads(report_path.read_text())
            valid, errors = validate_report_schema(data)
            if not valid:
                skipped.append(site)
                if not json_output:
                    print(f"  warning: {site}/.traces/report.json failed schema validation, skipping proof",
                          file=sys.stderr)
                continue
            reports.append({"path": str(report_path), "data": data})
        except (json.JSONDecodeError, OSError):
            skipped.append(site)

    return reports, skipped


def _three_machine_proof(reports, *, json_output: bool):
    """Run three-machine proof checks on loaded report dicts.

    Returns a comparison dict with equivalent, checks, violations, etc.
    """
    comparison = {
        "reports": len(reports),
        "runs": [],
        "checks": {},
        "equivalent": True,
        "violations": [],
        "warnings": [],
    }

    # Validate all reports have status == "committed"
    for i, r in enumerate(reports):
        status = r["data"].get("status")
        if status != "committed":
            comparison["violations"].append(
                f"Report {i+1} ({r['path']}) has status '{status}', expected 'committed'"
            )
            comparison["equivalent"] = False

    if not comparison["equivalent"]:
        return comparison

    # Extract key metrics from each report
    for i, r in enumerate(reports):
        data = r["data"]
        run_info = {
            "index": i,
            "path": r["path"],
            "status": data.get("status"),
            "cost_paid": data.get("cost", {}).get("paid", 0.0),
            "cost_reused": data.get("cost", {}).get("reused_estimate",
                                                      data.get("cost", {}).get("reused", 0.0)),
            "root": data.get("root"),
        }

        if "oracle_calls" in data and "cache_hits" in data and "cached_nodes" in data:
            oracle_calls = data["oracle_calls"]
            cache_hits = data["cache_hits"]
            cached_node_names = data["cached_nodes"]
        else:
            oracle_calls = 0
            cache_hits = 0
            cached_node_names = []

            for node in data.get("nodes", []):
                if node.get("kind") == "oracle":
                    if node.get("state") == "fired" and node.get("cost", {}).get("this_run", 0) > 0:
                        oracle_calls += 1
                    elif node.get("cached") is True:
                        cache_hits += 1
                        cached_node_names.append(node["name"])

        oracle_nodes = []
        for node in data.get("nodes", []):
            if node.get("kind") == "oracle":
                oracle_nodes.append(node["name"])

        run_info["oracle_calls"] = oracle_calls
        run_info["cache_hits"] = cache_hits
        run_info["oracle_nodes"] = oracle_nodes
        run_info["cached_nodes"] = cached_node_names

        comparison["runs"].append(run_info)

    # Three-machine proof checks (if exactly 3 reports)
    if len(reports) == 3:
        m1, m2, m3 = comparison["runs"]

        # M1 must have oracle evidence
        if m1["oracle_calls"] == 0:
            comparison["violations"].append("M1 should have oracle_calls > 0 (must fire oracles)")
            comparison["equivalent"] = False
        else:
            comparison["checks"]["m1_oracle_evidence"] = True

        if m1["cost_paid"] <= 0:
            comparison["violations"].append("M1 should have oracle cost > 0")
            comparison["equivalent"] = False
        else:
            comparison["checks"]["m1_paid_cost"] = True

        # M2 must have cache reuse evidence
        if m2["oracle_calls"] > 0:
            comparison["violations"].append(f"M2 should have 0 oracle calls, got {m2['oracle_calls']}")
            comparison["equivalent"] = False
        else:
            comparison["checks"]["m2_zero_oracle_calls"] = True

        if m2["cost_paid"] != 0.0:
            comparison["violations"].append(f"M2 should have cost = 0, got {m2['cost_paid']}")
            comparison["equivalent"] = False
        else:
            comparison["checks"]["m2_zero_cost"] = True

        if m2["cache_hits"] == 0:
            comparison["violations"].append(
                "M2 should have cache_hits > 0 (evidence of reuse), got 0"
            )
            comparison["equivalent"] = False
        else:
            comparison["checks"]["m2_has_cache_hits"] = True

        if len(m2["cached_nodes"]) == 0:
            comparison["violations"].append(
                "M2 should have cached oracle nodes (sealed or cached=True), found none"
            )
            comparison["equivalent"] = False
        else:
            comparison["checks"]["m2_cached_node_evidence"] = True

        # M3 must have oracle evidence
        if m3["oracle_calls"] == 0:
            comparison["violations"].append("M3 should have oracle_calls > 0 (must fire oracles)")
            comparison["equivalent"] = False
        else:
            comparison["checks"]["m3_oracle_evidence"] = True

        if m3["cost_paid"] <= 0:
            comparison["violations"].append("M3 should have oracle cost > 0")
            comparison["equivalent"] = False
        else:
            comparison["checks"]["m3_paid_cost"] = True

        # Cross-check proof fields against actual nodes
        for i, run in enumerate([m1, m2, m3], 1):
            nodes = reports[i-1]["data"].get("nodes", [])
            if len(nodes) == 0:
                comparison["violations"].append(f"M{i} has empty nodes list (invalid proof)")
                comparison["equivalent"] = False

        # M1 must have actual oracle nodes that fired
        m1_nodes = reports[0]["data"].get("nodes", [])
        m1_fired_oracles = [
            n for n in m1_nodes
            if n.get("kind") == "oracle"
            and n.get("state") == "fired"
            and not n.get("cached", False)
            and n.get("cost", {}).get("this_run", 0) > 0
        ]
        if len(m1_fired_oracles) == 0:
            comparison["violations"].append(
                "M1 must have at least one oracle node that fired (state=fired, cached=false, cost.this_run>0)"
            )
            comparison["equivalent"] = False
        else:
            comparison["checks"]["m1_node_level_oracle_evidence"] = True

        # M3 must have actual oracle nodes that fired
        m3_nodes = reports[2]["data"].get("nodes", [])
        m3_fired_oracles = [
            n for n in m3_nodes
            if n.get("kind") == "oracle"
            and n.get("state") == "fired"
            and not n.get("cached", False)
            and n.get("cost", {}).get("this_run", 0) > 0
        ]
        if len(m3_fired_oracles) == 0:
            comparison["violations"].append(
                "M3 must have at least one oracle node that fired (state=fired, cached=false, cost.this_run>0)"
            )
            comparison["equivalent"] = False
        else:
            comparison["checks"]["m3_node_level_oracle_evidence"] = True

        # M2 must have actual cached oracle nodes
        m2_nodes = reports[1]["data"].get("nodes", [])
        m2_cached_oracles = [
            n for n in m2_nodes
            if n.get("kind") == "oracle" and n.get("cached") is True
        ]
        if len(m2_cached_oracles) == 0:
            comparison["violations"].append(
                "M2 must have at least one oracle node with cached=true (cache reuse evidence)"
            )
            comparison["equivalent"] = False
        else:
            comparison["checks"]["m2_node_level_cache_evidence"] = True

        # Verify cached_nodes names real oracle nodes
        m2_oracle_names = {n["name"] for n in m2_nodes if n.get("kind") == "oracle"}
        for cached_name in m2["cached_nodes"]:
            if cached_name not in m2_oracle_names:
                comparison["violations"].append(
                    f"M2 cached_nodes references non-existent oracle: {cached_name}"
                )
                comparison["equivalent"] = False
        if all(name in m2_oracle_names for name in m2["cached_nodes"]):
            comparison["checks"]["m2_cached_nodes_valid"] = True

        # Cache path determinism (M1 root == M2 root)
        m1_root = reports[0]["data"].get("root")
        m2_root = reports[1]["data"].get("root")
        if m1_root and m2_root:
            if m1_root == m2_root:
                comparison["checks"]["m1_m2_root_identical"] = True
            else:
                comparison["violations"].append(
                    f"M1/M2 cache nondeterminism: roots differ ({m1_root[:7]} vs {m2_root[:7]})"
                )
                comparison["equivalent"] = False

        # M3 validator-bounded acceptance
        m1_outputs_by_node = {}
        m3_outputs_by_node = {}

        for node in m1_nodes:
            name = node.get("name")
            outputs = node.get("outputs", [])
            if name and outputs:
                m1_outputs_by_node[name] = {out["path"]: out["hash"] for out in outputs}

        for node in m3_nodes:
            name = node.get("name")
            outputs = node.get("outputs", [])
            if name and outputs:
                m3_outputs_by_node[name] = {out["path"]: out["hash"] for out in outputs}

        acceptance_outputs = []
        free_outputs = []
        acceptance_match = True

        for node in m1_nodes:
            name = node.get("name")
            equivalence = node.get("equivalence", {})

            if name not in m1_outputs_by_node or name not in m3_outputs_by_node:
                continue

            m1_outs = m1_outputs_by_node[name]
            m3_outs = m3_outputs_by_node[name]

            for path in m1_outs.keys():
                relation = equivalence.get(path, "exact")

                if relation == "free":
                    free_outputs.append(path)
                    continue

                acceptance_outputs.append(path)

                if m1_outs.get(path) != m3_outs.get(path):
                    comparison["violations"].append(
                        f"M3 acceptance divergence: {path} hash mismatch "
                        f"(M1:{m1_outs[path][:7]} vs M3:{m3_outs[path][:7]})"
                    )
                    comparison["equivalent"] = False
                    acceptance_match = False

        if acceptance_match and acceptance_outputs:
            comparison["checks"]["m3_declared_equivalence"] = True

        # Cost comparability with declared tolerance
        cost_tolerance = reports[0]["data"].get("cost_tolerance", {"ratio": [0.5, 2.0]})

        c1 = m1["cost_paid"]
        c3 = m3["cost_paid"]

        if c1 > 0:
            cost_ratio = c3 / c1
            min_ratio, max_ratio = cost_tolerance["ratio"]

            if min_ratio <= cost_ratio <= max_ratio:
                comparison["checks"]["m1_m3_comparable_cost"] = True
            else:
                comparison["violations"].append(
                    f"M1/M3 cost out of tolerance: C3/C1={cost_ratio:.3f} "
                    f"(allowed: [{min_ratio}, {max_ratio}])"
                )
                comparison["equivalent"] = False
                comparison["checks"]["m1_m3_comparable_cost"] = False
        else:
            if c3 == 0:
                comparison["checks"]["m1_m3_comparable_cost"] = True

        # Observational convergence (never flips equivalent)
        m3_root = reports[2]["data"].get("root")
        convergence = {
            "m1_m3_same_root": m1_root == m3_root if (m1_root and m3_root) else None,
            "acceptance_outputs": list(set(acceptance_outputs)),
            "acceptance_outputs_match": acceptance_match if acceptance_outputs else None,
            "free_outputs": list(set(free_outputs)),
        }
        comparison["convergence"] = convergence

    # Enforce invariant - violations implies not equivalent
    if len(comparison["violations"]) > 0:
        comparison["equivalent"] = False

    return comparison


def _rpad(left: str, right: str, width: int) -> str:
    """Pad between *left* and *right* so the combined visible width = *width*."""
    if not right:
        return left
    lv = _visible_len(left)
    rv = _visible_len(right)
    gap = max(1, width - lv - rv)
    return f"{left}{' ' * gap}{right}"


def _render_site_card(site_path: str, report_data: dict | None, show_cost: bool) -> str:
    """Return a rendered diamond card for a single site."""
    from husks.manifest import read_manifest

    short_name = Path(site_path).name or site_path
    manifest = read_manifest(site_path)

    # Extract fields from manifest, fall back to report_data
    if manifest:
        name = manifest.get("name", short_name)
        root = manifest.get("root")
        husk_hash = manifest.get("husk_hash")
        status = "committed"
    elif report_data:
        name = report_data.get("name", short_name)
        root = report_data.get("root")
        husk_hash = None
        status = report_data.get("status", "unknown")
    else:
        name = short_name
        root = None
        husk_hash = None
        status = "unknown"

    # Diamond stage
    if status == "committed":
        stage = "sealed"
    else:
        stage = "dry"

    # State coloring
    state_colors = {"sealed": CYAN, "committed": CYAN, "failed": RED}
    status_display = "sealed" if status == "committed" else status
    sc = state_colors.get(status_display, DIM)
    state_str = f"{sc}{status_display}{RESET}"

    # Build right-column lines
    right = [
        f"{BOLD}name{RESET}:  {name}",
        f"{BOLD}state{RESET}: {state_str}",
        f"{BOLD}root{RESET}:  sha256:{root[:6]}" if root else "",
    ]

    if show_cost and report_data:
        cost = report_data.get("cost", {}).get("paid", 0.0)
        right.append(f"{BOLD}cost{RESET}:  ${cost:.6f}")
    elif husk_hash:
        right.append(f"{BOLD}husk{RESET}:  sha256:{husk_hash[:6]}")
    else:
        right.append("")

    right.append(f"{BOLD}site{RESET}:  {short_name}")

    return render_banner(stage, right)


def _cmd_compare(args):
    """Compare equivalence across sites (three-machine proof with 3+).

    Pairwise artifact comparison (roots + hashes) for any number of sites.
    For 3+ sites: additionally reads .traces/report.json from each site
    and runs the three-machine proof checks.
    """
    from husks.manifest import compare_artifacts

    if len(args.sites) < 2:
        print("error: compare requires at least 2 sites", file=sys.stderr)
        sys.exit(EXIT_USAGE)

    # Determine comparison modes
    check_roots = not getattr(args, 'hashes_only', False)
    check_hashes = not getattr(args, 'roots_only', False)

    # Pairwise comparison of all sites
    sites = args.sites
    comparisons = []
    all_equivalent = True

    for i in range(len(sites)):
        for j in range(i + 1, len(sites)):
            site_a = sites[i]
            site_b = sites[j]

            result = compare_artifacts(
                site_a, site_b,
                check_roots=check_roots,
                check_hashes=check_hashes,
            )

            comparisons.append({
                "site_a": site_a,
                "site_b": site_b,
                "equivalent": result["equivalent"],
                "differences": result["differences"],
                "details": result["details"],
            })

            if not result["equivalent"]:
                all_equivalent = False

    # Three-machine proof for 3+ sites
    proof = None
    proof_skipped = []
    reports = []
    json_output = getattr(args, 'json_output', False)

    if len(sites) >= 3:
        reports, proof_skipped = _load_site_reports(sites, json_output=json_output)
        if len(reports) >= 3:
            proof = _three_machine_proof(reports, json_output=json_output)
            if proof["equivalent"]:
                # Three-machine proof passed: proof is the authoritative
                # equivalence check (handles scoped equivalence / free outputs).
                # Pairwise differences are expected when oracle outputs differ.
                all_equivalent = True
            else:
                all_equivalent = False
        elif not json_output and proof_skipped:
            for s in proof_skipped:
                print(f"  warning: {s} has no .traces/report.json, skipping three-machine proof",
                      file=sys.stderr)

    # Output results
    if json_output:
        output = {
            "equivalent": all_equivalent,
            "comparisons": comparisons,
        }
        if proof is not None:
            output["proof"] = proof
        if proof_skipped:
            output["proof_skipped"] = proof_skipped
        print(json.dumps(output, indent=2))
    else:
        # -- Build report lookup for cards ------------------------------------
        report_by_site: dict[str, dict] = {}
        for r in reports:
            site_dir = str(Path(r["path"]).parent.parent)
            report_by_site[site_dir] = r["data"]

        show_cost = proof is not None

        # -- Site cards -------------------------------------------------------
        print()
        for idx, site in enumerate(sites):
            rd = report_by_site.get(site)
            print(_render_site_card(site, rd, show_cost))
            if idx < len(sites) - 1:
                print()

        # -- Verify section ---------------------------------------------------
        hline = '\u2500' * (W - 2)
        sep = f"  {DIM}{hline}{RESET}"
        print()
        print(f"  {BOLD}verify{RESET}")
        print(sep)

        check_roots_flag = not getattr(args, 'hashes_only', False)
        check_hashes_flag = not getattr(args, 'roots_only', False)

        for cmp in comparisons:
            site_a_short = Path(cmp["site_a"]).name or cmp["site_a"]
            site_b_short = Path(cmp["site_b"]).name or cmp["site_b"]
            details = cmp["details"]

            if check_roots_flag and "root_a" in details:
                roots_match = details.get("root_a") == details.get("root_b")
                if roots_match:
                    left = f"  {GREEN}\u2713{RESET} {site_a_short} \u2261 {site_b_short}"
                    reason = "roots match"
                else:
                    left = f"  {RED}\u2717{RESET} {site_a_short} \u2260 {site_b_short}"
                    reason = "roots differ"
                print(_rpad(left, reason, W))

            if check_hashes_flag and "outputs_a" in details:
                hashes_match = details.get("outputs_a") == details.get("outputs_b")
                if hashes_match:
                    left = f"  {GREEN}\u2713{RESET} {site_a_short} \u2261 {site_b_short}"
                    reason = "hashes match"
                else:
                    left = f"  {RED}\u2717{RESET} {site_a_short} \u2260 {site_b_short}"
                    reason = "hashes differ"
                print(_rpad(left, reason, W))

        print(sep)

        # -- Three-machine proof section --------------------------------------
        if proof is not None:
            print()
            print(f"  {BOLD}three-machine proof{RESET}")
            print(sep)

            # Two-column check layout
            checks = list(proof["checks"].items())
            if checks:
                col_w = 30
                rows = []
                for ck, val in checks:
                    sym = f"{GREEN}\u2713{RESET}" if val is True else f"{RED}\u2717{RESET}"
                    rows.append(f"{sym} {ck}")

                for i in range(0, len(rows), 2):
                    left_cell = rows[i]
                    right_cell = rows[i + 1] if i + 1 < len(rows) else ""
                    if right_cell:
                        pad = col_w - _visible_len(left_cell)
                        print(f"  {left_cell}{' ' * max(1, pad)}{right_cell}")
                    else:
                        print(f"  {left_cell}")

            # Violations
            if proof["violations"]:
                for v in proof["violations"]:
                    print(f"  {RED}\u2717{RESET} {v}")

            print(sep)

        # -- Footer -----------------------------------------------------------
        print(f"  {GREEN}equivalent{RESET}" if all_equivalent else f"  {RED}not equivalent{RESET}")
        print()

    sys.exit(EXIT_OK if all_equivalent else EXIT_BUILD_FAIL)
