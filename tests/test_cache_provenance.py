"""
test_cache_provenance.py -- Beta Gate D7: Cache provenance in exports.

Tests that cache exports include a manifest with:
- Cache format version
- Created timestamp
- Entry count
- Entry keys (cache keys)
- Optional source site root

And that imports validate the manifest.
"""

import json
import tarfile
import tempfile
import shutil
import time
from pathlib import Path

from husks.build import build, rule, oracle
from husks.build.site import fresh_store
from husks.build.cache import cache_export, cache_import


def test_export_includes_manifest():
    """Cache export includes MANIFEST.json with provenance."""
    tmpdir = tempfile.mkdtemp(prefix="cache-manifest-")
    try:
        site = Path(tmpdir) / "site"
        site.mkdir()

        # Build with oracle to populate cache
        node = rule("test", outputs=["out.txt"], recipe=oracle("Say hello", fuel=5))
        S = build("test", 10, node, site=str(site))

        # Export cache
        export_file = Path(tmpdir) / "cache.tar.gz"
        count = cache_export(S, str(export_file))
        assert count == 1

        # Verify manifest exists in tarball
        with tarfile.open(export_file, "r:gz") as tar:
            members = {m.name for m in tar.getmembers()}
            assert "MANIFEST.json" in members, "Export should include MANIFEST.json"

            # Extract and validate manifest
            manifest_member = tar.getmember("MANIFEST.json")
            manifest_file = tar.extractfile(manifest_member)
            manifest = json.loads(manifest_file.read().decode())

            # Validate structure
            assert "cache_format_version" in manifest
            assert manifest["cache_format_version"] == "1.0"

            assert "created_ts" in manifest
            assert isinstance(manifest["created_ts"], (int, float))
            assert manifest["created_ts"] > 0

            assert "entry_count" in manifest
            assert manifest["entry_count"] == 1

            assert "entry_keys" in manifest
            assert len(manifest["entry_keys"]) == 1
            cache_key = manifest["entry_keys"][0]
            assert len(cache_key) == 64  # SHA-256 hex
            assert all(c in "0123456789abcdef" for c in cache_key)

            assert "source_site_root" in manifest
            # Root may be present if build completed

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_import_validates_manifest():
    """Cache import validates manifest version."""
    tmpdir = tempfile.mkdtemp(prefix="cache-manifest-val-")
    try:
        # Create tarball with invalid manifest
        bad_tar = Path(tmpdir) / "bad.tar.gz"
        with tarfile.open(bad_tar, "w:gz") as tar:
            # Add manifest with unsupported version
            manifest = {
                "cache_format_version": "2.0",  # Unsupported
                "entry_count": 0,
                "entry_keys": [],
            }
            manifest_json = json.dumps(manifest).encode()
            import io
            info = tarfile.TarInfo(name="MANIFEST.json")
            info.size = len(manifest_json)
            tar.addfile(info, fileobj=io.BytesIO(manifest_json))

        site = Path(tmpdir) / "site"
        site.mkdir()
        S = fresh_store(str(site), fuel=10)

        # Should reject unsupported version
        try:
            cache_import(S, str(bad_tar))
            assert False, "Should reject unsupported cache format version"
        except ValueError as e:
            assert "unsupported cache format version" in str(e).lower()

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_import_rejects_malformed_manifest():
    """Cache import rejects malformed manifest JSON."""
    tmpdir = tempfile.mkdtemp(prefix="cache-manifest-bad-")
    try:
        # Create tarball with malformed manifest
        bad_tar = Path(tmpdir) / "bad.tar.gz"
        with tarfile.open(bad_tar, "w:gz") as tar:
            # Add invalid JSON
            import io
            info = tarfile.TarInfo(name="MANIFEST.json")
            info.size = len(b"{invalid json")
            tar.addfile(info, fileobj=io.BytesIO(b"{invalid json"))

        site = Path(tmpdir) / "site"
        site.mkdir()
        S = fresh_store(str(site), fuel=10)

        # Should reject malformed JSON
        try:
            cache_import(S, str(bad_tar))
            assert False, "Should reject malformed manifest JSON"
        except ValueError as e:
            assert "invalid manifest json" in str(e).lower()

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_import_works_without_manifest():
    """Cache import works with old exports (no manifest) for backward compat."""
    tmpdir = tempfile.mkdtemp(prefix="cache-no-manifest-")
    try:
        # Create tarball without manifest (old format)
        cache_key = "a" * 64
        old_tar = Path(tmpdir) / "old.tar.gz"

        with tarfile.open(old_tar, "w:gz") as tar:
            # Add directory
            dir_info = tarfile.TarInfo(name=cache_key)
            dir_info.type = tarfile.DIRTYPE
            tar.addfile(dir_info)

            # Add outputs.json
            outputs = {"out.txt": "test content"}
            outputs_json = json.dumps(outputs).encode()
            import io
            out_info = tarfile.TarInfo(name=f"{cache_key}/outputs.json")
            out_info.size = len(outputs_json)
            tar.addfile(out_info, fileobj=io.BytesIO(outputs_json))

            # Add meta.json
            meta = {"created_ts": 123456789, "reuse_count": 0}
            meta_json = json.dumps(meta).encode()
            meta_info = tarfile.TarInfo(name=f"{cache_key}/meta.json")
            meta_info.size = len(meta_json)
            tar.addfile(meta_info, fileobj=io.BytesIO(meta_json))

        site = Path(tmpdir) / "site"
        site.mkdir()
        S = fresh_store(str(site), fuel=10)

        # Should accept old format without manifest
        count = cache_import(S, str(old_tar))
        assert count == 1, "Should import even without manifest (backward compat)"

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_roundtrip_with_manifest():
    """Full export/import roundtrip preserves cache with manifest."""
    tmpdir = tempfile.mkdtemp(prefix="cache-roundtrip-")
    try:
        site1 = Path(tmpdir) / "site1"
        site1.mkdir()

        # Build with oracle
        node = rule("worker", outputs=["result.txt"], recipe=oracle("Generate", fuel=5))
        S1 = build("test", 10, node, site=str(site1))

        # Export
        export_file = Path(tmpdir) / "cache.tar.gz"
        cache_export(S1, str(export_file))

        # Import to new site
        site2 = Path(tmpdir) / "site2"
        site2.mkdir()
        S2 = fresh_store(str(site2), fuel=10)
        cache_import(S2, str(export_file))

        # Rebuild - should use cache
        S2_rebuilt = build("test", 10, node, site=str(site2))

        # Should have zero cost (cache hit)
        assert S2_rebuilt["usage"]["total_cost_usd"] == 0.0

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)
