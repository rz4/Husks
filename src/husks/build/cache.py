"""Beta cache for oracle/trial reuse (Beta Gate D).

Deterministic file-system cache storing realized outputs for oracle/trial
recipes. Cache keys are derived from recipe digest + input signatures,
enabling cross-machine and cross-run reuse when dependencies match.

Cache layout (within site/.cache/):
  {cache_key}/
    outputs.json      - output filename -> content mapping
    seal.json         - seal data (recipe_digest, inputs, outputs)
    meta.json         - usage metadata (created_ts, reuse_count, etc.)

Cache key derivation:
  cache_key = sha256(recipe_digest + sorted(input_name:input_hash))

Beta constraints:
  - Oracle/trial recipes only (action recipes not cached)
  - Text outputs only (binary outputs rejected)
  - Single-site cache (no distributed cache)
  - File-system only (no external cache backends)
"""

from __future__ import annotations

import hashlib
import json
import tarfile
import time
from pathlib import Path
from typing import Any

from husks.build.site import Store, Recipe, site_path, ensure_dir, read_text, write_text, file_sig
from husks.build.identity import recipe_to_cse
from husks.core import recipe_digest


def cache_key(recipe_rd: str, input_sigs: dict[str, str]) -> str:
    """Compute deterministic cache key from recipe digest and input signatures.

    Parameters
    ----------
    recipe_rd : str
        Recipe digest (hex string)
    input_sigs : dict[str, str]
        Input name -> content hash mapping

    Returns
    -------
    str
        SHA-256 hex digest suitable as cache directory name
    """
    # Sort inputs for determinism
    sorted_inputs = sorted(input_sigs.items())
    preimage = recipe_rd + "".join(f"{k}:{v}" for k, v in sorted_inputs)
    return hashlib.sha256(preimage.encode()).hexdigest()


def cache_dir(S: Store, key: str) -> str:
    """Path to cache entry directory for given key."""
    return site_path(S, f".cache/{key}")


def cache_get(
    S: Store,
    recipe: Recipe,
    inputs: list[str],
) -> dict[str, str] | None:
    """Retrieve cached outputs for a recipe if available.

    Parameters
    ----------
    S : Store
        Build store
    recipe : Recipe
        Recipe dict (must be oracle or trial)
    inputs : list[str]
        Input file paths relative to site

    Returns
    -------
    dict[str, str] | None
        Output name -> content mapping if cache hit, None otherwise
    """
    # Only cache oracle/trial recipes
    if recipe is None or recipe.get("type") not in ("oracle", "trial"):
        return None

    # Compute cache key
    recipe_form = recipe_to_cse(recipe)
    recipe_rd = recipe_digest(recipe_form)
    input_sigs = {
        i: file_sig(site_path(S, i)).decode() for i in sorted(inputs)
    }
    key = cache_key(recipe_rd, input_sigs)

    # Check if cache entry exists
    cdir = cache_dir(S, key)
    outputs_file = Path(cdir) / "outputs.json"
    meta_file = Path(cdir) / "meta.json"

    if not outputs_file.exists():
        return None

    try:
        # Load cached outputs
        outputs = json.loads(outputs_file.read_text())

        # Update reuse metadata
        if meta_file.exists():
            meta = json.loads(meta_file.read_text())
            meta["reuse_count"] = meta.get("reuse_count", 0) + 1
            meta["last_reuse_ts"] = time.time()
            meta["last_reuse_run_id"] = S["run-id"]
            meta_file.write_text(json.dumps(meta, indent=2))

        return outputs
    except Exception:
        return None


def cache_put(
    S: Store,
    recipe: Recipe,
    inputs: list[str],
    outputs: dict[str, str],
    *,
    seal_data: dict[str, Any] | None = None,
) -> None:
    """Store outputs in cache for future reuse.

    Parameters
    ----------
    S : Store
        Build store
    recipe : Recipe
        Recipe dict (must be oracle or trial)
    inputs : list[str]
        Input file paths relative to site
    outputs : dict[str, str]
        Output name -> content mapping
    seal_data : dict | None
        Optional seal data to store alongside outputs
    """
    # Only cache oracle/trial recipes
    if recipe is None or recipe.get("type") not in ("oracle", "trial"):
        return

    # Compute cache key
    recipe_form = recipe_to_cse(recipe)
    recipe_rd = recipe_digest(recipe_form)
    input_sigs = {
        i: file_sig(site_path(S, i)).decode() for i in sorted(inputs)
    }
    key = cache_key(recipe_rd, input_sigs)

    # Create cache entry directory
    cdir = cache_dir(S, key)
    ensure_dir(cdir)

    # Write outputs
    outputs_file = Path(cdir) / "outputs.json"
    outputs_file.write_text(json.dumps(outputs, indent=2))

    # Write seal if provided
    if seal_data:
        seal_file = Path(cdir) / "seal.json"
        seal_file.write_text(json.dumps(seal_data, indent=2))

    # Write metadata
    meta = {
        "created_ts": time.time(),
        "created_run_id": S["run-id"],
        "reuse_count": 0,
        "recipe_digest": recipe_rd,
    }
    meta_file = Path(cdir) / "meta.json"
    meta_file.write_text(json.dumps(meta, indent=2))


def cache_list(S: Store) -> list[dict[str, Any]]:
    """List all cache entries with metadata.

    Returns
    -------
    list[dict]
        List of cache entry metadata dicts with keys:
        - key: cache key
        - recipe_digest: recipe digest
        - created_ts: creation timestamp
        - reuse_count: number of times reused
        - last_reuse_ts: last reuse timestamp (if reused)
    """
    cache_root = Path(site_path(S, ".cache"))
    if not cache_root.exists():
        return []

    entries = []
    for entry_dir in cache_root.iterdir():
        if not entry_dir.is_dir():
            continue

        meta_file = entry_dir / "meta.json"
        if not meta_file.exists():
            continue

        try:
            meta = json.loads(meta_file.read_text())
            meta["key"] = entry_dir.name
            entries.append(meta)
        except Exception:
            continue

    return sorted(entries, key=lambda e: e.get("created_ts", 0), reverse=True)


def cache_clear(S: Store) -> int:
    """Clear all cache entries.

    Returns
    -------
    int
        Number of cache entries removed
    """
    import shutil

    cache_root = Path(site_path(S, ".cache"))
    if not cache_root.exists():
        return 0

    count = 0
    for entry_dir in cache_root.iterdir():
        if entry_dir.is_dir():
            shutil.rmtree(entry_dir)
            count += 1

    return count


def cache_export(S: Store, export_path: str) -> int:
    """Export cache to a tarball for cross-machine transfer (Beta Gate D3).

    Parameters
    ----------
    S : Store
        Build store
    export_path : str
        Path to write .tar.gz archive

    Returns
    -------
    int
        Number of cache entries exported
    """
    cache_root = Path(site_path(S, ".cache"))

    count = 0
    with tarfile.open(export_path, "w:gz") as tar:
        if cache_root.exists():
            for entry_dir in cache_root.iterdir():
                if not entry_dir.is_dir():
                    continue
                # Add entry directory with relative path for portability
                tar.add(entry_dir, arcname=entry_dir.name)
                count += 1

    return count


def cache_import(S: Store, import_path: str, *, merge: bool = True) -> int:
    """Import cache from a tarball (Beta Gate D3).

    Parameters
    ----------
    S : Store
        Build store
    import_path : str
        Path to .tar.gz archive
    merge : bool
        If True, merge with existing cache (default).
        If False, clear existing cache before import.

    Returns
    -------
    int
        Number of cache entries imported
    """
    import shutil

    cache_root = Path(site_path(S, ".cache"))

    # Clear existing cache if not merging
    if not merge and cache_root.exists():
        shutil.rmtree(cache_root)

    ensure_dir(str(cache_root))

    count = 0
    with tarfile.open(import_path, "r:gz") as tar:
        for member in tar.getmembers():
            if member.isdir() and "/" not in member.name:
                # Top-level directory is a cache entry
                tar.extract(member, path=cache_root)
                count += 1
            elif member.isfile():
                # File within a cache entry
                tar.extract(member, path=cache_root)

    return count
