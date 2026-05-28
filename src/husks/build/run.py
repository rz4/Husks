"""Top-level build orchestration."""

from __future__ import annotations

import hashlib
import uuid
from pathlib import Path
from typing import Any

from husks.core import CSE_VERSION, CseValue, atom, encode
from husks.utils import trace as T

from husks.build.site import Store, Node, OracleBackend, Stop, site_path, ensure_dir, fresh_store
from husks.build.eval import eval_node, node_to_cse, compute_build_root
from husks.build.seal import write_build_manifest


# ── Top-level build ───────────────────────────────────────────────

_last_store: Store | None = None
"""Captured Store from the most recent ``build()`` call.

Used by the CLI to retrieve results after executing a .hy design file.
"""


def build(
    *args: Any,
    name: str | None = None,
    fuel: int | None = None,
    site: str | None = None,
    oracle_backend: OracleBackend | None = None,
    oracle_model: str | None = None,
    readonly_dirs: list[str] | None = None,
    site_inputs: list[str] | dict[str, str] | None = None,
    **kwargs: Any,
) -> Store:
    """Execute a build.

    Name and fuel may be passed positionally or as keywords::

        build("my-build", 12, node, ...)        # positional
        build(node, :name "my-build" :fuel 12)  # keyword (Hy style)

    Parameters
    ----------
    name : str
        Build name (used for the .husk filename and trace headers).
    fuel : int
        Global fuel budget.
    *nodes : Node
        One or more root nodes (typically a single target node).
    site : str, optional
        Site directory path.  If not given, a temp directory is created.
    oracle_backend : callable, optional
        Oracle dispatch function.  Defaults to the stub backend.
    oracle_model : str, optional
        Model identifier passed to trace output (advisory only).

    Returns
    -------
    Store
        The final build state dict.
    """
    nodes: list[Node] = []
    for a in args:
        if isinstance(a, str):
            if name is not None:
                raise TypeError("build() got multiple values for 'name'")
            name = a
        elif isinstance(a, int) and not isinstance(a, bool):
            if fuel is not None:
                raise TypeError("build() got multiple values for 'fuel'")
            fuel = a
        elif isinstance(a, dict):
            nodes.append(a)
        else:
            raise TypeError(f"build() unexpected argument: {a!r}")
    if name is None:
        raise TypeError("build() missing required argument: 'name'")
    if fuel is None:
        raise TypeError("build() missing required argument: 'fuel'")
    if site is None:
        site = f"/tmp/mccarthy-{name}-{str(uuid.uuid4())[:8]}"

    # Stage site_inputs: create read-only symlinks into the site directory.
    if site_inputs:
        from husks.build.site import setup_links
        if isinstance(site_inputs, list):
            site_inputs = {Path(si).name: si for si in site_inputs}
        si_readonly = setup_links(site, site_inputs)
        readonly_dirs = list(set((readonly_dirs or []) + si_readonly))

    # Clear trace state so sequential in-process builds don't accumulate.
    T.clear()

    S = fresh_store(site, fuel, oracle_backend=oracle_backend, readonly_dirs=readonly_dirs)

    S["trace"].append({"event": "build-start", "name": name, "site": site, "fuel": fuel})
    T.build_start(name, fuel, site, oracle_model)

    try:
        last_commit_value = None
        for node in nodes:
            try:
                eval_node(S, node)
            except Stop as stop:
                if stop.kind == "halt":
                    raise  # propagate halts immediately
                # commit: record and continue to next target
                last_commit_value = stop.value
                S["status"] = "running"  # reset for next target
        # All targets processed
        S["status"] = "committed"
        S["value"] = last_commit_value if last_commit_value is not None else "ok"
        if last_commit_value is None:
            S["trace"].append({"event": "auto-commit"})
    except Stop:
        pass
    except Exception as e:
        S["status"] = "halted"
        S["value"] = f"error: {e}"
        S["trace"].append({"event": "error", "message": str(e)})

    # Sealed artifact manifest
    T.sealed_manifest()

    # Compute build-root (Merkle DAG) and write .husk file
    if nodes and S["status"] in ("committed", "halted"):
        try:
            if len(nodes) == 1:
                S["build-root"] = compute_build_root(S, nodes[0])
            else:
                per_roots = {
                    n.get("name", n.get("value", n.get("reason", "?"))): compute_build_root(S, n)
                    for n in nodes
                }
                S["target-roots"] = per_roots
                combined = hashlib.sha256(
                    b"".join(r.encode() for r in sorted(per_roots.values()))
                ).hexdigest()
                S["build-root"] = combined
            build_form: list[CseValue] = [
                b"build", atom(name), atom(str(fuel)),
            ] + [node_to_cse(n) for n in nodes]
            husk_form: CseValue = [b"husk", CSE_VERSION, build_form]
            husk_bytes = encode(husk_form)
            husk_path = site_path(S, f"{name}.husk")
            Path(husk_path).write_bytes(husk_bytes)
            write_build_manifest(
                S, name, nodes,
                design_source=kwargs.get("design_source"),
                design_kind=kwargs.get("design_kind"),
            )
        except Exception:
            S["build-root"] = None

    S["trace"].append({"event": "build-end", "status": S["status"]})
    T.build_end(S["status"], S["fuel"], fuel)
    global _last_store
    _last_store = S
    return S
