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

from pathlib import Path
import pytest

pytestmark = [pytest.mark.beta, pytest.mark.gate_d]


def test_cache_export(cache_temp_site_with_input, basic_stub_oracle):
    """Cache can be exported to tarball."""
    from husks.build import build
    from husks.build.cache import cache_export
    from conftest import make_oracle_node

    site = cache_temp_site_with_input["site"]
    tmpdir = cache_temp_site_with_input["tmpdir"]

    node = make_oracle_node("worker", inputs=["input.txt"], outputs=["output.txt"])
    S = build("demo", 10, node, site=str(site), oracle_backend=basic_stub_oracle)

    # Export cache
    export_file = Path(tmpdir) / "cache.tar.gz"
    count = cache_export(S, str(export_file))

    assert count == 1, "should export 1 cache entry"
    assert export_file.exists(), "export file should be created"
    assert export_file.stat().st_size > 0, "export file should not be empty"


def test_cache_import(cache_temp_site_with_input, basic_stub_oracle):
    """Cache can be imported from tarball."""
    from husks.build import build, fresh_store
    from husks.build.cache import cache_export, cache_import, cache_list
    from conftest import make_oracle_node

    tmpdir = cache_temp_site_with_input["tmpdir"]
    site_a = cache_temp_site_with_input["site"]

    node = make_oracle_node("worker", inputs=["input.txt"], outputs=["output.txt"])
    S_a = build("demo", 10, node, site=str(site_a), oracle_backend=basic_stub_oracle)

    # Export cache from site A
    export_file = Path(tmpdir) / "cache.tar.gz"
    cache_export(S_a, str(export_file))

    # Create site B (empty cache)
    site_b = Path(tmpdir) / "site_b"
    site_b.mkdir()

    # Import cache to site B
    S_b = fresh_store(str(site_b), fuel=10)
    count = cache_import(S_b, str(export_file))

    assert count == 1, "should import 1 cache entry"

    # Verify cache is available in site B
    entries = cache_list(S_b)
    assert len(entries) == 1, "site B should have 1 cache entry"


def test_cache_import_merge(cache_temp_site):
    """Import merges with existing cache by default."""
    from husks.build import build
    from husks.build.cache import cache_export, cache_import, cache_list
    from conftest import make_oracle_node

    tmpdir = cache_temp_site["tmpdir"]

    # Create site A with cache entry 1
    site_a = Path(tmpdir) / "site_a"
    site_a.mkdir()
    (site_a / "input1.txt").write_text("data1\n")

    def stub_oracle(S, rule_name, recipe, outputs):
        from husks.build.site import write_text, site_path
        write_text(site_path(S, outputs[0], write=True), f"result for {rule_name}\n")
        return {"tokens_in": 100, "tokens_out": 50, "cost_usd": 0.001, "fuel_steps": 1}

    node1 = make_oracle_node("worker1", inputs=["input1.txt"], outputs=["output1.txt"], prompt="Test 1")
    S_a = build("demo", 10, node1, site=str(site_a), oracle_backend=stub_oracle)
    export1 = Path(tmpdir) / "cache1.tar.gz"
    cache_export(S_a, str(export1))

    # Create site B with cache entry 2
    site_b = Path(tmpdir) / "site_b"
    site_b.mkdir()
    (site_b / "input2.txt").write_text("data2\n")

    node2 = make_oracle_node("worker2", inputs=["input2.txt"], outputs=["output2.txt"], prompt="Test 2")
    S_b = build("demo", 10, node2, site=str(site_b), oracle_backend=stub_oracle)

    # Import cache 1 into site B (merge)
    cache_import(S_b, str(export1), merge=True)

    # Should have both cache entries
    entries = cache_list(S_b)
    assert len(entries) == 2, "merge should preserve existing cache"


def test_cache_import_replace(cache_temp_site):
    """Import can replace existing cache."""
    from husks.build import build
    from husks.build.cache import cache_export, cache_import, cache_list
    from conftest import make_oracle_node

    tmpdir = cache_temp_site["tmpdir"]

    # Create site A with cache entry 1
    site_a = Path(tmpdir) / "site_a"
    site_a.mkdir()
    (site_a / "input1.txt").write_text("data1\n")

    def stub_oracle(S, rule_name, recipe, outputs):
        from husks.build.site import write_text, site_path
        write_text(site_path(S, outputs[0], write=True), f"result for {rule_name}\n")
        return {"tokens_in": 100, "tokens_out": 50, "cost_usd": 0.001, "fuel_steps": 1}

    node1 = make_oracle_node("worker1", inputs=["input1.txt"], outputs=["output1.txt"], prompt="Test 1")
    S_a = build("demo", 10, node1, site=str(site_a), oracle_backend=stub_oracle)
    export1 = Path(tmpdir) / "cache1.tar.gz"
    cache_export(S_a, str(export1))

    # Create site B with cache entry 2
    site_b = Path(tmpdir) / "site_b"
    site_b.mkdir()
    (site_b / "input2.txt").write_text("data2\n")

    node2 = make_oracle_node("worker2", inputs=["input2.txt"], outputs=["output2.txt"], prompt="Test 2")
    S_b = build("demo", 10, node2, site=str(site_b), oracle_backend=stub_oracle)

    # Verify site B has 1 cache entry
    assert len(cache_list(S_b)) == 1

    # Import cache 1 into site B (replace)
    cache_import(S_b, str(export1), merge=False)

    # Should have only cache entry from import
    entries = cache_list(S_b)
    assert len(entries) == 1, "replace should clear existing cache"


def test_cross_site_cache_reuse(cache_temp_site, counting_oracle):
    """Cache exported from one site can be used by another."""
    from husks.build import build, fresh_store
    from husks.build.cache import cache_export, cache_import
    from husks.build.eval import eval_node
    from conftest import make_oracle_node

    tmpdir = cache_temp_site["tmpdir"]

    # Site A: Build and cache
    site_a = Path(tmpdir) / "site_a"
    site_a.mkdir()
    (site_a / "input.txt").write_text("data\n")

    node = make_oracle_node("worker", inputs=["input.txt"], outputs=["output.txt"])

    # First build on site A
    S_a = build("demo", 10, node, site=str(site_a), oracle_backend=counting_oracle)
    assert counting_oracle.count["n"] == 1

    # Export cache from site A
    export_file = Path(tmpdir) / "cache.tar.gz"
    cache_export(S_a, str(export_file))

    # Site B: Import cache and reuse
    site_b = Path(tmpdir) / "site_b"
    site_b.mkdir()
    (site_b / "input.txt").write_text("data\n")

    # Import cache before build
    S_b = fresh_store(str(site_b), fuel=10, oracle_backend=counting_oracle)
    cache_import(S_b, str(export_file))

    # Build on site B (should use cache, not call oracle)
    eval_node(S_b, node)

    # Oracle should not be called on site B (cache hit)
    assert counting_oracle.count["n"] == 1, "site B should reuse cache from site A"
    assert (site_b / "output.txt").read_text() == "result 1\n"


def test_empty_cache_export(cache_temp_site):
    """Empty cache exports empty tarball."""
    from husks.build.cache import cache_export
    from husks.build import fresh_store

    site = cache_temp_site["site"]
    tmpdir = cache_temp_site["tmpdir"]

    S = fresh_store(str(site), fuel=10)

    export_file = Path(tmpdir) / "cache.tar.gz"
    count = cache_export(S, str(export_file))

    assert count == 0, "empty cache should export 0 entries"
    assert export_file.exists(), "export file should be created even if empty"


def test_empty_cache_import(cache_temp_site):
    """Importing empty cache is safe."""
    from husks.build.cache import cache_export, cache_import, cache_list
    from husks.build import fresh_store

    tmpdir = cache_temp_site["tmpdir"]

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
