"""Architecture checker — import graph analysis and cycle detection.

Uses only stdlib (ast, pathlib, typing) so this module itself cannot
violate the layering contract it enforces.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Any


# ── Import graph extraction ───────────────────────────────────────

def parse_import_edges(
    src_root: str | Path,
    *,
    package_prefix: str = "husks"
) -> dict[str, list[str]]:
    """Parse module-level import edges from Python source files.

    Returns a dict mapping module names to the list of husks.* modules
    they import at module top level (before any function definitions).

    Example: {"husks.build.eval": ["husks.core", "husks.build.identity"]}
    """
    src_root = Path(src_root)
    edges: dict[str, list[str]] = {}

    for py_file in src_root.rglob("*.py"):
        # Skip __pycache__ and hidden directories
        if any(part.startswith(".") or part == "__pycache__"
               for part in py_file.parts):
            continue

        module_name = _file_to_module(py_file, src_root, package_prefix)
        if not module_name:
            continue

        imported = _parse_top_level_imports(py_file, package_prefix)
        if imported:
            edges[module_name] = imported

    return edges


def parse_deferred_edges(
    src_root: str | Path,
    *,
    package_prefix: str = "husks"
) -> dict[str, list[str]]:
    """Parse in-function (deferred) import edges.

    Returns imports that appear inside function bodies, which are
    potential cycle-breaking deferred imports that need whitelisting.
    """
    src_root = Path(src_root)
    edges: dict[str, list[str]] = {}

    for py_file in src_root.rglob("*.py"):
        if any(part.startswith(".") or part == "__pycache__"
               for part in py_file.parts):
            continue

        module_name = _file_to_module(py_file, src_root, package_prefix)
        if not module_name:
            continue

        imported = _parse_deferred_imports(py_file, package_prefix)
        if imported:
            edges[module_name] = imported

    return edges


def _file_to_module(
    py_file: Path,
    src_root: Path,
    package_prefix: str
) -> str | None:
    """Convert a .py file path to a module name like 'husks.core'."""
    try:
        rel = py_file.relative_to(src_root)
    except ValueError:
        return None

    parts = list(rel.parts)

    # Remove .py extension
    if parts[-1].endswith(".py"):
        parts[-1] = parts[-1][:-3]

    # Remove __init__ (package markers)
    if parts[-1] == "__init__":
        parts = parts[:-1]

    # Remove __main__ (entry points, not library modules)
    if parts[-1] == "__main__":
        return None

    if not parts:
        return None

    return ".".join(parts)


def _parse_top_level_imports(
    py_file: Path,
    package_prefix: str
) -> list[str]:
    """Extract module-level imports of package_prefix.* modules.

    Only considers imports before the first function/class definition.
    """
    try:
        source = py_file.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(py_file))
    except (SyntaxError, UnicodeDecodeError):
        return []

    imports: list[str] = []

    # Find first function or class definition
    first_def_line = None
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            if first_def_line is None or node.lineno < first_def_line:
                first_def_line = node.lineno

    # Collect imports before first definition
    for node in tree.body:
        # Stop at first function/class
        if first_def_line is not None and node.lineno >= first_def_line:
            break

        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.startswith(package_prefix + "."):
                    imports.append(_normalize_import(alias.name))
        elif isinstance(node, ast.ImportFrom):
            if node.module and node.module.startswith(package_prefix + "."):
                imports.append(_normalize_import(node.module))
            elif node.module == package_prefix:
                # from husks import X
                imports.append(package_prefix)

    return sorted(set(imports))


def _parse_deferred_imports(
    py_file: Path,
    package_prefix: str
) -> list[str]:
    """Extract in-function imports of package_prefix.* modules."""
    try:
        source = py_file.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(py_file))
    except (SyntaxError, UnicodeDecodeError):
        return []

    imports: list[str] = []

    # Walk all function bodies
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for stmt in ast.walk(node):
                if isinstance(stmt, ast.Import):
                    for alias in stmt.names:
                        if alias.name.startswith(package_prefix + "."):
                            imports.append(_normalize_import(alias.name))
                elif isinstance(stmt, ast.ImportFrom):
                    if stmt.module and stmt.module.startswith(package_prefix + "."):
                        imports.append(_normalize_import(stmt.module))
                    elif stmt.module == package_prefix:
                        imports.append(package_prefix)

    return sorted(set(imports))


def _normalize_import(module: str) -> str:
    """Normalize import to package-level granularity.

    'husks.build.eval' stays as-is.
    'husks.oracle' stays as-is.
    """
    return module


# ── Cycle detection ───────────────────────────────────────────────

def strongly_connected_components(
    edges: dict[str, list[str]]
) -> list[list[str]]:
    """Tarjan's algorithm for finding strongly connected components.

    Returns list of SCCs; any SCC with len > 1 is a cycle.
    """
    index_counter = [0]
    stack: list[str] = []
    lowlinks: dict[str, int] = {}
    index: dict[str, int] = {}
    on_stack: dict[str, bool] = {}
    sccs: list[list[str]] = []

    def strongconnect(node: str) -> None:
        index[node] = index_counter[0]
        lowlinks[node] = index_counter[0]
        index_counter[0] += 1
        stack.append(node)
        on_stack[node] = True

        for neighbor in edges.get(node, []):
            if neighbor not in index:
                strongconnect(neighbor)
                lowlinks[node] = min(lowlinks[node], lowlinks[neighbor])
            elif on_stack.get(neighbor, False):
                lowlinks[node] = min(lowlinks[node], index[neighbor])

        if lowlinks[node] == index[node]:
            scc: list[str] = []
            while True:
                w = stack.pop()
                on_stack[w] = False
                scc.append(w)
                if w == node:
                    break
            sccs.append(scc)

    # Get all nodes
    all_nodes = set(edges.keys())
    for targets in edges.values():
        all_nodes.update(targets)

    for node in sorted(all_nodes):
        if node not in index:
            strongconnect(node)

    return sccs


# ── Architecture checker ──────────────────────────────────────────

def check_architecture(
    src_root: str | Path,
    contract: dict[str, Any],
    *,
    package_prefix: str = "husks"
) -> list[str]:
    """Check architecture contract against source code.

    Returns a list of violations; empty list == pass.

    Parameters
    ----------
    src_root : str | Path
        Root directory containing the package source
    contract : dict
        Parsed layers.toml content
    package_prefix : str
        Package name prefix (default: "husks")

    Returns
    -------
    list[str]
        List of violation messages; empty if all checks pass
    """
    edges = parse_import_edges(src_root, package_prefix=package_prefix)
    deferred = parse_deferred_edges(src_root, package_prefix=package_prefix)

    layers = contract.get("layers", {})
    isolated = contract.get("isolated", {})
    pure_infra = contract.get("pure_infra", {})
    intra_layer = contract.get("intra_layer", {})
    allow_deferred = contract.get("allow_deferred", {})

    violations: list[str] = []

    # 1. Check for cycles (any SCC with > 1 node)
    sccs = strongly_connected_components(edges)
    for scc in sccs:
        if len(scc) > 1:
            cycle_str = " → ".join(scc[:4])  # Show first few
            if len(scc) > 4:
                cycle_str += " → ..."
            violations.append(f"cycle: {cycle_str}")

    # 2. Check for upward edges (importing higher or same layer)
    for source, targets in edges.items():
        source_layer = layers.get(source, 999)

        for target in targets:
            target_layer = layers.get(target, -1)

            # Same layer is allowed only if explicitly ordered in intra_layer
            if target_layer == source_layer:
                if not _same_layer_ok(source, target, intra_layer):
                    violations.append(
                        f"same-layer import without ordering: {source} → {target}"
                    )
            # Upward import (illegal)
            elif target_layer > source_layer:
                violations.append(
                    f"upward import: {source} (L{source_layer}) → {target} (L{target_layer})"
                )

    # 3. Check deferred imports against whitelist
    for source, targets in deferred.items():
        allowed = allow_deferred.get(source, [])
        for target in targets:
            if target not in allowed:
                violations.append(
                    f"unsanctioned deferred import: {source} → (deferred) → {target}"
                )

    # 4. Check pure_infra modules have zero husks imports
    pure_modules = pure_infra.get("modules", [])
    for module in pure_modules:
        if module in edges and edges[module]:
            imported = ", ".join(edges[module])
            violations.append(
                f"pure_infra module imports husks: {module} → {imported}"
            )

    # 5. Check gate isolation (imports core only)
    for module, required_layer in isolated.items():
        if module not in edges:
            continue
        for target in edges[module]:
            target_layer = layers.get(target, 999)
            if target_layer > required_layer:
                violations.append(
                    f"isolated module imports above L{required_layer}: "
                    f"{module} → {target} (L{target_layer})"
                )

    return violations


def _same_layer_ok(
    source: str,
    target: str,
    intra_layer: dict[str, list[str]]
) -> bool:
    """Check if same-layer import is allowed by intra_layer ordering.

    intra_layer maps a module to modules it may import in the same layer.
    Example: {"husks.build.policies": ["husks.build.identity"]}
    means policies can import identity (both in L1).
    """
    allowed_targets = intra_layer.get(source, [])
    return target in allowed_targets
