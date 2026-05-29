"""
test_cache_layout.py -- Beta Gate D1: Cache layout and key derivation.

Tests the beta cache module for deterministic key computation,
file-system layout, and metadata tracking.

Tests cover:
- Cache key determinism (same inputs -> same key)
- Cache put/get round-trip
- Oracle recipe caching
- Trial recipe caching (not yet implemented)
- Input signature changes invalidate cache
- Recipe changes invalidate cache
- Metadata tracking (reuse count, timestamps)
- Cache listing and clearing
"""

import tempfile
import shutil
import json
from pathlib import Path


def test_cache_key_determinism():
    """Same recipe and inputs produce same cache key."""
    from husks.build.cache import cache_key

    recipe_rd = "abc123"
    inputs = {"input1.txt": "hash1", "input2.txt": "hash2"}

    key1 = cache_key(recipe_rd, inputs)
    key2 = cache_key(recipe_rd, inputs)

    assert key1 == key2, "cache key should be deterministic"
    assert len(key1) == 64, "cache key should be SHA-256 hex (64 chars)"


def test_cache_key_input_order_independence():
    """Cache key is independent of input dict order."""
    from husks.build.cache import cache_key

    recipe_rd = "abc123"
    inputs1 = {"a.txt": "hash_a", "b.txt": "hash_b"}
    inputs2 = {"b.txt": "hash_b", "a.txt": "hash_a"}

    key1 = cache_key(recipe_rd, inputs1)
    key2 = cache_key(recipe_rd, inputs2)

    assert key1 == key2, "cache key should be independent of input order"


def test_cache_key_changes_with_recipe():
    """Different recipe produces different cache key."""
    from husks.build.cache import cache_key

    inputs = {"input.txt": "hash1"}
    key1 = cache_key("recipe_a", inputs)
    key2 = cache_key("recipe_b", inputs)

    assert key1 != key2, "different recipes should have different cache keys"


def test_cache_key_changes_with_inputs():
    """Different inputs produce different cache key."""
    from husks.build.cache import cache_key

    recipe_rd = "abc123"
    key1 = cache_key(recipe_rd, {"input.txt": "hash1"})
    key2 = cache_key(recipe_rd, {"input.txt": "hash2"})

    assert key1 != key2, "different input hashes should have different cache keys"


def test_cache_put_get_round_trip():
    """Cached outputs can be retrieved."""
    from husks.build import build, rule, oracle
    from husks.build.cache import cache_put, cache_get
    from husks.build.identity import recipe_to_cse
    from husks.core import recipe_digest

    tmpdir = tempfile.mkdtemp(prefix="d1-round-trip-")
    try:
        site = Path(tmpdir) / "site"
        site.mkdir()

        # Create input file
        (site / "input.txt").write_text("test input\n")

        # Oracle recipe
        recipe = {
            "type": "oracle",
            "name": "test_oracle",
            "prompt": "Generate output based on input.",
            "tools": [],
            "fuel": 8,
        }

        # Simulate oracle outputs
        outputs = {"output.txt": "generated output\n"}

        # Create minimal store
        S = {"site": str(site), "run-id": "test-run"}

        # Put outputs in cache
        cache_put(S, recipe, ["input.txt"], outputs)

        # Retrieve from cache
        cached = cache_get(S, recipe, ["input.txt"])

        assert cached is not None, "cache get should return cached outputs"
        assert cached == outputs, "cached outputs should match stored outputs"

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_cache_miss_on_changed_input():
    """Cache miss when input changes."""
    from husks.build.cache import cache_put, cache_get

    tmpdir = tempfile.mkdtemp(prefix="d1-miss-input-")
    try:
        site = Path(tmpdir) / "site"
        site.mkdir()

        # Create input
        (site / "input.txt").write_text("original\n")

        recipe = {
            "type": "oracle",
            "prompt": "test",
        }

        S = {"site": str(site), "run-id": "test-run"}

        # Cache with original input
        outputs = {"output.txt": "result\n"}
        cache_put(S, recipe, ["input.txt"], outputs)

        # Verify cache hit
        cached = cache_get(S, recipe, ["input.txt"])
        assert cached is not None

        # Change input
        (site / "input.txt").write_text("modified\n")

        # Cache miss
        cached = cache_get(S, recipe, ["input.txt"])
        assert cached is None, "cache should miss when input changes"

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_cache_miss_on_changed_recipe():
    """Cache miss when recipe changes."""
    from husks.build.cache import cache_put, cache_get

    tmpdir = tempfile.mkdtemp(prefix="d1-miss-recipe-")
    try:
        site = Path(tmpdir) / "site"
        site.mkdir()

        (site / "input.txt").write_text("data\n")

        recipe1 = {"type": "oracle", "prompt": "prompt A"}
        recipe2 = {"type": "oracle", "prompt": "prompt B"}

        S = {"site": str(site), "run-id": "test-run"}

        outputs = {"output.txt": "result\n"}
        cache_put(S, recipe1, ["input.txt"], outputs)

        # Cache hit with same recipe
        cached = cache_get(S, recipe1, ["input.txt"])
        assert cached is not None

        # Cache miss with different recipe
        cached = cache_get(S, recipe2, ["input.txt"])
        assert cached is None, "cache should miss when recipe changes"

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_cache_reuse_count_increments():
    """Reuse count increments on cache hits."""
    from husks.build.cache import cache_put, cache_get, cache_dir

    tmpdir = tempfile.mkdtemp(prefix="d1-reuse-count-")
    try:
        site = Path(tmpdir) / "site"
        site.mkdir()

        (site / "input.txt").write_text("data\n")

        recipe = {"type": "oracle", "prompt": "test"}
        outputs = {"output.txt": "result\n"}

        S = {"site": str(site), "run-id": "test-run"}

        # Put in cache
        cache_put(S, recipe, ["input.txt"], outputs)

        # Read initial metadata
        from husks.build.identity import recipe_to_cse
        from husks.core import recipe_digest
        recipe_form = recipe_to_cse(recipe)
        recipe_rd = recipe_digest(recipe_form)
        from husks.build.site import file_sig, site_path
        from husks.build.cache import cache_key
        input_sigs = {"input.txt": file_sig(site_path(S, "input.txt")).decode()}
        key = cache_key(recipe_rd, input_sigs)
        cdir = cache_dir(S, key)
        meta_file = Path(cdir) / "meta.json"
        meta = json.loads(meta_file.read_text())

        assert meta["reuse_count"] == 0, "initial reuse count should be 0"

        # Get from cache (first reuse)
        cache_get(S, recipe, ["input.txt"])
        meta = json.loads(meta_file.read_text())
        assert meta["reuse_count"] == 1, "reuse count should increment"

        # Get again (second reuse)
        cache_get(S, recipe, ["input.txt"])
        meta = json.loads(meta_file.read_text())
        assert meta["reuse_count"] == 2, "reuse count should increment again"

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_cache_metadata_tracking():
    """Cache metadata includes timestamps and run IDs."""
    from husks.build.cache import cache_put, cache_dir

    tmpdir = tempfile.mkdtemp(prefix="d1-metadata-")
    try:
        site = Path(tmpdir) / "site"
        site.mkdir()

        (site / "input.txt").write_text("data\n")

        recipe = {"type": "oracle", "prompt": "test"}
        outputs = {"output.txt": "result\n"}

        S = {"site": str(site), "run-id": "run-123"}

        cache_put(S, recipe, ["input.txt"], outputs)

        # Read metadata
        from husks.build.identity import recipe_to_cse
        from husks.core import recipe_digest
        recipe_form = recipe_to_cse(recipe)
        recipe_rd = recipe_digest(recipe_form)
        from husks.build.site import file_sig, site_path
        from husks.build.cache import cache_key
        input_sigs = {"input.txt": file_sig(site_path(S, "input.txt")).decode()}
        key = cache_key(recipe_rd, input_sigs)
        cdir = cache_dir(S, key)
        meta_file = Path(cdir) / "meta.json"
        meta = json.loads(meta_file.read_text())

        assert "created_ts" in meta, "metadata should include created_ts"
        assert "created_run_id" in meta, "metadata should include created_run_id"
        assert meta["created_run_id"] == "run-123"
        assert meta["recipe_digest"] == recipe_rd

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_cache_list():
    """Cache list returns all cache entries."""
    from husks.build.cache import cache_put, cache_list

    tmpdir = tempfile.mkdtemp(prefix="d1-list-")
    try:
        site = Path(tmpdir) / "site"
        site.mkdir()

        (site / "input1.txt").write_text("data1\n")
        (site / "input2.txt").write_text("data2\n")

        S = {"site": str(site), "run-id": "test-run"}

        # Put two cache entries
        recipe1 = {"type": "oracle", "prompt": "prompt A"}
        recipe2 = {"type": "oracle", "prompt": "prompt B"}

        cache_put(S, recipe1, ["input1.txt"], {"out.txt": "result1\n"})
        cache_put(S, recipe2, ["input2.txt"], {"out.txt": "result2\n"})

        # List cache
        entries = cache_list(S)

        assert len(entries) == 2, "cache list should return 2 entries"
        assert all("key" in e for e in entries), "entries should have key"
        assert all("recipe_digest" in e for e in entries), "entries should have recipe_digest"

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_cache_clear():
    """Cache clear removes all entries."""
    from husks.build.cache import cache_put, cache_list, cache_clear

    tmpdir = tempfile.mkdtemp(prefix="d1-clear-")
    try:
        site = Path(tmpdir) / "site"
        site.mkdir()

        (site / "input.txt").write_text("data\n")

        S = {"site": str(site), "run-id": "test-run"}

        recipe = {"type": "oracle", "prompt": "test"}
        cache_put(S, recipe, ["input.txt"], {"out.txt": "result\n"})

        # Verify cache has entries
        assert len(cache_list(S)) == 1

        # Clear cache
        count = cache_clear(S)
        assert count == 1, "cache clear should return number of entries removed"

        # Verify cache is empty
        assert len(cache_list(S)) == 0, "cache should be empty after clear"

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_action_recipes_not_cached():
    """Action recipes are not cached (oracle/trial only)."""
    from husks.build.cache import cache_put, cache_get

    tmpdir = tempfile.mkdtemp(prefix="d1-no-action-")
    try:
        site = Path(tmpdir) / "site"
        site.mkdir()

        (site / "input.txt").write_text("data\n")

        def my_action(S):
            pass

        recipe = {"type": "action", "fn": my_action}
        outputs = {"output.txt": "result\n"}

        S = {"site": str(site), "run-id": "test-run"}

        # Put should silently skip action recipes
        cache_put(S, recipe, ["input.txt"], outputs)

        # Get should return None
        cached = cache_get(S, recipe, ["input.txt"])
        assert cached is None, "action recipes should not be cached"

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_cache_directory_structure():
    """Cache creates correct directory structure."""
    from husks.build.cache import cache_put

    tmpdir = tempfile.mkdtemp(prefix="d1-structure-")
    try:
        site = Path(tmpdir) / "site"
        site.mkdir()

        (site / "input.txt").write_text("data\n")

        recipe = {"type": "oracle", "prompt": "test"}
        outputs = {"output.txt": "result\n"}

        S = {"site": str(site), "run-id": "test-run"}

        cache_put(S, recipe, ["input.txt"], outputs)

        # Verify structure
        cache_root = site / ".cache"
        assert cache_root.exists(), ".cache directory should exist"

        # Should have one cache entry directory
        entries = list(cache_root.iterdir())
        assert len(entries) == 1, "should have one cache entry"

        entry = entries[0]
        assert (entry / "outputs.json").exists(), "should have outputs.json"
        assert (entry / "meta.json").exists(), "should have meta.json"

        # Verify outputs content
        outputs_data = json.loads((entry / "outputs.json").read_text())
        assert outputs_data == outputs, "outputs.json should contain outputs"

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)
