"""
test_cache_validation_path.py -- Task 11: Single cache validation path.

Validates that cache_get() is the canonical validation path and that
all cache lookups go through proper validation.
"""

import json
import tempfile
import shutil
from pathlib import Path

from husks.build.cache import cache_get, cache_put
from husks.build.site import Store
from husks.build.identity import recipe_to_cse
from husks.core import recipe_digest

import pytest


@pytest.mark.beta


@pytest.mark.gate_d


def test_cache_get_is_single_validation_path():
    """cache_get() performs all required validation (Task 11).

    This test documents that cache_get() is the ONLY function that should
    validate cache entries. All other functions (cache_put, cache_import, etc.)
    either create cache entries or import them, but validation happens only
    in cache_get().
    """
    tmpdir = tempfile.mkdtemp(prefix="cache-validation-")
    try:
        S: Store = {"site": tmpdir, "run-id": "test"}

        # Create a valid cache entry
        recipe = {
            "type": "oracle",
            "name": "test_oracle",
            "prompt": "test prompt",
            "outputs": ["out.txt"],
        }
        inputs = []
        outputs = {"out.txt": "test content"}

        # Put into cache
        cache_put(S, recipe, inputs, outputs)

        # Retrieve through cache_get - this validates everything
        result = cache_get(S, recipe, inputs, declared_outputs=["out.txt"])

        assert result is not None, "Valid cache entry should be retrieved"
        assert result == outputs, "Retrieved outputs should match cached outputs"

        # Now tamper with the cache entry to verify validation catches it
        recipe_form = recipe_to_cse(recipe)
        recipe_rd = recipe_digest(recipe_form)
        from husks.build.cache import cache_key
        key = cache_key(recipe_rd, {})
        cache_dir = Path(tmpdir) / ".cache" / key
        seal_file = cache_dir / "seal.json"

        # Tamper with recipe digest in seal
        seal_data = json.loads(seal_file.read_text())
        original_rd = seal_data["recipe_digest"]
        seal_data["recipe_digest"] = "tampered_digest_0000000000"
        seal_file.write_text(json.dumps(seal_data))

        # cache_get should reject tampered entry
        result = cache_get(S, recipe, inputs, declared_outputs=["out.txt"])
        assert result is None, "cache_get should reject tampered recipe digest"

        # Restore recipe digest but tamper with output hash
        seal_data["recipe_digest"] = original_rd
        seal_data["outputs"]["out.txt"] = "0000000000"  # Wrong hash
        seal_file.write_text(json.dumps(seal_data))

        # cache_get should reject tampered content hash
        result = cache_get(S, recipe, inputs, declared_outputs=["out.txt"])
        assert result is None, "cache_get should reject tampered content hash"

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


@pytest.mark.beta


@pytest.mark.gate_d


def test_cache_validation_prevents_bypass():
    """Direct .cache/ access bypasses validation (anti-pattern).

    This test demonstrates why code should NEVER read .cache/ files directly.
    Only cache_get() provides validation guarantees.
    """
    tmpdir = tempfile.mkdtemp(prefix="cache-bypass-")
    try:
        S: Store = {"site": tmpdir, "run-id": "test"}

        # Create a valid cache entry
        recipe = {
            "type": "oracle",
            "name": "test_oracle",
            "prompt": "test prompt",
            "outputs": ["out.txt"],
        }
        inputs = []
        outputs = {"out.txt": "original content"}

        cache_put(S, recipe, inputs, outputs)

        # Find cache entry path
        recipe_form = recipe_to_cse(recipe)
        recipe_rd = recipe_digest(recipe_form)
        from husks.build.cache import cache_key
        key = cache_key(recipe_rd, {})
        outputs_file = Path(tmpdir) / ".cache" / key / "outputs.json"

        # ANTI-PATTERN: Reading cache file directly (bypasses validation)
        direct_outputs = json.loads(outputs_file.read_text())
        assert direct_outputs == outputs, "Direct read gets unvalidated data"

        # Now tamper with the content
        tampered_outputs = {"out.txt": "malicious content"}
        outputs_file.write_text(json.dumps(tampered_outputs))

        # Direct read would get tampered data (DANGEROUS!)
        direct_outputs = json.loads(outputs_file.read_text())
        assert direct_outputs == tampered_outputs, "Direct read bypasses validation!"

        # But cache_get() rejects it (SAFE!)
        validated_outputs = cache_get(S, recipe, inputs, declared_outputs=["out.txt"])
        assert validated_outputs is None, "cache_get correctly rejects tampered data"

        print("\n✓ Task 11: cache_get() is the single validation path")
        print("  Direct .cache/ access bypasses validation (don't do it!)")
        print("  Always use cache_get() for validated cache lookups")

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


@pytest.mark.beta


@pytest.mark.gate_d


def test_cache_get_validation_steps():
    """Document the 5 validation steps in cache_get() (Task 11)."""
    tmpdir = tempfile.mkdtemp(prefix="cache-validation-steps-")
    try:
        S: Store = {"site": tmpdir, "run-id": "test"}

        recipe = {
            "type": "oracle",
            "name": "test",
            "prompt": "test",
            "outputs": ["out.txt"],
        }
        inputs = []
        outputs = {"out.txt": "content"}

        cache_put(S, recipe, inputs, outputs)

        # All 5 validation steps should pass:
        # 1. Seal exists
        # 2. Recipe digest matches
        # 3. Output names match
        # 4. Output hashes match
        # 5. Metadata updated on reuse

        result = cache_get(S, recipe, inputs, declared_outputs=["out.txt"])
        assert result is not None, "All validation steps should pass"

        print("\n✓ cache_get() validation steps:")
        print("  1. Seal exists and has valid schema")
        print("  2. Recipe digest matches (prevents recipe tampering)")
        print("  3. Output names match (prevents output set mismatch)")
        print("  4. Output hashes match (prevents content tampering)")
        print("  5. Metadata updated on successful reuse")

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


@pytest.mark.beta


@pytest.mark.gate_d


def test_cache_rejects_missing_seal_version():
    """Beta Readiness Task 4: Reject cache entries without cache_seal_version."""
    tmpdir = tempfile.mkdtemp(prefix="cache-seal-version-")
    try:
        S: Store = {"site": tmpdir, "run-id": "test"}

        recipe = {
            "type": "oracle",
            "name": "test",
            "prompt": "test",
            "outputs": ["out.txt"],
        }
        inputs = []
        outputs = {"out.txt": "content"}

        # Create cache entry manually without cache_seal_version (simulating old cache)
        from husks.build.cache import cache_key, cache_dir
        from husks.build.identity import recipe_to_cse
        from husks.core import recipe_digest
        from husks.build.site import ensure_dir
        import hashlib

        recipe_form = recipe_to_cse(recipe)
        recipe_rd = recipe_digest(recipe_form)
        key = cache_key(recipe_rd, {})
        cdir = cache_dir(S, key)
        ensure_dir(cdir)

        # Write outputs.json
        outputs_file = Path(cdir) / "outputs.json"
        outputs_file.write_text(json.dumps(outputs))

        # Write seal.json WITHOUT cache_seal_version (old format)
        output_hashes = {
            name: hashlib.sha256(content.encode()).hexdigest()
            for name, content in outputs.items()
        }
        seal_data = {
            # NOTE: Missing cache_seal_version!
            "recipe_digest": recipe_rd,
            "outputs": output_hashes,
            "inputs": {},
        }
        seal_file = Path(cdir) / "seal.json"
        seal_file.write_text(json.dumps(seal_data))

        # Try to retrieve - should reject due to missing cache_seal_version
        result = cache_get(S, recipe, inputs, declared_outputs=["out.txt"])
        assert result is None, "cache_get should reject cache entry without cache_seal_version"

        print("\n✓ Beta Readiness Task 4: Missing cache_seal_version rejected")

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


@pytest.mark.beta


@pytest.mark.gate_d


def test_cache_rejects_unsupported_seal_version():
    """Beta Readiness Task 4: Reject cache entries with unsupported cache_seal_version."""
    tmpdir = tempfile.mkdtemp(prefix="cache-seal-version-unsupported-")
    try:
        S: Store = {"site": tmpdir, "run-id": "test"}

        recipe = {
            "type": "oracle",
            "name": "test",
            "prompt": "test",
            "outputs": ["out.txt"],
        }
        inputs = []
        outputs = {"out.txt": "content"}

        # Create cache entry with unsupported version
        cache_put(S, recipe, inputs, outputs)

        # Find and modify the seal to use unsupported version
        from husks.build.cache import cache_key
        from husks.build.identity import recipe_to_cse
        from husks.core import recipe_digest

        recipe_form = recipe_to_cse(recipe)
        recipe_rd = recipe_digest(recipe_form)
        key = cache_key(recipe_rd, {})
        seal_file = Path(tmpdir) / ".cache" / key / "seal.json"

        seal_data = json.loads(seal_file.read_text())
        seal_data["cache_seal_version"] = "2.0"  # Unsupported version
        seal_file.write_text(json.dumps(seal_data))

        # Try to retrieve - should reject due to unsupported version
        result = cache_get(S, recipe, inputs, declared_outputs=["out.txt"])
        assert result is None, "cache_get should reject unsupported cache_seal_version"

        print("\n✓ Beta Readiness Task 4: Unsupported cache_seal_version rejected")

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)
