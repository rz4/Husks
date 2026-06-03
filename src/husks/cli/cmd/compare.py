"""Compare command: pairwise artifact equivalence + three-machine proof."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from husks.cli.helpers import EXIT_OK, EXIT_BUILD_FAIL, EXIT_USAGE
from husks.utils.console import (
    BOLD, DIM, RESET, GREEN, YELLOW, RED, CYAN, W,
    render_banner, _visible_len,
)
from husks.report import validate_report_schema
from husks.manifest import read_manifest, compare_artifacts
from husks.cli.cmd.inspect import collect_site_residue
from husks.cli.surface import emit_residue


def _load_site_reports(sites, *, json_output: bool):
    """Load .traces/report.json from each site directory.

    Returns a list of {"path": ..., "data": ...} dicts for sites that have
    reports.  Sites missing reports are returned in a separate skip list.
    """
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

    # State coloring to match logo colors
    state_colors = {"sealed": YELLOW, "committed": YELLOW, "failed": RED}
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
        verbose = getattr(args, 'verbose', False)

        # -- Site cards -------------------------------------------------------
        print()
        if verbose:
            for idx, site in enumerate(sites):
                manifest = read_manifest(site)
                if manifest:
                    residue = collect_site_residue(manifest, site)
                    print(emit_residue(residue, verbose=True))
                else:
                    print(_render_site_card(site, report_by_site.get(site), show_cost))
                if idx < len(sites) - 1:
                    print()
        else:
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

        # Compute husk hashes per site (SHA256 of the .husk file)
        import hashlib
        husk_hash_by_site: dict[str, str | None] = {}
        for site in sites:
            m = read_manifest(site)
            name = m.get("name") if m else None
            hh = None
            if name:
                husk_path = Path(site) / f"{name}.husk"
                if husk_path.is_file():
                    hh = hashlib.sha256(husk_path.read_bytes()).hexdigest()
            husk_hash_by_site[site] = hh

        # Collect pairwise results
        pair_rows: list[tuple[str, str, bool | None, bool | None]] = []
        for cmp in comparisons:
            site_a_short = Path(cmp["site_a"]).name or cmp["site_a"]
            site_b_short = Path(cmp["site_b"]).name or cmp["site_b"]
            details = cmp["details"]
            roots_match = (
                details.get("root_a") == details.get("root_b")
                if check_roots_flag and "root_a" in details
                else None
            )
            hh_a = husk_hash_by_site.get(cmp["site_a"])
            hh_b = husk_hash_by_site.get(cmp["site_b"])
            husks_match = (
                hh_a == hh_b
                if hh_a is not None or hh_b is not None
                else None
            )
            pair_rows.append((site_a_short, site_b_short, roots_match, husks_match))

        # Column layout
        label_col = 14
        col_w = 11
        any_roots = any(rm is not None for _, _, rm, _ in pair_rows)
        any_husks = any(hm is not None for _, _, _, hm in pair_rows)

        # Header
        header = " " * (label_col + 2)
        if any_husks:
            header += "husk".ljust(col_w)
        if any_roots:
            header += "root".ljust(col_w)
        print(f"  {DIM}{header.rstrip()}{RESET}")

        # Rows
        for sa, sb, rm, hm in pair_rows:
            both_ok = (rm is not False) and (hm is not False)
            if both_ok:
                pair_label = f"{GREEN}{sa} \u2261 {sb}{RESET}"
            else:
                pair_label = f"{RED}{sa} \u2260 {sb}{RESET}"
            pad = label_col - _visible_len(pair_label)
            row = f"  {pair_label}{' ' * max(pad, 1)}"
            if any_husks:
                if hm is not None:
                    sym = f"{GREEN}\u2713{RESET}" if hm else f"{RED}\u2717{RESET}"
                else:
                    sym = f"{DIM}-{RESET}"
                row += sym + " " * (col_w - 1)
            if any_roots:
                if rm is not None:
                    sym = f"{GREEN}\u2713{RESET}" if rm else f"{RED}\u2717{RESET}"
                else:
                    sym = f"{DIM}-{RESET}"
                row += sym
            print(row.rstrip())

        print(sep)

        # -- Three-machine proof section --------------------------------------
        if proof is not None:
            print()
            print(f"  {BOLD}three-machine proof{RESET}")
            print(sep)

            checks = proof["checks"]

            # Short-name map: check key → display label
            _label = {
                "m1_oracle_evidence":           "called oracle",
                "m1_paid_cost":                 "paid cost",
                "m1_node_level_oracle_evidence": "fired nodes",
                "m2_zero_oracle_calls":         "zero calls",
                "m2_zero_cost":                 "zero cost",
                "m2_has_cache_hits":            "cache hits",
                "m2_cached_node_evidence":      "cached nodes",
                "m2_node_level_cache_evidence":  "cached flags",
                "m2_cached_nodes_valid":        "names valid",
                "m3_oracle_evidence":           "called oracle",
                "m3_paid_cost":                 "paid cost",
                "m3_node_level_oracle_evidence": "fired nodes",
                "m1_m2_root_identical":         "root identical",
                "m1_m3_comparable_cost":        "comparable cost",
                "m3_declared_equivalence":      "declared equivalence",
            }

            # Column groups (ordered)
            m1_keys = ["m1_oracle_evidence", "m1_paid_cost",
                        "m1_node_level_oracle_evidence"]
            m2_keys = ["m2_zero_oracle_calls", "m2_zero_cost",
                        "m2_has_cache_hits", "m2_cached_node_evidence",
                        "m2_node_level_cache_evidence", "m2_cached_nodes_valid"]
            m3_keys = ["m3_oracle_evidence", "m3_paid_cost",
                        "m3_node_level_oracle_evidence"]
            cross_keys = ["m1_m2_root_identical", "m1_m3_comparable_cost",
                          "m3_declared_equivalence"]

            def _sym(key):
                if checks.get(key) is True:
                    return f"{GREEN}\u2713{RESET}"
                return f"{RED}\u2717{RESET}"

            # Column layout
            col_w = 20
            indent = "    "

            # Headers
            h1 = f"{DIM}M1 \u00b7 oracle{RESET}"
            h2 = f"{DIM}M2 \u00b7 cache{RESET}"
            h3 = f"{DIM}M3 \u00b7 oracle{RESET}"
            pad1 = col_w - _visible_len(h1)
            pad2 = col_w - _visible_len(h2)
            print(f"{indent}{h1}{' ' * pad1}{h2}{' ' * pad2}{h3}")

            # Per-machine rows (pad to max column length)
            n_rows = max(len(m1_keys), len(m2_keys), len(m3_keys))
            for i in range(n_rows):
                c1 = f"{_sym(m1_keys[i])} {_label[m1_keys[i]]}" if i < len(m1_keys) else ""
                c2 = f"{_sym(m2_keys[i])} {_label[m2_keys[i]]}" if i < len(m2_keys) else ""
                c3 = f"{_sym(m3_keys[i])} {_label[m3_keys[i]]}" if i < len(m3_keys) else ""
                p1 = col_w - _visible_len(c1) if c1 else col_w
                p2 = col_w - _visible_len(c2) if c2 else col_w
                print(f"{indent}{c1}{' ' * p1}{c2}{' ' * p2}{c3}")

            # Merge tier: vertical pipes then cross-machine checks
            pipe_line = f"{indent}\u2502{' ' * (col_w - 1)}\u2502{' ' * (col_w - 1)}\u2502"
            print(pipe_line)

            # root identical: merges M2 (connector reaches col_w pipe)
            ck = cross_keys[0]
            entry = f"{_sym(ck)} {_label[ck]} "
            connector_len = col_w - _visible_len(entry)
            print(f"{indent}{entry}{'\u2500' * connector_len}\u256f{' ' * (col_w - 1)}\u2502")

            # comparable cost: merges M3 (connector reaches col_w*2 pipe)
            ck = cross_keys[1]
            entry = f"{_sym(ck)} {_label[ck]} "
            connector_len = col_w * 2 - _visible_len(entry)
            print(f"{indent}{entry}{'\u2500' * connector_len}\u256f")

            # declared equivalence (no connector)
            ck = cross_keys[2]
            print(f"{indent}{_sym(ck)} {_label[ck]}")

            # Violations
            if proof["violations"]:
                print()
                for v in proof["violations"]:
                    print(f"  {RED}\u2717{RESET} {v}")

            print(sep)

        # -- Diff section (--diff) --------------------------------------------
        if getattr(args, 'diff', False):
            import difflib

            # When three-machine proof passes, only diff pairs with mismatching roots
            proof_passed = proof is not None and proof["equivalent"]

            for cmp_result in comparisons:
                if proof_passed:
                    details_r = cmp_result["details"]
                    if details_r.get("root_a") == details_r.get("root_b"):
                        continue
                details = cmp_result["details"]
                outputs_a = details.get("outputs_a", {})
                outputs_b = details.get("outputs_b", {})
                all_outputs = sorted(set(outputs_a.keys()) | set(outputs_b.keys()))

                site_a = cmp_result["site_a"]
                site_b = cmp_result["site_b"]
                sa_short = Path(site_a).name or site_a
                sb_short = Path(site_b).name or site_b

                has_diffs = False
                for output in all_outputs:
                    hash_a = outputs_a.get(output)
                    hash_b = outputs_b.get(output)
                    if hash_a == hash_b:
                        continue

                    file_a = Path(site_a) / output
                    file_b = Path(site_b) / output

                    if not file_a.exists() and not file_b.exists():
                        continue

                    if not has_diffs:
                        print()
                        print(f"  {BOLD}diff{RESET}  {sa_short} \u2194 {sb_short}")
                        print(sep)
                        has_diffs = True

                    try:
                        lines_a = file_a.read_text().splitlines(keepends=True) if file_a.exists() else []
                        lines_b = file_b.read_text().splitlines(keepends=True) if file_b.exists() else []
                    except (UnicodeDecodeError, OSError):
                        # Binary or unreadable file — show hash summary only
                        ha = hash_a[:10] if hash_a else "missing"
                        hb = hash_b[:10] if hash_b else "missing"
                        print(f"    {DIM}{output}{RESET}  (binary)  {ha} \u2192 {hb}")
                        continue

                    diff = difflib.unified_diff(
                        lines_a, lines_b,
                        fromfile=f"{sa_short}/{output}",
                        tofile=f"{sb_short}/{output}",
                    )
                    for line in diff:
                        line = line.rstrip('\n')
                        if line.startswith('+++') or line.startswith('---'):
                            print(f"    {BOLD}{line}{RESET}")
                        elif line.startswith('+'):
                            print(f"    {GREEN}{line}{RESET}")
                        elif line.startswith('-'):
                            print(f"    {RED}{line}{RESET}")
                        elif line.startswith('@@'):
                            print(f"    {CYAN}{line}{RESET}")
                        else:
                            print(f"    {line}")

                if has_diffs:
                    print(sep)

        # -- Footer -----------------------------------------------------------
        print(f"  {GREEN}equivalent{RESET}" if all_equivalent else f"  {RED}not equivalent{RESET}")
        print()

    sys.exit(EXIT_OK if all_equivalent else EXIT_BUILD_FAIL)
