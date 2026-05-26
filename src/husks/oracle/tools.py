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


_SENTINEL = object()


def sandbox(
    path: str,
    *,
    write: bool = False,
    site_root: Path | None | object = _SENTINEL,
    readonly_roots: set[Path] | None = None,
) -> Path:
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
    site_root : Path or None, optional
        When explicitly passed, use this instead of the module global.
        When omitted (sentinel), fall back to the module global.
    readonly_roots : set of Path, optional
        When explicitly passed, use this instead of the module global.
    """
    effective_root = _site_root if site_root is _SENTINEL else site_root
    effective_readonly = _readonly_roots if readonly_roots is None else readonly_roots
    p = Path(path).resolve()
    if effective_root is not None:
        try:
            p.relative_to(effective_root)
        except ValueError:
            # Write access: must be under site root only.
            if write:
                raise ValueError(
                    f"path '{path}' resolves to '{p}' which is outside "
                    f"the site root '{effective_root}' (write denied)"
                ) from None
            # Read access: also allow read-only roots.
            for ro in effective_readonly:
                try:
                    p.relative_to(ro)
                    break
                except ValueError:
                    continue
            else:
                raise ValueError(
                    f"path '{path}' resolves to '{p}' which is outside "
                    f"the site root '{effective_root}'"
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
    # Internal context parameters that should not appear in tool schemas.
    _INTERNAL_PARAMS = frozenset({"site_root", "readonly_roots"})
    for pname, param in sig.parameters.items():
        if pname in _INTERNAL_PARAMS:
            continue
        if param.kind == inspect.Parameter.KEYWORD_ONLY:
            continue
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


def dispatch(name: str, args: dict[str, Any], *, context: dict[str, Any] | None = None) -> str:
    """Call a registered tool by name.

    Returns the tool's string output, or an error string if the
    tool is not found.

    Parameters
    ----------
    context : dict, optional
        Extra keyword arguments forwarded to the tool function.
        Used to thread ``site_root`` and ``readonly_roots`` from
        the kernel context without relying on module globals.
    """
    entry = _REGISTRY.get(name)
    if entry is None:
        return f"Error: unknown tool '{name}'"
    if context:
        return entry["fn"](**args, **context)
    return entry["fn"](**args)


# ── Core tools ────────────────────────────────────────────────────

def _sandbox_kwargs(site_root=None, readonly_roots=None):
    """Build kwargs for sandbox() from optional context overrides."""
    kw = {}
    if site_root is not None:
        kw["site_root"] = Path(site_root) if not isinstance(site_root, Path) else site_root
    if readonly_roots is not None:
        kw["readonly_roots"] = {
            Path(p) if not isinstance(p, Path) else p for p in readonly_roots
        }
    return kw


@tool
def read_file(path: str, *, site_root=None, readonly_roots=None) -> str:
    """Return file contents as a string."""
    try:
        p = sandbox(path, **_sandbox_kwargs(site_root, readonly_roots))
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
def write_file(path: str, content: str, *, site_root=None, readonly_roots=None) -> str:
    """Write content to a file, creating parent directories as needed."""
    try:
        p = sandbox(path, write=True, **_sandbox_kwargs(site_root, readonly_roots))
    except ValueError as e:
        return f"Error: {e}"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content)
    return "ok"


@tool
def list_dir(path: str, *, site_root=None, readonly_roots=None) -> str:
    """Return a list of names in a directory (one level)."""
    try:
        p = sandbox(path, **_sandbox_kwargs(site_root, readonly_roots))
    except ValueError as e:
        return f"Error: {e}"
    if not p.exists():
        return f"Error: '{path}' does not exist."
    if not p.is_dir():
        return f"Error: '{path}' is not a directory."
    return "\n".join(sorted(os.listdir(str(p))))


@tool
def tree(path: str, depth: int = 3, *, site_root=None, readonly_roots=None) -> str:
    """Recursive directory listing up to the given depth."""
    try:
        root = sandbox(path, **_sandbox_kwargs(site_root, readonly_roots))
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
