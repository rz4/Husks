"""
tools.py -- Sandboxed filesystem tools for Husks oracle execution.

This module provides the tool registry that oracles use to interact
with the site directory during execution.  Four built-in tools:

  read-file   -- Read a file as UTF-8 text.
  write-file  -- Write content to a file, creating parent directories.
  list-dir    -- List names in a directory (one level).
  tree        -- Recursive directory listing up to a given depth.

All tool paths are resolved through a site-root sandbox.  When the
sandbox is active, any path that resolves outside the site root
raises ValueError, preventing oracle escape.

Tool registration
-----------------
The ``@tool`` decorator registers a Python function in the module
registry and auto-generates an OpenAI function-calling schema from
the function's type hints and signature.  The tool name is derived
from ``fn.__name__`` with underscores replaced by hyphens
(``read_file`` becomes ``read-file``).

Public API
----------
  set_site_root(path, readonly)  -- Activate/deactivate the sandbox.
  sandbox(path, write)           -- Resolve a path within the sandbox.
  schemas(names)                 -- Return OpenAI tool definitions.
  dispatch(name, args)           -- Call a registered tool by name.

Interface with husks
-------------------------
Consumed by:

  oracle/kernel.py -- calls dispatch() to execute tool calls from
                      the LLM, and schemas() to build the tool
                      definitions sent to the model.

  build.py         -- calls set_site_root() before/after oracle
                      evaluation (indirectly, via kernel.live_oracle).

Does not import anything from husks.  This module is
self-contained with stdlib-only dependencies.
"""

from __future__ import annotations

import inspect
import os
from pathlib import Path
from typing import Any, get_type_hints


# ── Site sandbox ──────────────────────────────────────────────────

_site_root: Path | None = None
_readonly_roots: set[Path] = set()


def set_site_root(path: str | None, readonly: list[str] | None = None) -> None:
    """Activate or deactivate the site-root sandbox.

    When active, all tool paths must resolve within the site root.
    Pass None to deactivate.

    Parameters
    ----------
    path : str or None
        Site root directory.  None deactivates the sandbox.
    readonly : list of str, optional
        Absolute paths of read-only import targets.  Reads through
        symlinks into these directories are permitted; writes are not.
    """
    global _site_root, _readonly_roots
    _site_root = Path(path).resolve() if path else None
    _readonly_roots = {Path(p).resolve() for p in (readonly or [])}


def get_site_root() -> Path | None:
    """Return the current site root, or None if sandboxing is off."""
    return _site_root


def sandbox(path: str, *, write: bool = False) -> Path:
    """Resolve *path* within the site-root sandbox.

    Returns the resolved Path.  Raises ValueError if the resolved
    path escapes the allowed roots.

    Parameters
    ----------
    path : str
        The path to resolve (may be relative to cwd or absolute).
    write : bool
        If True, the path must resolve under the site root only.
        If False (default), the path may also resolve under any
        registered read-only root (import target).
    """
    p = Path(path).resolve()
    if _site_root is not None:
        try:
            p.relative_to(_site_root)
        except ValueError:
            # Write access: must be under site root only.
            if write:
                raise ValueError(
                    f"path '{path}' resolves to '{p}' which is outside "
                    f"the site root '{_site_root}' (write denied)"
                ) from None
            # Read access: also allow read-only roots.
            for ro in _readonly_roots:
                try:
                    p.relative_to(ro)
                    break
                except ValueError:
                    continue
            else:
                raise ValueError(
                    f"path '{path}' resolves to '{p}' which is outside "
                    f"the site root '{_site_root}'"
                ) from None
    return p


# ── Registry ──────────────────────────────────────────────────────

_REGISTRY: dict[str, dict[str, Any]] = {}


def tool(fn):
    """Register a function as a tool.

    The tool name is derived from ``fn.__name__`` with underscores
    replaced by hyphens.  An OpenAI function-calling schema is
    auto-generated from the function's type hints and signature.
    """
    name = fn.__name__.replace("_", "-")
    hints = get_type_hints(fn)
    sig = inspect.signature(fn)
    props: dict[str, dict[str, str]] = {}
    required: list[str] = []
    for pname, param in sig.parameters.items():
        ptype = hints.get(pname, str)
        json_type = {str: "string", int: "integer", float: "number",
                     bool: "boolean"}.get(ptype, "string")
        props[pname] = {"type": json_type, "description": pname}
        if param.default is inspect.Parameter.empty:
            required.append(pname)
    schema = {
        "type": "function",
        "function": {
            "name": name,
            "description": (fn.__doc__ or "").strip(),
            "parameters": {
                "type": "object",
                "properties": props,
                "required": required,
            },
        },
    }
    _REGISTRY[name] = {"fn": fn, "schema": schema}
    return fn


def schemas(names: list[str] | None = None) -> list[dict[str, Any]]:
    """Return OpenAI function-calling tool definitions.

    If *names* is None, returns all registered tools.  Otherwise
    returns only the named tools (silently skipping unknown names).
    """
    if names is None:
        return [v["schema"] for v in _REGISTRY.values()]
    return [_REGISTRY[n]["schema"] for n in names if n in _REGISTRY]


def dispatch(name: str, args: dict[str, Any]) -> str:
    """Call a registered tool by name.

    Returns the tool's string output, or an error string if the
    tool is not found.
    """
    entry = _REGISTRY.get(name)
    if entry is None:
        return f"Error: unknown tool '{name}'"
    return entry["fn"](**args)


# ── Core tools ────────────────────────────────────────────────────

@tool
def read_file(path: str) -> str:
    """Return file contents as a string."""
    try:
        p = sandbox(path)
    except ValueError as e:
        return f"Error: {e}"
    if p.is_dir():
        return f"Error: '{path}' is a directory, not a file. Use list-dir instead."
    if not p.exists():
        return f"Error: '{path}' does not exist."
    try:
        return p.read_text()
    except UnicodeDecodeError:
        return f"Error: '{path}' is a binary file and cannot be read as text."


@tool
def write_file(path: str, content: str) -> str:
    """Write content to a file, creating parent directories as needed."""
    try:
        p = sandbox(path, write=True)
    except ValueError as e:
        return f"Error: {e}"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content)
    return "ok"


@tool
def list_dir(path: str) -> str:
    """Return a list of names in a directory (one level)."""
    try:
        p = sandbox(path)
    except ValueError as e:
        return f"Error: {e}"
    if not p.exists():
        return f"Error: '{path}' does not exist."
    if not p.is_dir():
        return f"Error: '{path}' is not a directory."
    return "\n".join(sorted(os.listdir(str(p))))


@tool
def tree(path: str, depth: int = 3) -> str:
    """Recursive directory listing up to the given depth."""
    try:
        root = sandbox(path)
    except ValueError as e:
        return f"Error: {e}"
    if not root.exists():
        return f"Error: '{path}' does not exist."
    if not root.is_dir():
        return f"Error: '{path}' is not a directory."
    lines: list[str] = []
    _walk(root, root, depth, lines)
    return "\n".join(lines)


def _walk(base: Path, current: Path, depth: int, lines: list[str]) -> None:
    """Recursive helper for tree.  Skips hidden files and __pycache__."""
    if depth < 0:
        return
    rel = current.relative_to(base)
    indent = "  " * len(rel.parts)
    if current == base:
        lines.append(str(base))
    else:
        suffix = "/" if current.is_dir() else ""
        lines.append(f"{indent}{current.name}{suffix}")
    if current.is_dir():
        children = sorted(current.iterdir(), key=lambda p: (not p.is_dir(), p.name))
        for child in children:
            if child.name.startswith(".") or child.name == "__pycache__":
                continue
            _walk(base, child, depth - (1 if child.is_dir() else 0), lines)
