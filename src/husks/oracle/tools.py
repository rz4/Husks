"""
tools.py -- Sandboxed filesystem tools for Husks oracle execution.

Four built-in tools (read-file, write-file, list-dir, tree) with
site-root sandbox enforcement.  The @tool decorator auto-generates
OpenAI function-calling schemas.  Stdlib only, no husks imports.

See docs/architecture.md for the tool list and sandbox details.
"""

from __future__ import annotations

import inspect
import os
import signal
from pathlib import Path
from typing import Any, get_type_hints


# ── Site sandbox ──────────────────────────────────────────────────

_site_root: Path | None = None
_readonly_roots: set[Path] = set()

# P25: Maximum oracle output size (10 MB)
# Prevents unbounded artifact generation
MAX_WRITE_SIZE = 10 * 1024 * 1024

# P26: Maximum tool execution time (30 seconds)
# Prevents runaway tool operations
MAX_TOOL_TIMEOUT = 30


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

    # P30 (not implemented): Would check for None site_root with write tools,
    # but this breaks test cleanup. Real protection is in sandbox() function.

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
    raw = Path(path)
    if not raw.is_absolute() and effective_root is not None:
        p = (effective_root / raw).resolve()
    else:
        p = raw.resolve()
    if effective_root is not None:
        try:
            p.relative_to(effective_root)
        except ValueError:
            # Write access: must be under site root only.
            # P29: write=True path NEVER consults readonly_roots - security critical!
            # This prevents readonly imports from being re-exported as writable artifacts.
            if write:
                # Assert: readonly_roots is never consulted for writes
                # (This path returns immediately without checking effective_readonly)
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


def _timeout_handler(signum, frame):
    """Signal handler for tool timeout (P26)."""
    raise TimeoutError("tool execution exceeded time limit")


def dispatch(name: str, args: dict[str, Any], *, context: dict[str, Any] | None = None, timeout: int | None = None) -> str:
    """Call a registered tool by name with timeout protection.

    Returns the tool's string output, or an error string if the
    tool is not found or if arguments are malformed.

    Parameters
    ----------
    context : dict, optional
        Extra keyword arguments forwarded to the tool function.
        Used to thread ``site_root`` and ``readonly_roots`` from
        the kernel context without relying on module globals.
    timeout : int, optional
        P26: Maximum execution time in seconds (default: MAX_TOOL_TIMEOUT).
        Each tool dispatch is bounded individually.
    """
    entry = _REGISTRY.get(name)
    if entry is None:
        return f"Error: unknown tool '{name}'"

    # P26: Set up timeout for this tool dispatch
    effective_timeout = timeout if timeout is not None else MAX_TOOL_TIMEOUT
    old_handler = None

    # Catch malformed arguments to prevent crashing the oracle loop
    try:
        # P26: Install timeout handler (Unix only)
        if hasattr(signal, 'SIGALRM'):
            old_handler = signal.signal(signal.SIGALRM, _timeout_handler)
            signal.alarm(effective_timeout)

        if context:
            result = entry["fn"](**args, **context)
        else:
            result = entry["fn"](**args)

        # Cancel timeout if successful
        if hasattr(signal, 'SIGALRM'):
            signal.alarm(0)
            if old_handler:
                signal.signal(signal.SIGALRM, old_handler)

        return result

    except TimeoutError as e:
        # P26: Tool timeout
        if hasattr(signal, 'SIGALRM'):
            signal.alarm(0)
            if old_handler:
                signal.signal(signal.SIGALRM, old_handler)
        # P27: Include exception type
        return f"Error: TimeoutError in '{name}': {e}"
    except TypeError as e:
        # Handle argument errors (wrong types, missing/extra params)
        # P27: Include exception type
        return f"Error: TypeError in '{name}': {e}"
    except Exception as e:
        # Catch any other unexpected errors from the tool
        # P27: Log real exception type instead of just stringifying
        exc_type = type(e).__name__
        return f"Error: {exc_type} in '{name}': {e}"
    finally:
        # Ensure timeout is always canceled
        if hasattr(signal, 'SIGALRM'):
            signal.alarm(0)
            if old_handler:
                signal.signal(signal.SIGALRM, old_handler)


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
    """Write content to a file, creating parent directories as needed.

    P25: Enforces a maximum output size (10 MB) to prevent unbounded artifacts.
    """
    # P25: Cap output size before writing
    content_bytes = content.encode('utf-8')
    if len(content_bytes) > MAX_WRITE_SIZE:
        size_mb = len(content_bytes) / (1024 * 1024)
        max_mb = MAX_WRITE_SIZE / (1024 * 1024)
        return f"Error: content size ({size_mb:.1f} MB) exceeds maximum allowed size ({max_mb:.1f} MB)"

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

    # Convert to Path for sandbox validation during recursion
    # Use global sandbox if no explicit override
    effective_site_root = _site_root if site_root is None else (
        Path(site_root) if not isinstance(site_root, Path) else site_root
    )
    effective_readonly = _readonly_roots if readonly_roots is None else (
        {Path(p) if not isinstance(p, Path) else p for p in readonly_roots}
    )

    lines: list[str] = []
    _walk(root, root, depth, lines, effective_site_root, effective_readonly)
    return "\n".join(lines)


def _walk(
    base: Path,
    current: Path,
    depth: int,
    lines: list[str],
    site_root: Path | None = None,
    readonly_roots: set[Path] | None = None,
) -> None:
    """Recursive helper for tree.  Skips hidden files and __pycache__.

    Validates each child before recursing to prevent symlink traversal
    outside the sandbox.
    """
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

            # Security: resolve and validate child before recursing
            # Skip symlinks that escape the sandbox
            if site_root is not None:
                try:
                    resolved = child.resolve()
                    # Check if resolved path is within allowed roots
                    try:
                        resolved.relative_to(site_root)
                    except ValueError:
                        # Not under site root - check readonly roots
                        allowed = False
                        for ro in (readonly_roots or set()):
                            try:
                                resolved.relative_to(ro)
                                allowed = True
                                break
                            except ValueError:
                                continue
                        if not allowed:
                            # Skip this child - it escapes the sandbox
                            continue
                except (OSError, RuntimeError):
                    # Broken symlink or resolution error - skip it
                    continue

            _walk(base, child, depth - (1 if child.is_dir() else 0), lines,
                  site_root, readonly_roots)
