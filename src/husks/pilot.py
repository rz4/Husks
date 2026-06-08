"""L8 pilot -- Session envelope with tracer + explicit condense trigger.

The pilot wraps a working site, attaches a tracer, and provides an explicit
condense trigger.  Multiple condensations per session.  Failed condensation
returns to vapor.  The ratchet proposes action rules over oracle rules.

Tier 4 adds composition: inter-husk DAG via upstream references,
evaporate-then-replay, and cold topological replay.

Dependencies: gamma (L7), tracer (L7) + stdlib.
"""

from __future__ import annotations

import copy
import tempfile
from collections import deque
from pathlib import Path


def _topo_sort(num_nodes: int, edges: list[dict]) -> list[int]:
    """Topological sort via Kahn's algorithm.

    Parameters
    ----------
    num_nodes : int
        Number of nodes (indexed 0..num_nodes-1).
    edges : list[dict]
        Each edge has 'from_node' and 'to_node' (int indices).

    Returns
    -------
    list[int]
        Node indices in topological order.

    Raises
    ------
    ValueError
        If the graph contains a cycle.
    """
    in_degree = [0] * num_nodes
    adj: list[list[int]] = [[] for _ in range(num_nodes)]
    for e in edges:
        src, dst = e["from_node"], e["to_node"]
        adj[src].append(dst)
        in_degree[dst] += 1

    queue: deque[int] = deque(i for i in range(num_nodes) if in_degree[i] == 0)
    order: list[int] = []
    while queue:
        n = queue.popleft()
        order.append(n)
        for nb in adj[n]:
            in_degree[nb] -= 1
            if in_degree[nb] == 0:
                queue.append(nb)

    if len(order) != num_nodes:
        raise ValueError("cycle detected in condensate graph")
    return order


class Pilot:
    """Session envelope: working site + tracer + explicit condense trigger."""

    def __init__(self, *, site: str | None = None, name: str = "pilot"):
        from husks.tracer import Tracer

        if site is None:
            self._site = tempfile.mkdtemp(prefix="husks-pilot-")
        else:
            self._site = site
            Path(site).mkdir(parents=True, exist_ok=True)

        self._name = name
        self._tracer = Tracer(name=name)
        self._droplets: list[dict] = []
        self._edges: list[dict] = []
        self._condense_count = 0

    @property
    def site(self) -> str:
        return self._site

    @property
    def droplets(self) -> list[dict]:
        return list(self._droplets)

    @property
    def status(self) -> str:
        """'vapor' (no droplets) or 'condensed' (>=1 droplet)."""
        return "condensed" if self._droplets else "vapor"

    def record(self, event: dict) -> None:
        """Forward a tool event to the attached tracer."""
        self._tracer.record(event)

    def condense(
        self,
        accepted_outputs: dict[str, str],
        *,
        design_overrides: dict | None = None,
        stub: bool = False,
        upstream: dict[str, tuple[int, str]] | None = None,
    ) -> dict:
        """Explicit condense trigger.  Returns gamma result dict.

        Parameters
        ----------
        upstream : dict[str, tuple[int, str]] | None
            Maps local_input_name -> (droplet_index, output_name).
            Resolves each reference to the upstream droplet's M1 site
            and injects the path into the design's site_inputs.
        """
        from husks.gamma import condense as gamma_condense

        # Draft design from tracer
        design = self._tracer.draft(
            accepted_outputs=list(accepted_outputs.keys()),
        )
        if design_overrides:
            design.update(design_overrides)

        # Resolve upstream references into site_inputs
        if upstream:
            si = design.get("site_inputs", {})
            upstream_provided = set()
            for local_input, (droplet_idx, output_name) in upstream.items():
                upstream_site = self._droplets[droplet_idx]["site"]
                si[local_input] = str(Path(upstream_site) / output_name)
                upstream_provided.add(local_input)
            design["site_inputs"] = si

            # Strip rules whose outputs are fully provided by upstream
            design["rules"] = [
                r for r in design.get("rules", [])
                if not all(o in upstream_provided for o in r.get("outputs", []))
            ]
            # Update target if rules changed
            if design["rules"]:
                design["target"] = design["rules"][-1]["name"]

        # Each condensation gets its own sub-site
        self._condense_count += 1
        sub_site = str(Path(self._site) / f"condense-{self._condense_count}")

        result = gamma_condense(
            design,
            accepted_outputs,
            site=sub_site,
            stub=stub,
        )

        if result["verdict"] == "CONDENSE":
            droplet_idx = len(self._droplets)
            self._droplets.append({
                **result,
                "design": design,
                "accepted_outputs": dict(accepted_outputs),
            })
            # Record edges from upstream
            if upstream:
                for local_input, (src_idx, output_name) in upstream.items():
                    self._edges.append({
                        "from_node": src_idx,
                        "from_output": output_name,
                        "to_node": droplet_idx,
                        "to_input": local_input,
                    })

        return result

    def evaporate(self) -> dict:
        """Persist the droplet graph as a condensate.  Discard tracer state.

        Returns a condensate dict with 'nodes' and 'edges'.  The transcript
        (tracer events) is discarded; only the replayable graph persists.
        """
        nodes = []
        for d in self._droplets:
            # Point accepted_outputs to M1 cold outputs (self-contained)
            cold_accepted = {}
            for name in d["accepted_outputs"]:
                cold_accepted[name] = str(Path(d["site"]) / name)
            nodes.append({
                "design": d["design"],
                "accepted_outputs": cold_accepted,
                "site": d["site"],
            })

        condensate = {
            "nodes": nodes,
            "edges": list(self._edges),
        }

        # Discard the transcript
        self._tracer._events = []

        return condensate

    @staticmethod
    def replay(
        condensate: dict,
        *,
        site: str | None = None,
        stub: bool = False,
    ) -> list[dict]:
        """Replay a condensate cold in topological order.

        Parameters
        ----------
        condensate : dict
            Result of evaporate(): has 'nodes' and 'edges'.
        site : str | None
            Base directory for replay sites.  Defaults to a tempdir.
        stub : bool
            If True, run in stub mode.

        Returns
        -------
        list[dict]
            Gamma results in topological order.  On REJECT, returns
            partial results (fail fast).
        """
        from husks.gamma import condense as gamma_condense

        nodes = condensate["nodes"]
        edges = condensate["edges"]
        num_nodes = len(nodes)

        if num_nodes == 0:
            return []

        order = _topo_sort(num_nodes, edges)

        if site is None:
            base = tempfile.mkdtemp(prefix="husks-replay-")
        else:
            base = site
            Path(base).mkdir(parents=True, exist_ok=True)

        # Build edge lookup: to_node -> list of edges
        incoming: dict[int, list[dict]] = {}
        for e in edges:
            incoming.setdefault(e["to_node"], []).append(e)

        results: list[dict | None] = [None] * num_nodes
        ordered_results: list[dict] = []

        for node_idx in order:
            node = nodes[node_idx]
            design = copy.deepcopy(node["design"])

            # Resolve upstream edges: wire upstream replay M1 outputs
            for e in incoming.get(node_idx, []):
                src_result = results[e["from_node"]]
                src_site = src_result["site"]
                si = design.get("site_inputs", {})
                si[e["to_input"]] = str(Path(src_site) / e["from_output"])
                design["site_inputs"] = si

            # Resolve accepted_outputs: point to original M1 site files
            accepted = {}
            for name, path in node["accepted_outputs"].items():
                accepted[name] = path

            sub_site = str(Path(base) / f"replay-{node_idx}")

            result = gamma_condense(
                design,
                accepted,
                site=sub_site,
                stub=stub,
            )

            results[node_idx] = result
            ordered_results.append(result)

            if result["verdict"] != "CONDENSE":
                return ordered_results  # fail fast

        return ordered_results

    def ratchet(self, accepted_outputs: dict[str, str]) -> dict:
        """Draft design preferring action rules (tracer naturally does this)."""
        design = self._tracer.draft(
            accepted_outputs=list(accepted_outputs.keys()),
        )
        # Verify all rules are action kind (the tracer guarantees this)
        for rule in design.get("rules", []):
            assert rule.get("kind") == "action", (
                f"ratchet: rule '{rule.get('name')}' is not an action rule"
            )
        return design
