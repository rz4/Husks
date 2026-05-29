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
    """Export cache to a tarball for cross-machine transfer (Beta Gate D3/D7).

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
    import io

    cache_root = Path(site_path(S, ".cache"))

    # Beta Gate D7: Collect entry metadata for manifest
    entries = []
    if cache_root.exists():
        for entry_dir in cache_root.iterdir():
            if not entry_dir.is_dir():
                continue
            entries.append(entry_dir.name)

    # Beta Gate D7: Create provenance manifest
    manifest = {
        "cache_format_version": "1.0",
        "created_ts": time.time(),
        "entry_count": len(entries),
        "entry_keys": sorted(entries),
        "source_site_root": S.get("build-root"),
    }

    count = 0
    with tarfile.open(export_path, "w:gz") as tar:
        # Add manifest first
        manifest_json = json.dumps(manifest, indent=2).encode()
        manifest_info = tarfile.TarInfo(name="MANIFEST.json")
        manifest_info.size = len(manifest_json)
        tar.addfile(manifest_info, fileobj=io.BytesIO(manifest_json))

        # Add cache entries
        if cache_root.exists():
            for entry_dir in cache_root.iterdir():
                if not entry_dir.is_dir():
                    continue
                # Add entry directory with relative path for portability
                tar.add(entry_dir, arcname=entry_dir.name)
                count += 1

    return count


def cache_import(S: Store, import_path: str, *, merge: bool = True) -> int:
    """Import cache from a tarball (Beta Gate D3/D4).

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

    Raises
    ------
    ValueError
        If tarball contains unsafe members (absolute paths, .., symlinks, etc.)
    """
    import shutil
    import os

    cache_root = Path(site_path(S, ".cache"))

    # Clear existing cache if not merging
    if not merge and cache_root.exists():
        shutil.rmtree(cache_root)

    ensure_dir(str(cache_root))

    # Beta Gate D4: Safe tar import - validate all members before extraction
    # Beta Gate D7: Validate manifest first
    MAX_MEMBER_SIZE = 100 * 1024 * 1024  # 100 MB per member
    ALLOWED_EXTENSIONS = {".json"}

    with tarfile.open(import_path, "r:gz") as tar:
        members_to_extract = []
        manifest = None

        # Beta Gate D7: Extract and validate manifest first
        for member in tar.getmembers():
            if member.name == "MANIFEST.json":
                if member.size > 1024 * 1024:  # 1MB max for manifest
                    raise ValueError("cache import rejected: manifest too large")
                manifest_file = tar.extractfile(member)
                if manifest_file:
                    try:
                        manifest = json.loads(manifest_file.read().decode())
                        # Validate manifest structure
                        if "cache_format_version" not in manifest:
                            raise ValueError("cache import rejected: manifest missing format version")
                        if "entry_count" not in manifest:
                            raise ValueError("cache import rejected: manifest missing entry count")
                        # Version check (currently only support 1.0)
                        if manifest["cache_format_version"] != "1.0":
                            raise ValueError(
                                f"cache import rejected: unsupported cache format version "
                                f"{manifest['cache_format_version']} (expected 1.0)"
                            )
                    except json.JSONDecodeError as e:
                        raise ValueError(f"cache import rejected: invalid manifest JSON: {e}")
                break

        # Manifest is optional for backward compatibility, but if present, must be valid
        # If no manifest found, continue with validation

        for member in tar.getmembers():
            # Skip manifest (already validated)
            if member.name == "MANIFEST.json":
                continue

            # Reject absolute paths
            if os.path.isabs(member.name):
                raise ValueError(
                    f"cache import rejected: absolute path '{member.name}' (security violation)"
                )

            # Reject path traversal (..)
            if ".." in Path(member.name).parts:
                raise ValueError(
                    f"cache import rejected: path traversal '..' in '{member.name}' (security violation)"
                )

            # Reject symlinks
            if member.issym() or member.islnk():
                raise ValueError(
                    f"cache import rejected: symlink '{member.name}' (security violation)"
                )

            # Reject special files (devices, FIFOs, etc.)
            if not (member.isfile() or member.isdir()):
                raise ValueError(
                    f"cache import rejected: special file '{member.name}' (security violation)"
                )

            # Reject oversized members
            if member.size > MAX_MEMBER_SIZE:
                raise ValueError(
                    f"cache import rejected: oversized file '{member.name}' "
                    f"({member.size} bytes > {MAX_MEMBER_SIZE} max)"
                )

            # Validate file structure: <cache_key>/{outputs.json,seal.json,meta.json}
            parts = Path(member.name).parts
            if len(parts) > 2:
                raise ValueError(
                    f"cache import rejected: unexpected nesting '{member.name}' "
                    f"(expected <cache_key>/<file>.json)"
                )

            if member.isfile():
                # Must be within a cache entry directory
                if len(parts) != 2:
                    raise ValueError(
                        f"cache import rejected: file not in cache entry '{member.name}'"
                    )

                cache_key, filename = parts

                # Validate cache key is hex (sha256 = 64 chars)
                if not (len(cache_key) == 64 and all(c in "0123456789abcdef" for c in cache_key)):
                    raise ValueError(
                        f"cache import rejected: invalid cache key '{cache_key}' "
                        f"(expected 64-char hex)"
                    )

                # Validate filename
                if filename not in {"outputs.json", "seal.json", "meta.json"}:
                    raise ValueError(
                        f"cache import rejected: unexpected file '{filename}' "
                        f"(expected outputs.json, seal.json, or meta.json)"
                    )

            elif member.isdir():
                # Top-level directories must be cache keys
                if len(parts) != 1:
                    raise ValueError(
                        f"cache import rejected: unexpected directory '{member.name}'"
                    )

                cache_key = parts[0]
                if not (len(cache_key) == 64 and all(c in "0123456789abcdef" for c in cache_key)):
                    raise ValueError(
                        f"cache import rejected: invalid cache key '{cache_key}' "
                        f"(expected 64-char hex)"
                    )

            members_to_extract.append(member)

        # All members validated - safe to extract
        count = 0
        for member in members_to_extract:
            tar.extract(member, path=cache_root, filter='data')  # Use 'data' filter for safety
            if member.isdir() and len(Path(member.name).parts) == 1:
                count += 1

    return count
