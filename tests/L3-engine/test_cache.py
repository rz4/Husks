"""Tests for cache: cache_key, cache_get, cache_put, pending, list, clear, export/import."""

import json
import tarfile
from pathlib import Path

import pytest

from husks.engine import (
    cache_key, cache_dir, cache_get, cache_put, cache_put_pending,
    cache_promote_pending, cache_discard_pending,
    cache_list, cache_clear, cache_export, cache_import,
)
from husks.seal import site_path, write_text, fresh_store


def _oracle_recipe(prompt="test"):
    return {"type": "oracle", "name": "gen", "prompt": prompt, "tools": [], "fuel": 1}


def _setup_inputs(S, inputs=("input.txt",)):
    for name in inputs:
        write_text(site_path(S, name), f"content of {name}")
    return list(inputs)


class TestCacheKey:
    def test_deterministic(self):
        k1 = cache_key("abc", {"a.txt": "hash1"})
        k2 = cache_key("abc", {"a.txt": "hash1"})
        assert k1 == k2
        assert len(k1) == 64

    def test_different_recipe_different_key(self):
        k1 = cache_key("abc", {"a.txt": "hash1"})
        k2 = cache_key("def", {"a.txt": "hash1"})
        assert k1 != k2

    def test_different_inputs_different_key(self):
        k1 = cache_key("abc", {"a.txt": "hash1"})
        k2 = cache_key("abc", {"a.txt": "hash2"})
        assert k1 != k2


class TestCachePutGet:
    def test_round_trip(self, tmp_store):
        recipe = _oracle_recipe()
        inputs = _setup_inputs(tmp_store)
        outputs = {"out.txt": "hello world"}
        cache_put(tmp_store, recipe, inputs, outputs)
        result = cache_get(tmp_store, recipe, inputs, declared_outputs=["out.txt"])
        assert result == outputs

    def test_miss_on_different_recipe(self, tmp_store):
        recipe1 = _oracle_recipe("prompt1")
        recipe2 = _oracle_recipe("prompt2")
        inputs = _setup_inputs(tmp_store)
        cache_put(tmp_store, recipe1, inputs, {"out.txt": "content"})
        assert cache_get(tmp_store, recipe2, inputs) is None

    def test_miss_on_different_inputs(self, tmp_store):
        recipe = _oracle_recipe()
        inputs = _setup_inputs(tmp_store)
        cache_put(tmp_store, recipe, inputs, {"out.txt": "content"})
        # Change input content
        write_text(site_path(tmp_store, "input.txt"), "modified")
        assert cache_get(tmp_store, recipe, inputs) is None

    def test_action_recipe_not_cached(self, tmp_store):
        recipe = {"type": "action", "fn": lambda S: None}
        inputs = _setup_inputs(tmp_store)
        cache_put(tmp_store, recipe, inputs, {"out.txt": "x"})
        assert cache_get(tmp_store, recipe, inputs) is None

    def test_none_recipe_not_cached(self, tmp_store):
        cache_put(tmp_store, None, [], {"out.txt": "x"})
        assert cache_get(tmp_store, None, []) is None

    def test_output_mismatch_rejected(self, tmp_store):
        recipe = _oracle_recipe()
        inputs = _setup_inputs(tmp_store)
        cache_put(tmp_store, recipe, inputs, {"out.txt": "content"})
        # Request with different declared outputs
        assert cache_get(tmp_store, recipe, inputs, declared_outputs=["other.txt"]) is None

    def test_tampered_content_rejected(self, tmp_store):
        recipe = _oracle_recipe()
        inputs = _setup_inputs(tmp_store)
        cache_put(tmp_store, recipe, inputs, {"out.txt": "original"})
        # Tamper with cached content
        cdir = cache_dir(tmp_store, cache_key(
            __import__("husks.kernel", fromlist=["recipe_digest"]).recipe_digest(
                __import__("husks.forms", fromlist=["recipe_to_cse"]).recipe_to_cse(recipe)),
            {i: __import__("husks.seal", fromlist=["file_sig"]).file_sig(site_path(tmp_store, i)).decode()
             for i in sorted(inputs)}
        ))
        outputs_file = Path(cdir) / "outputs.json"
        outputs_file.write_text(json.dumps({"out.txt": "tampered"}))
        assert cache_get(tmp_store, recipe, inputs) is None


class TestCachePending:
    def test_pending_not_servable(self, tmp_store):
        """Pending entries are not returned by cache_get."""
        recipe = _oracle_recipe()
        inputs = _setup_inputs(tmp_store)
        cache_put_pending(tmp_store, recipe, inputs, {"out.txt": "pending"})
        assert cache_get(tmp_store, recipe, inputs) is None

    def test_promote_makes_servable(self, tmp_store):
        recipe = _oracle_recipe()
        inputs = _setup_inputs(tmp_store)
        cache_put_pending(tmp_store, recipe, inputs, {"out.txt": "promoted"})
        promoted = cache_promote_pending(tmp_store)
        assert promoted == 1
        result = cache_get(tmp_store, recipe, inputs)
        assert result == {"out.txt": "promoted"}

    def test_discard_removes_pending(self, tmp_store):
        recipe = _oracle_recipe()
        inputs = _setup_inputs(tmp_store)
        cache_put_pending(tmp_store, recipe, inputs, {"out.txt": "discard me"})
        cache_discard_pending(tmp_store)
        assert cache_promote_pending(tmp_store) == 0

    def test_promote_foreign_orphan_gc(self, tmp_store):
        """Pending entries from other runs are GC'd during promotion."""
        recipe = _oracle_recipe()
        inputs = _setup_inputs(tmp_store)
        cache_put_pending(tmp_store, recipe, inputs, {"out.txt": "orphan"})
        # Change run-id to simulate a different run
        tmp_store["run-id"] = "different-run-id"
        promoted = cache_promote_pending(tmp_store)
        assert promoted == 0


class TestCacheListClear:
    def test_list_empty(self, tmp_store):
        assert cache_list(tmp_store) == []

    def test_list_after_put(self, tmp_store):
        recipe = _oracle_recipe()
        inputs = _setup_inputs(tmp_store)
        cache_put(tmp_store, recipe, inputs, {"out.txt": "x"})
        entries = cache_list(tmp_store)
        assert len(entries) == 1
        assert "key" in entries[0]
        assert entries[0]["reuse_count"] == 0

    def test_clear(self, tmp_store):
        recipe = _oracle_recipe()
        inputs = _setup_inputs(tmp_store)
        cache_put(tmp_store, recipe, inputs, {"out.txt": "x"})
        removed = cache_clear(tmp_store)
        assert removed >= 1
        assert cache_list(tmp_store) == []


class TestCacheExportImport:
    def test_round_trip(self, tmp_store, tmp_path):
        recipe = _oracle_recipe()
        inputs = _setup_inputs(tmp_store)
        cache_put(tmp_store, recipe, inputs, {"out.txt": "exported"})
        archive = str(tmp_path / "cache.tar.gz")
        exported = cache_export(tmp_store, archive)
        assert exported == 1

        # Import into fresh store
        site2 = str(tmp_path / "site2")
        S2 = fresh_store(site2, fuel=5)
        _setup_inputs(S2)
        imported = cache_import(S2, archive)
        assert imported == 1
        result = cache_get(S2, recipe, inputs)
        assert result == {"out.txt": "exported"}

    def test_import_rejects_path_traversal(self, tmp_store, tmp_path):
        """Tarball with .. paths is rejected."""
        archive = str(tmp_path / "bad.tar.gz")
        with tarfile.open(archive, "w:gz") as tar:
            import io
            data = b"{}"
            info = tarfile.TarInfo(name="../escape/outputs.json")
            info.size = len(data)
            tar.addfile(info, fileobj=io.BytesIO(data))
        with pytest.raises(ValueError, match="path traversal"):
            cache_import(tmp_store, archive)

    def test_import_rejects_symlinks(self, tmp_store, tmp_path):
        archive = str(tmp_path / "bad.tar.gz")
        with tarfile.open(archive, "w:gz") as tar:
            info = tarfile.TarInfo(name="link")
            info.type = tarfile.SYMTYPE
            info.linkname = "/etc/passwd"
            tar.addfile(info)
        with pytest.raises(ValueError, match="symlink"):
            cache_import(tmp_store, archive)

    def test_export_deterministic(self, tmp_store, tmp_path):
        """Two exports produce archives with identical tar content."""
        recipe = _oracle_recipe()
        inputs = _setup_inputs(tmp_store)
        cache_put(tmp_store, recipe, inputs, {"out.txt": "det"})
        a1 = str(tmp_path / "cache.tar.gz")
        a2 = str(tmp_path / "cache.tar.gz")  # same name avoids gzip header diff
        cache_export(tmp_store, a1)
        content1 = Path(a1).read_bytes()
        cache_export(tmp_store, a2)
        content2 = Path(a2).read_bytes()
        assert content1 == content2
