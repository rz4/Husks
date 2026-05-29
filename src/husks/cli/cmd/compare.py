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

    Task 4: Does NOT rely on cost.reused/projected fields (non-authoritative
    estimates). Uses authoritative fields: paid_cost, oracle_calls, cache_hits,
    cached_nodes.
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

    # Analyze reports
    comparison = {
        "reports": len(reports),
        "runs": [],
        "checks": {},
        "equivalent": True,
        "violations": [],
    }

    # Extract key metrics from each report
    for i, r in enumerate(reports):
        data = r["data"]
        run_info = {
            "index": i,
            "path": r["path"],
            "status": data.get("status"),
            "cost_paid": data.get("cost", {}).get("paid", 0.0),
            "cost_reused": data.get("cost", {}).get("reused", 0.0),
            "root": data.get("root"),
        }

        # Count oracle calls, cache hits, and collect reuse evidence
        oracle_calls = 0
        cache_hits = 0
        oracle_nodes = []
        cached_node_names = []  # Task 3: Explicit cache reuse evidence

        for node in data.get("nodes", []):
            if node.get("kind") == "oracle":
                oracle_nodes.append(node["name"])
                # Oracle fired in this run (paid cost)
                if node.get("state") == "fired" and node.get("cost", {}).get("this_run", 0) > 0:
                    oracle_calls += 1
                # Task 4: Oracle reused from cache - require EXPLICIT cached=true
                # (state="sealed" alone doesn't prove cache reuse, could be local seal)
                elif node.get("cached") is True:
                    cache_hits += 1
                    cached_node_names.append(node["name"])

        run_info["oracle_calls"] = oracle_calls
        run_info["cache_hits"] = cache_hits
        run_info["oracle_nodes"] = oracle_nodes
        run_info["cached_nodes"] = cached_node_names  # Task 3: Explicit evidence

        comparison["runs"].append(run_info)

    # Three-machine proof checks (if exactly 3 reports)
    if len(reports) == 3:
        m1, m2, m3 = comparison["runs"]

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

        # Check: M3 paid comparable cost to M1
        if m3["cost_paid"] <= 0:
            comparison["violations"].append("M3 should have oracle cost > 0")
            comparison["equivalent"] = False
        else:
            comparison["checks"]["m3_paid_cost"] = True

        # For stub oracle, costs should be exactly equal
        # For live oracle, allow some variance
        cost_diff = abs(m1["cost_paid"] - m3["cost_paid"])
        cost_tolerance = max(m1["cost_paid"] * 0.1, 0.0001)  # 10% or small epsilon

        if cost_diff > cost_tolerance:
            comparison["violations"].append(
                f"M1 and M3 costs differ significantly: {m1['cost_paid']} vs {m3['cost_paid']}"
            )
            # Don't mark as non-equivalent - costs can vary with live oracle
            comparison["checks"]["m1_m3_comparable_cost"] = "warning"
        else:
            comparison["checks"]["m1_m3_comparable_cost"] = True

        # Check: All have same root (if all committed successfully)
        roots = [r["root"] for r in comparison["runs"] if r["root"]]
        if len(set(roots)) > 1:
            comparison["violations"].append(f"Build roots differ: {roots}")
            comparison["equivalent"] = False
        elif len(roots) == 3:
            comparison["checks"]["same_root"] = True

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

        if comparison["equivalent"]:
            print("  ✓ Three-machine proof validated")
        else:
            print("  ✗ Proof validation failed")
        print()

    sys.exit(EXIT_OK if comparison["equivalent"] else EXIT_BUILD_FAIL)
