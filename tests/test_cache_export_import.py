"""
test_cache_export_import.py -- Beta Gate D3: Cache export/import for cross-machine reuse.

Tests cache portability via export/import, enabling cross-machine
verification and cache sharing in the three-machine beta test.

Tests cover:
- Export cache to tarball
- Import cache from tarball
- Import merge with existing cache
- Import replace existing cache
- Cross-site cache transfer
- Empty cache export/import
"""

import tempfile
import shutil
from pathlib import Path


def test_cache_export():
    """Cache can be exported to tarball."""
    from husks.build import build, rule, oracle
    from husks.build.cache import cache_export

    tmpdir = tempfile.mkdtemp(prefix="d3-export-")
    try:
        site = Path(tmpdir) / "site"
        site.mkdir()

        (site / "input.txt").write_text("data\n")

        def stub_oracle(S, rule_name, recipe, outputs):
            from husks.build.site import write_text, site_path
            write_text(site_path(S, outputs[0], write=True), "result\n")
            return {"tokens_in": 100, "tokens_out": 50, "cost_usd": 0.001, "fuel_steps": 1}

        node = rule(
            "worker",
            inputs=["input.txt"],
            outputs=["output.txt"],
            recipe=oracle(prompt="Test", fuel=5),
        )

        S = build("demo", 10, node, site=str(site), oracle_backend=stub_oracle)

        # Export cache
        export_file = Path(tmpdir) / "cache.tar.gz"
        count = cache_export(S, str(export_file))

        assert count == 1, "should export 1 cache entry"
        assert export_file.exists(), "export file should be created"
        assert export_file.stat().st_size > 0, "export file should not be empty"

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_cache_import():
    """Cache can be imported from tarball."""
    from husks.build import build, rule, oracle
    from husks.build.cache import cache_export, cache_import, cache_list

    tmpdir = tempfile.mkdtemp(prefix="d3-import-")
    try:
        # Create site A with cache
        site_a = Path(tmpdir) / "site_a"
        site_a.mkdir()
        (site_a / "input.txt").write_text("data\n")

        def stub_oracle(S, rule_name, recipe, outputs):
            from husks.build.site import write_text, site_path
            write_text(site_path(S, outputs[0], write=True), "result\n")
            return {"tokens_in": 100, "tokens_out": 50, "cost_usd": 0.001, "fuel_steps": 1}

        node = rule(
            "worker",
            inputs=["input.txt"],
            outputs=["output.txt"],
            recipe=oracle(prompt="Test", fuel=5),
        )

        S_a = build("demo", 10, node, site=str(site_a), oracle_backend=stub_oracle)

        # Export cache from site A
        export_file = Path(tmpdir) / "cache.tar.gz"
        cache_export(S_a, str(export_file))

        # Create site B (empty cache)
        site_b = Path(tmpdir) / "site_b"
        site_b.mkdir()

        # Import cache to site B
        from husks.build import fresh_store
        S_b = fresh_store(str(site_b), fuel=10)
        count = cache_import(S_b, str(export_file))

        assert count == 1, "should import 1 cache entry"

        # Verify cache is available in site B
        entries = cache_list(S_b)
        assert len(entries) == 1, "site B should have 1 cache entry"

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_cache_import_merge():
    """Import merges with existing cache by default."""
    from husks.build import build, rule, oracle
    from husks.build.cache import cache_export, cache_import, cache_list

    tmpdir = tempfile.mkdtemp(prefix="d3-merge-")
    try:
        # Create site A with cache entry 1
        site_a = Path(tmpdir) / "site_a"
        site_a.mkdir()
        (site_a / "input1.txt").write_text("data1\n")

        def stub_oracle(S, rule_name, recipe, outputs):
            from husks.build.site import write_text, site_path
            write_text(site_path(S, outputs[0], write=True), f"result for {rule_name}\n")
            return {"tokens_in": 100, "tokens_out": 50, "cost_usd": 0.001, "fuel_steps": 1}

        node1 = rule(
            "worker1",
            inputs=["input1.txt"],
            outputs=["output1.txt"],
            recipe=oracle(prompt="Test 1", fuel=5),
        )

        S_a = build("demo", 10, node1, site=str(site_a), oracle_backend=stub_oracle)
        export1 = Path(tmpdir) / "cache1.tar.gz"
        cache_export(S_a, str(export1))

        # Create site B with cache entry 2
        site_b = Path(tmpdir) / "site_b"
        site_b.mkdir()
        (site_b / "input2.txt").write_text("data2\n")

        node2 = rule(
            "worker2",
            inputs=["input2.txt"],
            outputs=["output2.txt"],
            recipe=oracle(prompt="Test 2", fuel=5),
        )

        S_b = build("demo", 10, node2, site=str(site_b), oracle_backend=stub_oracle)

        # Import cache 1 into site B (merge)
        cache_import(S_b, str(export1), merge=True)

        # Should have both cache entries
        entries = cache_list(S_b)
        assert len(entries) == 2, "merge should preserve existing cache"

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_cache_import_replace():
    """Import can replace existing cache."""
    from husks.build import build, rule, oracle
    from husks.build.cache import cache_export, cache_import, cache_list

    tmpdir = tempfile.mkdtemp(prefix="d3-replace-")
    try:
        # Create site A with cache entry 1
        site_a = Path(tmpdir) / "site_a"
        site_a.mkdir()
        (site_a / "input1.txt").write_text("data1\n")

        def stub_oracle(S, rule_name, recipe, outputs):
            from husks.build.site import write_text, site_path
            write_text(site_path(S, outputs[0], write=True), f"result for {rule_name}\n")
            return {"tokens_in": 100, "tokens_out": 50, "cost_usd": 0.001, "fuel_steps": 1}

        node1 = rule(
            "worker1",
            inputs=["input1.txt"],
            outputs=["output1.txt"],
            recipe=oracle(prompt="Test 1", fuel=5),
        )

        S_a = build("demo", 10, node1, site=str(site_a), oracle_backend=stub_oracle)
        export1 = Path(tmpdir) / "cache1.tar.gz"
        cache_export(S_a, str(export1))

        # Create site B with cache entry 2
        site_b = Path(tmpdir) / "site_b"
        site_b.mkdir()
        (site_b / "input2.txt").write_text("data2\n")

        node2 = rule(
            "worker2",
            inputs=["input2.txt"],
            outputs=["output2.txt"],
            recipe=oracle(prompt="Test 2", fuel=5),
        )

        S_b = build("demo", 10, node2, site=str(site_b), oracle_backend=stub_oracle)

        # Verify site B has 1 cache entry
        assert len(cache_list(S_b)) == 1

        # Import cache 1 into site B (replace)
        cache_import(S_b, str(export1), merge=False)

        # Should have only cache entry from import
        entries = cache_list(S_b)
        assert len(entries) == 1, "replace should clear existing cache"

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_cross_site_cache_reuse():
    """Cache exported from one site can be used by another."""
    from husks.build import build, rule, oracle
    from husks.build.cache import cache_export, cache_import

    tmpdir = tempfile.mkdtemp(prefix="d3-cross-site-")
    try:
        # Site A: Build and cache
        site_a = Path(tmpdir) / "site_a"
        site_a.mkdir()
        (site_a / "input.txt").write_text("data\n")

        call_count = {"n": 0}
        def counting_oracle(S, rule_name, recipe, outputs):
            call_count["n"] += 1
            from husks.build.site import write_text, site_path
            write_text(site_path(S, outputs[0], write=True), "oracle result\n")
            return {"tokens_in": 100, "tokens_out": 50, "cost_usd": 0.001, "fuel_steps": 1}

        node = rule(
            "worker",
            inputs=["input.txt"],
            outputs=["output.txt"],
            recipe=oracle(prompt="Test", fuel=5),
        )

        # First build on site A
        S_a = build("demo", 10, node, site=str(site_a), oracle_backend=counting_oracle)
        assert call_count["n"] == 1

        # Export cache from site A
        export_file = Path(tmpdir) / "cache.tar.gz"
        cache_export(S_a, str(export_file))

        # Site B: Import cache and reuse
        site_b = Path(tmpdir) / "site_b"
        site_b.mkdir()
        (site_b / "input.txt").write_text("data\n")

        # Import cache before build
        from husks.build import fresh_store
        S_b = fresh_store(str(site_b), fuel=10, oracle_backend=counting_oracle)
        cache_import(S_b, str(export_file))

        # Build on site B (should use cache, not call oracle)
        from husks.build import commit
        from husks.build.eval import eval_node
        eval_node(S_b, node)

        # Oracle should not be called on site B (cache hit)
        assert call_count["n"] == 1, "site B should reuse cache from site A"
        assert (site_b / "output.txt").read_text() == "oracle result\n"

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_empty_cache_export():
    """Empty cache exports empty tarball."""
    from husks.build.cache import cache_export
    from husks.build import fresh_store

    tmpdir = tempfile.mkdtemp(prefix="d3-empty-export-")
    try:
        site = Path(tmpdir) / "site"
        site.mkdir()

        S = fresh_store(str(site), fuel=10)

        export_file = Path(tmpdir) / "cache.tar.gz"
        count = cache_export(S, str(export_file))

        assert count == 0, "empty cache should export 0 entries"
        assert export_file.exists(), "export file should be created even if empty"

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_empty_cache_import():
    """Importing empty cache is safe."""
    from husks.build.cache import cache_export, cache_import, cache_list
    from husks.build import fresh_store

    tmpdir = tempfile.mkdtemp(prefix="d3-empty-import-")
    try:
        # Create empty cache export
        site_a = Path(tmpdir) / "site_a"
        site_a.mkdir()
        S_a = fresh_store(str(site_a), fuel=10)

        export_file = Path(tmpdir) / "cache.tar.gz"
        cache_export(S_a, str(export_file))

        # Import to site B
        site_b = Path(tmpdir) / "site_b"
        site_b.mkdir()
        S_b = fresh_store(str(site_b), fuel=10)

        count = cache_import(S_b, str(export_file))
        assert count == 0, "empty import should import 0 entries"
        assert len(cache_list(S_b)) == 0, "site B should have no cache entries"

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)
