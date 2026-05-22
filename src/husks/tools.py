#- tools.py — core filesystem tools for Husks
#
# Four tools: read-file, write-file, list-dir, tree
# Single @tool decorator auto-generates OpenAI function-calling schemas.
# Public API: schemas(names=None), dispatch(name, args)

import inspect
import os
from pathlib import Path
from typing import get_type_hints


# ── Site sandbox ─────────────────────────────────────────────
_site_root = None   # set before oracle dispatch, cleared after


def set_site_root(path):
    """Set the site root for path containment. All tool paths must resolve within it."""
    global _site_root
    _site_root = Path(path).resolve() if path else None


def sandbox(path):
    """Resolve a path against the site root. Raises ValueError if it escapes."""
    p = Path(path).resolve()
    if _site_root is not None:
        try:
            p.relative_to(_site_root)
        except ValueError:
            raise ValueError(
                f"path '{path}' resolves to '{p}' which is outside the site root '{_site_root}'")
    return p


# ── Registry ─────────────────────────────────────────────────
_REGISTRY = {}   # tool-name → {fn, schema}


def tool(fn):
    """Register a function as a tool. Name derived from fn.__name__ (_ → -)."""
    name = fn.__name__.replace("_", "-")
    hints = get_type_hints(fn)
    sig = inspect.signature(fn)
    props = {}
    required = []
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


def schemas(names=None):
    """Return OpenAI function-calling tool definitions."""
    if names is None:
        return [v["schema"] for v in _REGISTRY.values()]
    return [_REGISTRY[n]["schema"] for n in names if n in _REGISTRY]


def dispatch(name, args):
    """Call a registered tool by name."""
    entry = _REGISTRY.get(name)
    if entry is None:
        return f"Error: unknown tool '{name}'"
    return entry["fn"](**args)


# ── Core tools ───────────────────────────────────────────────

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
        p = sandbox(path)
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
    """Recursive directory listing. Returns an indented tree up to the given depth."""
    try:
        root = sandbox(path)
    except ValueError as e:
        return f"Error: {e}"
    if not root.exists():
        return f"Error: '{path}' does not exist."
    if not root.is_dir():
        return f"Error: '{path}' is not a directory."
    lines = []
    _walk(root, root, depth, lines)
    return "\n".join(lines)


def _walk(base, current, depth, lines):
    """Recursive helper for tree. Skips hidden files and __pycache__."""
    if depth < 0:
        return
    rel = current.relative_to(base)
    indent = "  " * len(rel.parts)
    if current == base:
        lines.append(str(base))
    else:
        lines.append(f"{indent}{current.name}/" if current.is_dir() else f"{indent}{current.name}")
    if current.is_dir():
        children = sorted(current.iterdir(), key=lambda p: (not p.is_dir(), p.name))
        for child in children:
            if child.name.startswith(".") or child.name == "__pycache__":
                continue
            _walk(base, child, depth - (1 if child.is_dir() else 0), lines)
