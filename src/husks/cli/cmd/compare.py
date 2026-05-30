"""All _cmd_* command functions."""

from __future__ import annotations

import json
import sys

from husks.cli.helpers import EXIT_OK, EXIT_BUILD_FAIL, EXIT_USAGE


def _cmd_compare(args):
    """Compare artifact equivalence across sites (Beta Gate C6/C7).

    Compares build roots, output hashes, and seal validity across
    multiple sites to verify cross-machine equivalence.
    """
    from husks.manifest import compare_artifacts

    if len(args.sites) < 2:
        print("error: compare requires at least 2 sites", file=sys.stderr)
        sys.exit(EXIT_USAGE)

    # Determine comparison modes
    check_roots = not args.hashes_only
    check_hashes = not args.roots_only

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

    # Output results
    if args.json_output:
        # Beta Gate C7: Machine-readable JSON only, no console noise
        output = {
            "equivalent": all_equivalent,
            "comparisons": comparisons,
        }
        print(json.dumps(output, indent=2))
    else:
        # Human-readable output
        print()
        print(f"Comparing {len(sites)} sites:")
        for site in sites:
            print(f"  • {site}")
        print()

        for cmp in comparisons:
            site_a_short = cmp["site_a"].split("/")[-1] or cmp["site_a"]
            site_b_short = cmp["site_b"].split("/")[-1] or cmp["site_b"]

            if cmp["equivalent"]:
                print(f"  ✓ {site_a_short} ≡ {site_b_short}")
            else:
                print(f"  ✗ {site_a_short} ≠ {site_b_short}")
                for diff in cmp["differences"]:
                    print(f"      - {diff}")
        print()

        if all_equivalent:
            print("  All sites are equivalent ✓")
        else:
            print("  Sites differ ✗")
        print()

    sys.exit(EXIT_OK if all_equivalent else EXIT_BUILD_FAIL)


def _cmd_compare_runs(args):
    """Compare JSON reports from multiple runs (Beta Gate C/F/G).

    Validates the three-machine proof:
    - M1: paid_cost > 0, oracle_calls > 0
    - M2: paid_cost = 0, oracle_calls = 0, cache_hits > 0, cached_nodes nonempty
    - M3: paid_cost comparable to M1, oracle_calls comparable to M1
    - All: same build root (artifact equivalence)

    Task 1/2/3: Hardened to require explicit cache reuse evidence in M2
    (cached=true flag), not just zero cost. Reports must pass schema validation.

    Task 4/7 (New): Does NOT rely on cost.reused_estimate/projected_estimate fields
    (non-authoritative estimates). Uses authoritative fields: paid_cost, oracle_calls,
    cache_hits, cached_nodes.
    """
    from husks.report import validate_report_schema

    if len(args.reports) < 2:
        print("error: compare-runs requires at least 2 report files", file=sys.stderr)
        sys.exit(EXIT_USAGE)

    # Load all reports
    reports = []
    for path in args.reports:
        try:
            with open(path, 'r') as f:
                report = json.load(f)

                # Task 2: Validate report schema before processing
                valid, errors = validate_report_schema(report)
                if not valid:
                    if args.json_output:
                        # Output JSON error for failed schema validation
                        error_output = {
                            "reports": 0,
                            "equivalent": False,
                            "violations": [f"Report {path} failed schema validation"] + errors,
                            "error": "schema_validation_failed"
                        }
                        print(json.dumps(error_output, indent=2))
                    else:
                        print(f"error: report {path} failed schema validation:", file=sys.stderr)
                        for e in errors:
                            print(f"  - {e}", file=sys.stderr)
                    sys.exit(EXIT_USAGE)

                reports.append({"path": path, "data": report})
        except FileNotFoundError:
            if args.json_output:
                error_output = {
                    "reports": 0,
                    "equivalent": False,
                    "violations": [f"Report file not found: {path}"],
                    "error": "file_not_found"
                }
                print(json.dumps(error_output, indent=2))
            else:
                print(f"error: report file not found: {path}", file=sys.stderr)
            sys.exit(EXIT_USAGE)
        except json.JSONDecodeError as e:
            if args.json_output:
                error_output = {
                    "reports": 0,
                    "equivalent": False,
                    "violations": [f"Invalid JSON in {path}: {e}"],
                    "error": "json_decode_error"
                }
                print(json.dumps(error_output, indent=2))
            else:
                print(f"error: invalid JSON in {path}: {e}", file=sys.stderr)
            sys.exit(EXIT_USAGE)

    # Task 1 (New Task): Validate all reports have status == "committed"
    # CRITICAL: compare-runs should reject halted/error runs
    for i, r in enumerate(reports):
        status = r["data"].get("status")
        if status != "committed":
            if args.json_output:
                error_output = {
                    "reports": len(reports),
                    "equivalent": False,
                    "violations": [
                        f"Report {i+1} ({r['path']}) has status '{status}', expected 'committed'"
                    ],
                    "error": "non_committed_status"
                }
                print(json.dumps(error_output, indent=2))
            else:
                print(
                    f"error: report {i+1} ({r['path']}) has status '{status}', expected 'committed'",
                    file=sys.stderr
                )
            sys.exit(EXIT_BUILD_FAIL)

    # Analyze reports
    # Beta Readiness Task 1: Separate violations from warnings
    comparison = {
        "reports": len(reports),
        "runs": [],
        "checks": {},
        "equivalent": True,
        "violations": [],
        "warnings": [],  # Non-fatal issues
    }

    # Extract key metrics from each report
    for i, r in enumerate(reports):
        data = r["data"]
        run_info = {
            "index": i,
            "path": r["path"],
            "status": data.get("status"),  # Now guaranteed to be "committed"
            "cost_paid": data.get("cost", {}).get("paid", 0.0),
            # Task 7 (New): Support both old and new field names for backward compat
            "cost_reused": data.get("cost", {}).get("reused_estimate",
                                                      data.get("cost", {}).get("reused", 0.0)),
            "root": data.get("root"),
        }

        # Task 3 (New): Use oracle evidence from report if available (schema v2+)
        # Otherwise reconstruct from node-level data (backward compatibility)
        if "oracle_calls" in data and "cache_hits" in data and "cached_nodes" in data:
            # Report provides oracle evidence directly (Task 3)
            oracle_calls = data["oracle_calls"]
            cache_hits = data["cache_hits"]
            cached_node_names = data["cached_nodes"]
        else:
            # Fall back to reconstruction from node data (for old reports)
            oracle_calls = 0
            cache_hits = 0
            cached_node_names = []

            for node in data.get("nodes", []):
                if node.get("kind") == "oracle":
                    # Oracle fired in this run (paid cost)
                    if node.get("state") == "fired" and node.get("cost", {}).get("this_run", 0) > 0:
                        oracle_calls += 1
                    # Task 4: Oracle reused from cache - require EXPLICIT cached=true
                    # (state="sealed" alone doesn't prove cache reuse, could be local seal)
                    elif node.get("cached") is True:
                        cache_hits += 1
                        cached_node_names.append(node["name"])

        # Collect oracle node names for reporting
        oracle_nodes = []
        for node in data.get("nodes", []):
            if node.get("kind") == "oracle":
                oracle_nodes.append(node["name"])

        run_info["oracle_calls"] = oracle_calls
        run_info["cache_hits"] = cache_hits
        run_info["oracle_nodes"] = oracle_nodes
        run_info["cached_nodes"] = cached_node_names  # Task 3: Explicit evidence

        comparison["runs"].append(run_info)

    # Three-machine proof checks (if exactly 3 reports)
    if len(reports) == 3:
        m1, m2, m3 = comparison["runs"]

        # Task 2 (New): M1 must have oracle evidence (oracle_calls > 0)
        # Not just cost > 0, which could be mocked
        if m1["oracle_calls"] == 0:
            comparison["violations"].append("M1 should have oracle_calls > 0 (must fire oracles)")
            comparison["equivalent"] = False
        else:
            comparison["checks"]["m1_oracle_evidence"] = True

        # Check: M1 paid oracle cost
        if m1["cost_paid"] <= 0:
            comparison["violations"].append("M1 should have oracle cost > 0")
            comparison["equivalent"] = False
        else:
            comparison["checks"]["m1_paid_cost"] = True

        # Task 1: M2 must have EVIDENCE of cache reuse, not just zero cost
        # Check: M2 had zero oracle calls
        if m2["oracle_calls"] > 0:
            comparison["violations"].append(f"M2 should have 0 oracle calls, got {m2['oracle_calls']}")
            comparison["equivalent"] = False
        else:
            comparison["checks"]["m2_zero_oracle_calls"] = True

        # Check: M2 paid zero cost
        if m2["cost_paid"] != 0.0:
            comparison["violations"].append(f"M2 should have cost = 0, got {m2['cost_paid']}")
            comparison["equivalent"] = False
        else:
            comparison["checks"]["m2_zero_cost"] = True

        # Task 1/3: Check M2 has explicit cache reuse evidence
        if m2["cache_hits"] == 0:
            comparison["violations"].append(
                "M2 should have cache_hits > 0 (evidence of reuse), got 0"
            )
            comparison["equivalent"] = False
        else:
            comparison["checks"]["m2_has_cache_hits"] = True

        # Task 1/3: Verify M2 actually has cached nodes with evidence
        if len(m2["cached_nodes"]) == 0:
            comparison["violations"].append(
                "M2 should have cached oracle nodes (sealed or cached=True), found none"
            )
            comparison["equivalent"] = False
        else:
            comparison["checks"]["m2_cached_node_evidence"] = True

        # Task 2 (New): M3 must have oracle evidence (oracle_calls > 0)
        # Not just cost > 0, which could be mocked
        if m3["oracle_calls"] == 0:
            comparison["violations"].append("M3 should have oracle_calls > 0 (must fire oracles)")
            comparison["equivalent"] = False
        else:
            comparison["checks"]["m3_oracle_evidence"] = True

        # Check: M3 paid comparable cost to M1
        if m3["cost_paid"] <= 0:
            comparison["violations"].append("M3 should have oracle cost > 0")
            comparison["equivalent"] = False
        else:
            comparison["checks"]["m3_paid_cost"] = True

        # Beta Readiness Task 2: Cost comparability is a hard failure
        # For stub oracle, costs should be exactly equal
        # For live oracle, small variance allowed but still enforced
        cost_diff = abs(m1["cost_paid"] - m3["cost_paid"])
        cost_tolerance = max(m1["cost_paid"] * 0.1, 0.0001)  # 10% or small epsilon

        if cost_diff > cost_tolerance:
            comparison["violations"].append(
                f"M1 and M3 costs not comparable: ${m1['cost_paid']:.6f} vs ${m3['cost_paid']:.6f} "
                f"(diff: ${cost_diff:.6f}, tolerance: ${cost_tolerance:.6f})"
            )
            comparison["equivalent"] = False
            comparison["checks"]["m1_m3_comparable_cost"] = False
        else:
            comparison["checks"]["m1_m3_comparable_cost"] = True

        # Beta Hardening Task 3/4: Cross-check proof fields against actual nodes
        # Don't allow empty nodes lists to pass (Task 4)
        for i, run in enumerate([m1, m2, m3], 1):
            nodes = reports[i-1]["data"].get("nodes", [])
            if len(nodes) == 0:
                comparison["violations"].append(f"M{i} has empty nodes list (invalid proof)")
                comparison["equivalent"] = False

        # Beta Hardening Task 3: M1 must have actual oracle nodes that fired
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

        # Beta Hardening Task 3: M3 must have actual oracle nodes that fired
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

        # Beta Hardening Task 3: M2 must have actual cached oracle nodes
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

        # Beta Hardening Task 3: Verify cached_nodes names real oracle nodes
        m2_oracle_names = {n["name"] for n in m2_nodes if n.get("kind") == "oracle"}
        for cached_name in m2["cached_nodes"]:
            if cached_name not in m2_oracle_names:
                comparison["violations"].append(
                    f"M2 cached_nodes references non-existent oracle: {cached_name}"
                )
                comparison["equivalent"] = False
        if all(name in m2_oracle_names for name in m2["cached_nodes"]):
            comparison["checks"]["m2_cached_nodes_valid"] = True

        # Check: All have same root (if all committed successfully)
        roots = [r["root"] for r in comparison["runs"] if r["root"]]
        if len(set(roots)) > 1:
            comparison["violations"].append(f"Build roots differ: {roots}")
            comparison["equivalent"] = False
        elif len(roots) == 3:
            comparison["checks"]["same_root"] = True

    # Beta Readiness Task 1: Enforce invariant - violations implies not equivalent
    if len(comparison["violations"]) > 0:
        comparison["equivalent"] = False

    # Output
    if args.json_output:
        print(json.dumps(comparison, indent=2))
    else:
        print()
        print(f"Comparing {len(reports)} runs:")
        for run in comparison["runs"]:
            print(f"  [{run['index']}] {run['path']}")
            print(f"      status: {run['status']}")
            print(f"      cost: ${run['cost_paid']:.6f}")
            print(f"      oracle calls: {run['oracle_calls']}, cache hits: {run['cache_hits']}")
            # Task 3: Show explicit cache reuse evidence
            if run['cached_nodes']:
                print(f"      cached nodes: {', '.join(run['cached_nodes'])}")
            print()

        if comparison["checks"]:
            print("Checks:")
            for check, result in comparison["checks"].items():
                sym = "✓" if result is True else ("⚠" if result == "warning" else "✗")
                print(f"  {sym} {check}")
            print()

        if comparison["violations"]:
            print("Violations:")
            for v in comparison["violations"]:
                print(f"  ✗ {v}")
            print()

        # Beta Readiness Task 1: Show warnings separately
        if comparison.get("warnings"):
            print("Warnings:")
            for w in comparison["warnings"]:
                print(f"  ⚠ {w}")
            print()

        if comparison["equivalent"]:
            print("  ✓ Three-machine proof validated")
        else:
            print("  ✗ Proof validation failed")
        print()

    sys.exit(EXIT_OK if comparison["equivalent"] else EXIT_BUILD_FAIL)
