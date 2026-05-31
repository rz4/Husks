"""
CLI Surface layer - dispatches residue to JSON or visual output.

Beta Gate 95: Command → Residue → Surface architecture.

The surface layer takes CliResidue (shared intermediate representation)
and emits either:
- Pure JSON (machine-readable, no ANSI codes)
- Visual DAG (concise or verbose, with colors and symbols)
"""

from __future__ import annotations
import json
from husks.cli.residue import CliResidue


def emit_residue(residue: CliResidue, *, json_mode: bool = False, verbose: bool = False) -> str:
    """Dispatch residue to JSON or visual output.

    **Beta Gate 95**: Enforces mutual exclusivity of --verbose and --json.

    Parameters
    ----------
    residue : CliResidue
        Shared intermediate representation from command
    json_mode : bool
        Output as pure JSON (no ANSI codes, machine-readable)
    verbose : bool
        Output in verbose visual mode (ignored if json_mode=True)

    Returns
    -------
    str
        Formatted output string

    Raises
    ------
    ValueError
        If both json_mode and verbose are True (mutually exclusive)
    """
    if json_mode and verbose:
        raise ValueError("--verbose and --json are mutually exclusive")

    if json_mode:
        return _emit_json(residue)
    else:
        from husks.cli.view import render_dag
        return render_dag(residue, verbose=verbose)


def _emit_json(residue: CliResidue) -> str:
    """Emit residue as pure JSON with shared vocabulary.

    **Shared vocabulary** (same across check, run, status):
    - Top-level: command, name, site, status, root, fuel_budget, fuel_used, cost, nodes, passes, fails
    - Node-level: name, kind, state, fuel, fuel_budget, cost, cache, output_hash, diagnosis, children

    **No command-specific fields** in the shared vocabulary.
    """
    # Map status for visual display (dry → checked for check command)
    status_display = residue.status
    if residue.command == "check" and residue.status == "dry":
        status_display = "checked"
    elif residue.status == "committed":
        status_display = "sealed"
    elif residue.status == "halted":
        status_display = "failed"

    # Build top-level structure
    output = {
        "command": residue.command,
        "name": residue.design_name,
        "site": residue.site,
        "status": status_display,
        "root": residue.root,
        "fuel_budget": residue.fuel_budget,
        "fuel_used": residue.fuel_used,
        "cost": residue.cost,
        "nodes": [],
        "passes": residue.passes,
        "fails": residue.fails,
    }

    # Build node list
    for node in residue.nodes:
        node_dict = {
            "name": node.name,
            "kind": node.kind,
            "state": node.state,
        }

        # Optional fields (only include if not None)
        if node.children:
            node_dict["children"] = node.children
        if node.fuel is not None:
            node_dict["fuel"] = node.fuel
        if node.fuel_budget is not None:
            node_dict["fuel_budget"] = node.fuel_budget
        if node.cost is not None:
            node_dict["cost"] = node.cost
        if node.cache:
            node_dict["cache"] = node.cache
        if node.output_hash is not None:
            node_dict["output_hash"] = node.output_hash
        if node.diagnosis is not None:
            node_dict["diagnosis"] = node.diagnosis
        if node.stale_reason is not None:
            node_dict["stale_reason"] = node.stale_reason

        output["nodes"].append(node_dict)

    # Add error message if present
    if residue.error_message:
        output["error"] = residue.error_message

    return json.dumps(output, indent=2)
