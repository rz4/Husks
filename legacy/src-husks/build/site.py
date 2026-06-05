"""Site helpers: Store, filesystem utilities, fuel."""

from __future__ import annotations

import os
import tempfile
import uuid
from pathlib import Path
from typing import Any, Callable

from husks.core import ABSENT, content_hash

# ── Type aliases ──────────────────────────────────────────────────

Store = dict[str, Any]
Node = dict[str, Any]
Recipe = dict[str, Any] | None
OracleBackend = Callable[[Store, str, dict, list[str]], dict[str, Any] | None]


# ── Stop signal ───────────────────────────────────────────────────

class Stop(Exception):
    """Flow-control exception for commit and halt transitions.

    Raised by eval_node when it encounters a commit or halt node, or
    by burn() when fuel is exhausted.  The build() top-level catches
    Stop and records the final status.
    """

    __slots__ = ("kind", "value")

    def __init__(self, kind: str, value: str) -> None:
        self.kind = kind
        self.value = value
        super().__init__()


# ── Site helpers ──────────────────────────────────────────────────

def site_path(S: Store, name: str, *, write: bool = False) -> str:
    """Resolve *name* relative to the site directory.

    Raises ValueError if the resolved path escapes the site root
    (e.g. via ``..`` components or absolute paths).  Symlinked imports
    (registered as read-only dirs) are permitted to resolve outside
    when *write* is False.  When *write* is True, paths that escape
    the site root are always rejected.

    .. deprecated::
        Use read_path() or write_path() for clarity in action code.
    """
    site = Path(S["site"]).resolve()
    if write and "stage" in S:
        base = Path(S["stage"]).resolve()
    else:
        base = site
    raw = base / name

    # When writing to stage, break symlinks so writes create real files
    # in the stage directory instead of following through to the live site.
    if write and "stage" in S:
        # Break parent directory symlinks first (for nested paths like "dir/file.txt")
        # This ensures we create real staged directories, not write through symlinks.
        parts = Path(name).parts
        for i in range(len(parts) - 1):  # Check all parent directories
            parent = base / Path(*parts[:i+1])
            if parent.is_symlink():
                # Break symlink and create real directory
                import os
                target = parent.resolve()
                parent.unlink()
                parent.mkdir(parents=True, exist_ok=True)
                # Mirror contents of the original directory (as symlinks)
                # so existing files are still accessible
                if target.is_dir():
                    for item in target.iterdir():
                        link = parent / item.name
                        if not link.exists():
                            os.symlink(str(item), str(link))

        # Break final path symlink if it exists
        if raw.is_symlink():
            raw.unlink()

    target = raw.resolve()
    if not target.is_relative_to(base):
        if write:
            raise ValueError(f"path escapes site (write denied): {name}")
        # Allow paths that resolve into registered read-only dirs (imports)
        readonly_dirs = S.get("readonly-dirs", [])
        if not any(target.is_relative_to(Path(rd).resolve()) for rd in readonly_dirs):
            raise ValueError(f"path escapes site: {name}")
    return str(target)


def read_path(S: Store, name: str) -> str:
    """Resolve *name* for reading from the site.

    Returns the path to read from, preferring staged versions during
    staging contexts. Use this helper when reading inputs or checking
    for file existence in actions.

    Example:
        def my_action(S):
            data = Path(read_path(S, "input.txt")).read_text()
            # Process data...

    Raises ValueError if the path escapes the site root.
    """
    return site_path(S, name, write=False)


def write_path(S: Store, name: str) -> str:
    """Resolve *name* for writing to the site.

    During staged builds, returns the staging path to ensure writes
    are isolated from the live site. Outside staging, returns the
    live site path. Use this helper when writing outputs in actions
    to prevent accidental live-site mutation during staged builds.

    Example:
        def my_action(S):
            output_path = write_path(S, "output.txt")
            Path(output_path).write_text("result")

    Migration from legacy pattern:
        # Old (risky - bypasses staging):
        path = site_path(S, "output.txt")

        # New (safe - respects staging):
        path = write_path(S, "output.txt")

    Raises ValueError if the path escapes the site root.
    """
    return site_path(S, name, write=True)


def ensure_dir(p: str) -> str:
    """Create directory *p* and all parents.  Returns *p*."""
    Path(p).mkdir(parents=True, exist_ok=True)
    return p


def read_text(p: str) -> str:
    """Read a file as UTF-8 text."""
    return Path(p).read_text()


def write_text(p: str, s: str) -> str:
    """Write UTF-8 text to a file atomically with fsync, creating parent directories.

    Uses a temporary file in the same directory followed by os.replace() to ensure
    the write is atomic. Calls fsync() before closing to ensure durability on disk.
    A crash mid-write leaves the original file intact or the new file fully written.

    Returns *p*.
    """
    pp = Path(p)
    ensure_dir(str(pp.parent))

    # Write to a temporary file in the same directory (same filesystem)
    # to ensure os.replace() can be atomic
    fd, temp_path = tempfile.mkstemp(
        dir=str(pp.parent),
        prefix=f".{pp.name}.",
        suffix=".tmp"
    )
    fd_closed = False
    try:
        # Write the content
        os.write(fd, str(s).encode('utf-8'))
        # Flush to OS buffers and sync to disk
        os.fsync(fd)
        os.close(fd)
        fd_closed = True
        # Atomically replace the target file
        os.replace(temp_path, str(pp))
    except:
        # Clean up temp file on error
        if not fd_closed:
            try:
                os.close(fd)
            except:
                pass
        try:
            os.unlink(temp_path)
        except:
            pass
        raise

    return p


def write_bytes_atomic(p: str, data: bytes) -> str:
    """Write bytes to a file atomically with fsync, creating parent directories.

    Uses a temporary file in the same directory followed by os.replace() to ensure
    the write is atomic. Calls fsync() before closing to ensure durability on disk.
    A crash mid-write leaves the original file intact or the new file fully written.

    Returns *p*.
    """
    pp = Path(p)
    ensure_dir(str(pp.parent))

    # Write to a temporary file in the same directory (same filesystem)
    # to ensure os.replace() can be atomic
    fd, temp_path = tempfile.mkstemp(
        dir=str(pp.parent),
        prefix=f".{pp.name}.",
        suffix=".tmp"
    )
    fd_closed = False
    try:
        # Write the content
        os.write(fd, data)
        # Flush to OS buffers and sync to disk
        os.fsync(fd)
        os.close(fd)
        fd_closed = True
        # Atomically replace the target file
        os.replace(temp_path, str(pp))
    except:
        # Clean up temp file on error
        if not fd_closed:
            try:
                os.close(fd)
            except:
                pass
        try:
            os.unlink(temp_path)
        except:
            pass
        raise

    return p


def file_exists(p: str) -> bool:
    """True if *p* exists on the filesystem."""
    return Path(p).exists()


def fresh_store(
    site: str,
    fuel: int,
    *,
    oracle_backend: OracleBackend | None = None,
    oracle_backend_name: str = "litellm",
    readonly_dirs: list[str] | None = None,
) -> Store:
    """Create a new build store rooted at *site*."""
    ensure_dir(site)
    return {
        "site": site,
        "fuel": fuel,
        "status": "running",
        "value": None,
        "trace": [],
        "oracle-backend": oracle_backend,
        "oracle-backend-name": oracle_backend_name,
        "readonly-dirs": readonly_dirs or [],
        "run-id": str(uuid.uuid4()),
        "usage": {
            "total_cost_usd": 0.0,
            "total_input_tokens": 0,
            "total_output_tokens": 0,
            "by_rule": {},
        },
    }


# ── Fuel ──────────────────────────────────────────────────────────

def burn(S: Store, label: str) -> None:
    """Decrement fuel by one.  Raises Stop if fuel is exhausted."""
    S["fuel"] -= 1
    S["trace"].append({"event": "burn", "label": label, "fuel": S["fuel"]})
    if S["fuel"] < 0:
        S["status"] = "halted"
        S["value"] = f"fuel exhausted: {label}"
        raise Stop("halt", S["value"])


# ── Site inputs ───────────────────────────────────────────────────

def resolve_site_inputs(site_inputs: list | dict | None) -> dict[str, str]:
    """Normalize site_inputs to canonical dict form.

    **Beta Gate 95**: Unifies site_inputs handling across the codebase.
    Both list and dict forms remain valid in design.json, but this
    function provides a canonical dict representation.

    Parameters
    ----------
    site_inputs : list, dict, or None
        - List form: paths (absolute or basenames)
        - Dict form: {local_name: path}
        - None: treated as empty dict

    Returns
    -------
    dict
        Canonical mapping of local_name → path.
        - For list entries that are absolute paths: local_name is basename
        - For list entries that are relative/basenames: local_name is the entry itself
        - For dict entries: passed through as-is

    Notes
    -----
    This function does NOT validate paths or resolve them against design
    source directories. It only normalizes the data structure. Path
    validation and resolution happen in designs.ir.normalize_site_inputs()
    or build/run.py.

    Examples
    --------
    >>> resolve_site_inputs(None)
    {}
    >>> resolve_site_inputs(["/tmp/data.txt"])
    {"data.txt": "/tmp/data.txt"}
    >>> resolve_site_inputs(["prompt.txt"])
    {"prompt.txt": "prompt.txt"}
    >>> resolve_site_inputs({"input.txt": "/data/input.txt"})
    {"input.txt": "/data/input.txt"}
    """
    if site_inputs is None:
        return {}

    if isinstance(site_inputs, dict):
        return site_inputs.copy()

    # List form: extract local names
    result = {}
    for entry in site_inputs:
        p = Path(entry)
        if p.is_absolute():
            # Absolute path: local name is basename
            local_name = p.name
        else:
            # Relative path or basename: use as-is
            local_name = entry
        result[local_name] = entry

    return result


# ── File signatures ───────────────────────────────────────────────

def setup_links(site: str, mapping: dict[str, str]) -> list[str]:
    """Create read-only symlinks in *site* for each name→path entry.

    **Beta Gate B4**: Validates import local names at runtime. Rejects internal
    paths (.traces, etc.), path traversal, and existing symlinks pointing to
    wrong targets.

    Parameters
    ----------
    site : str
        Absolute path to the site directory.
    mapping : dict
        Mapping of local names (relative to site) to external paths.

    Returns
    -------
    list of str
        Resolved absolute paths of the external targets (for read-only
        sandbox registration).

    Raises
    ------
    ValueError
        If local name is invalid, external path doesn't exist, or symlink
        collision is detected.
    """
    import os

    readonly_dirs: list[str] = []
    for local_name, ext_path in mapping.items():
        # Beta B4: Validate local name
        # Reject internal paths
        if local_name.startswith('.'):
            raise ValueError(
                f"setup_links: local name cannot start with '.': {local_name}"
            )
        # Reject path traversal
        if '..' in Path(local_name).parts:
            raise ValueError(
                f"setup_links: local name contains path traversal: {local_name}"
            )
        # Reject absolute paths
        if Path(local_name).is_absolute():
            raise ValueError(
                f"setup_links: local name must be relative: {local_name}"
            )

        link = Path(site) / local_name
        ext = Path(ext_path).resolve()

        # Check external path exists
        if not ext.exists():
            raise ValueError(
                f"setup_links: external path does not exist: {ext_path}"
            )

        # Beta B4: Handle existing links/files
        if link.is_symlink():
            # Symlink exists - verify it points to the correct target
            existing_target = link.resolve()
            if existing_target != ext:
                raise ValueError(
                    f"setup_links: symlink '{local_name}' already exists but "
                    f"points to wrong target (expected {ext}, got {existing_target})"
                )
            # Correct symlink already exists, skip creation
        elif link.exists():
            # Regular file/directory exists where we want to create a link
            raise ValueError(
                f"setup_links: cannot create import link '{local_name}' "
                f"(file or directory already exists at that path)"
            )
        else:
            # Create the symlink
            link.parent.mkdir(parents=True, exist_ok=True)
            os.symlink(str(ext), str(link))

        # Register the containing directory (not the file itself) so that
        # site_path's is_relative_to check passes for files inside it.
        rd = str(ext.parent) if ext.is_file() else str(ext)
        readonly_dirs.append(rd)
    return readonly_dirs


def file_sig(p: str) -> bytes:
    """Return the CSE bytes atom for a file: content hash or ABSENT.

    Directories, symlinks to directories, and missing paths all yield
    ABSENT. Only regular files are hashed. This matches the behavior
    of content_hash_or_absent in core.py.
    """
    path = Path(p)
    if path.is_file():
        return content_hash(path.read_bytes())
    return ABSENT
