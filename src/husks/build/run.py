"""Top-level build orchestration."""

from __future__ import annotations

import hashlib
import uuid
from pathlib import Path
from typing import Any

from husks.core import CSE_VERSION, CseValue, atom, encode
from husks.utils import trace as T

from husks.build.site import Store, Node, OracleBackend, Stop, site_path, ensure_dir, fresh_store, write_bytes_atomic
from husks.build.eval import eval_node, node_to_cse, compute_build_root
from husks.build.seal import write_build_manifest


# ── Top-level build ───────────────────────────────────────────────

_last_store: Store | None = None
"""Captured Store from the most recent ``build()`` call."""


def build(
    *args: Any,
    name: str | None = None,
    fuel: int | None = None,
    site: str | None = None,
    oracle_backend: OracleBackend | None = None,
    oracle_backend_name: str = "litellm",
    oracle_model: str | None = None,
    readonly_dirs: list[str] | None = None,
    site_inputs: list[str] | dict[str, str] | None = None,
    **kwargs: Any,
) -> Store:
    """Execute a build.

    Name and fuel may be passed positionally or as keywords::

        build("my-build", 12, node, ...)              # positional
        build(node, name="my-build", fuel=12)         # keyword

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
    # Beta Gate A1/A2: site_inputs should already be normalized by normalize_site_inputs
    # to a dict of local_name → resolved_path with validated existence.
    # Beta Gate 95: Use resolve_site_inputs() for transparent list/dict handling.
    if site_inputs:
        from husks.build.site import setup_links, resolve_site_inputs

        # Normalize to dict (handles both list and dict forms)
        site_inputs = resolve_site_inputs(site_inputs)

        if site_inputs:  # Only call setup_links if there are paths to link
            si_readonly = setup_links(site, site_inputs)
            readonly_dirs = list(set((readonly_dirs or []) + si_readonly))

    # Clear trace state so sequential in-process builds don't accumulate.
    T.clear()

    S = fresh_store(site, fuel, oracle_backend=oracle_backend, oracle_backend_name=oracle_backend_name, readonly_dirs=readonly_dirs)

    # Beta Gate D5: Set cache-reuse-only mode if requested
    if kwargs.get("cache_reuse_only"):
        S["cache-reuse-only"] = True

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

    # Compute build-root (Merkle DAG) and write verification artifacts
    # CRITICAL: .husk file is only written for committed builds (successful seal).
    # Manifest is written for both committed and halted to record the outcome.
    if nodes and S["status"] == "committed":
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
            # P21: Write .husk atomically with fsync for crash safety
            write_bytes_atomic(husk_path, husk_bytes)
            # P21: Write build manifest atomically and last (uses atomic write_text)
            write_build_manifest(
                S, name, nodes,
                design_source=kwargs.get("design_source"),
                design_kind=kwargs.get("design_kind"),
            )
        except Exception as e:
            # Verification artifact write failure is FATAL
            # Cannot claim committed status without verifiable artifacts
            S["status"] = "halted"
            S["value"] = f"failed to write verification artifacts: {e}"
            S["build-root"] = None
            S["trace"].append({
                "event": "error",
                "message": f"verification artifact write failed: {e}"
            })
    elif nodes and S["status"] == "halted":
        # Halted builds: write manifest to record the failure, but no .husk file
        # The .husk file is the final seal artifact, only for successful builds
        try:
            write_build_manifest(
                S, name, nodes,
                design_source=kwargs.get("design_source"),
                design_kind=kwargs.get("design_kind"),
            )
        except Exception as e:
            # Log manifest write failure but don't change status (already halted)
            S["trace"].append({
                "event": "error",
                "message": f"failed to write manifest for halted build: {e}"
            })

    # Beta 100 Task A5: Promote or discard pending cache based on final status
    # Handles both explicit commit nodes and auto-commits
    if S["status"] == "committed":
        from husks.build.cache import cache_promote_pending
        try:
            promoted = cache_promote_pending(S)
            if promoted > 0:
                S["trace"].append({
                    "event": "cache-promoted",
                    "count": promoted,
                })
        except Exception as e:
            # Log promotion failure but don't fail the committed build
            S["trace"].append({
                "event": "cache-promotion-failed",
                "error": str(e),
            })
    else:
        from husks.build.cache import cache_discard_pending
        from husks.build.seal import clear_fired_seals
        try:
            cache_discard_pending(S)
        except Exception:
            pass  # Best-effort cleanup
        try:
            cleared = clear_fired_seals(S)
            if cleared > 0:
                S["trace"].append({
                    "event": "seals-cleared",
                    "count": cleared,
                })
        except Exception:
            pass  # Best-effort cleanup

    S["trace"].append({"event": "build-end", "status": S["status"]})
    T.build_end(S["status"], S["fuel"], fuel)
    global _last_store
    _last_store = S
    return S
