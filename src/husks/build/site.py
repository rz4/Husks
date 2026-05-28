"""Site helpers: Store, filesystem utilities, fuel."""

from __future__ import annotations

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
    """Write UTF-8 text to a file, creating parent directories.  Returns *p*."""
    pp = Path(p)
    ensure_dir(str(pp.parent))
    pp.write_text(str(s))
    return p


def file_exists(p: str) -> bool:
    """True if *p* exists on the filesystem."""
    return Path(p).exists()


def fresh_store(
    site: str,
    fuel: int,
    *,
    oracle_backend: OracleBackend | None = None,
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


# ── File signatures ───────────────────────────────────────────────

def setup_links(site: str, mapping: dict[str, str]) -> list[str]:
    """Create read-only symlinks in *site* for each name→path entry.

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
    """
    import os

    readonly_dirs: list[str] = []
    for local_name, ext_path in mapping.items():
        link = Path(site) / local_name
        # If the file already exists in the site (e.g. pre-created by
        # tests or a previous run), skip — don't clobber it.
        if link.exists() or link.is_symlink():
            continue
        ext = Path(ext_path).resolve()
        if not ext.exists():
            raise ValueError(
                f"setup_links: external path does not exist: {ext_path}"
            )
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
