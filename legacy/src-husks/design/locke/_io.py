"""
_io.py -- Design I/O operations.

Provides from_json, from_locke, to_json, and normalize_site_inputs functions.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

Design = dict[str, Any]


# ── Load / save ───────────────────────────────────────────────────

def from_json(path: str | Path) -> Design:
    """Load a design from a JSON file."""
    with open(path) as f:
        design = json.load(f)
    design["_source_path"] = str(Path(path).resolve())
    return design


def from_locke(path: str | Path) -> Design:
    """Load a design from a ``.locke`` file."""
    from ._resolver import from_file
    return from_file(str(path))


def normalize_site_inputs(
    site_inputs: list[str] | dict[str, str] | None,
    design_source_path: str | None = None,
) -> dict[str, str]:
    """Normalize site_inputs to a dict of local_name → resolved_path.

    **Beta Gate A1/A2**: Resolves relative paths against the design file's
    directory and validates that all declared inputs exist.

    Parameters
    ----------
    site_inputs : list, dict, or None
        - List form: ["prompt.txt", "/abs/path.txt"]
          Relative paths are resolved against design_source_path.
          Absolute paths are used as-is.
          Local name is the basename for absolute paths, or the full relative
          path for relative paths.
        - Dict form: {"local_name": "source_path"}
          Source paths are resolved against design_source_path if relative.
        - None: returns empty dict

    design_source_path : str, optional
        Path to the design.json file (from design["_source_path"]).
        Required for resolving relative paths.

    Returns
    -------
    dict
        Mapping of local_name (relative path in site) → resolved_absolute_path.

    Raises
    ------
    ValueError
        If a relative path is given without design_source_path, or if a
        declared input file does not exist.

    Examples
    --------
    >>> # List form with relative path
    >>> normalize_site_inputs(["prompt.txt"], "/path/to/design.json")
    {"prompt.txt": "/path/to/prompt.txt"}

    >>> # Dict form with explicit mapping
    >>> normalize_site_inputs({"input.txt": "data.txt"}, "/path/to/design.json")
    {"input.txt": "/path/to/data.txt"}

    >>> # Absolute path
    >>> normalize_site_inputs(["/tmp/data.txt"], None)
    {"data.txt": "/tmp/data.txt"}
    """
    if site_inputs is None:
        return {}

    design_dir = None
    if design_source_path:
        design_dir = Path(design_source_path).parent.resolve()

    result = {}

    if isinstance(site_inputs, list):
        for entry in site_inputs:
            p = Path(entry)
            if p.is_absolute():
                # Absolute path: local name is basename
                local_name = p.name
                resolved = p.resolve()
            else:
                # Relative path: resolve against design directory
                if design_dir is None:
                    raise ValueError(
                        f"Relative site_input '{entry}' requires design source path"
                    )
                local_name = entry
                resolved = (design_dir / entry).resolve()

            # Validate that the file exists
            if not resolved.exists():
                raise ValueError(
                    f"Declared site_input does not exist: {entry}\n"
                    f"  Resolved path: {resolved}"
                )

            result[local_name] = str(resolved)

    elif isinstance(site_inputs, dict):
        for local_name, source_path in site_inputs.items():
            p = Path(source_path)
            if p.is_absolute():
                resolved = p.resolve()
            else:
                if design_dir is None:
                    raise ValueError(
                        f"Relative site_input source '{source_path}' requires design source path"
                    )
                resolved = (design_dir / source_path).resolve()

            # Validate that the file exists
            if not resolved.exists():
                raise ValueError(
                    f"Declared site_input does not exist: {source_path}\n"
                    f"  Local name: {local_name}\n"
                    f"  Resolved path: {resolved}"
                )

            result[local_name] = str(resolved)

    return result


def to_json(design: Design, path: str | Path | None = None) -> str:
    """Serialize a design to JSON.  If *path* is given, write to file."""
    s = json.dumps(design, indent=2)
    if path:
        with open(path, "w") as f:
            f.write(s)
    return s
