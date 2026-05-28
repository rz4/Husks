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
    """
    site = Path(S["site"]).resolve()
    if write and "stage" in S:
        base = Path(S["stage"]).resolve()
    else:
        base = site
    target = (base / name).resolve()
    if not target.is_relative_to(base):
        if write:
            raise ValueError(f"path escapes site (write denied): {name}")
        # Allow paths that resolve into registered read-only dirs (imports)
        readonly_dirs = S.get("readonly-dirs", [])
        if not any(target.is_relative_to(Path(rd).resolve()) for rd in readonly_dirs):
            raise ValueError(f"path escapes site: {name}")
    return str(target)


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
    """Return the CSE bytes atom for a file: content hash or ABSENT."""
    path = Path(p)
    if path.exists():
        return content_hash(path.read_bytes())
    return ABSENT
