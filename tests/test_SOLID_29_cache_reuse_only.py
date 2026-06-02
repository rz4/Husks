"""
test_cache_reuse_only.py -- Beta Gate D4: Reuse-only mode.

Tests cache-reuse-only mode which prohibits oracle execution,
enforcing strict cache dependency for reproducibility verification.

Tests cover:
- Reuse-only mode with cache hit succeeds
- Reuse-only mode with cache miss fails
- Reuse-only mode disabled allows execution
- Error message identifies missing oracle
"""

from pathlib import Path
import pytest

pytestmark = [pytest.mark.beta, pytest.mark.gate_d]


def test_reuse_only_with_cache_hit(cache_temp_site_with_input, basic_stub_oracle):
    """Reuse-only mode succeeds when cache available."""
    from husks.build import build, fresh_store
    from husks.build.eval import eval_node
    from conftest import make_oracle_node

    site = cache_temp_site_with_input["site"]
    (site / "input.txt").write_text("data\n")

    node = make_oracle_node("worker", inputs=["input.txt"], outputs=["output.txt"])

    # First build to populate cache
    S1 = build("demo", 10, node, site=str(site), oracle_backend=basic_stub_oracle)
    assert S1["status"] == "committed"

    # Delete output to make rule stale
    (site / "output.txt").unlink()

    # Second build with reuse-only mode (should use cache)
    S2 = fresh_store(str(site), fuel=10, oracle_backend=basic_stub_oracle)
    S2["cache-reuse-only"] = True

    # Should succeed using cached result
    eval_node(S2, node)

    assert (site / "output.txt").read_text() == "result\n"


def test_reuse_only_with_cache_miss(cache_temp_site_with_input, basic_stub_oracle):
    """Reuse-only mode fails when cache unavailable."""
    from husks.build import fresh_store
    from husks.build.eval import eval_node
    from conftest import make_oracle_node

    site = cache_temp_site_with_input["site"]
    (site / "input.txt").write_text("data\n")

    node = make_oracle_node("worker", inputs=["input.txt"], outputs=["output.txt"])

    # Build with reuse-only mode but no cache
    S = fresh_store(str(site), fuel=10, oracle_backend=basic_stub_oracle)
    S["cache-reuse-only"] = True

    # Should fail with cache miss
    with pytest.raises(RuntimeError, match=r"cache-reuse-only mode is enabled"):
        eval_node(S, node)


def test_reuse_only_error_identifies_oracle(cache_temp_site_with_input, basic_stub_oracle):
    """Reuse-only error message identifies the oracle rule."""
    from husks.build import fresh_store
    from husks.build.eval import eval_node
    from conftest import make_oracle_node

    site = cache_temp_site_with_input["site"]
    (site / "input.txt").write_text("data\n")

    node = make_oracle_node("my-oracle-rule", inputs=["input.txt"], outputs=["output.txt"])

    S = fresh_store(str(site), fuel=10, oracle_backend=basic_stub_oracle)
    S["cache-reuse-only"] = True

    # Error should mention rule name
    with pytest.raises(RuntimeError, match=r"oracle 'my-oracle-rule'"):
        eval_node(S, node)


def test_reuse_only_disabled_allows_execution(cache_temp_site_with_input, counting_oracle):
    """With reuse-only disabled, oracle executes normally."""
    from husks.build import build
    from conftest import make_oracle_node

    site = cache_temp_site_with_input["site"]
    (site / "input.txt").write_text("data\n")

    node = make_oracle_node("worker", inputs=["input.txt"], outputs=["output.txt"])

    # Build without reuse-only (normal execution)
    S = build("demo", 10, node, site=str(site), oracle_backend=counting_oracle)

    assert S["status"] == "committed"
    assert counting_oracle.count["n"] == 1, "oracle should execute normally"


def test_reuse_only_with_changed_input(cache_temp_site_with_input, basic_stub_oracle):
    """Reuse-only fails when input changes (different cache key)."""
    from husks.build import build, fresh_store
    from husks.build.eval import eval_node
    from conftest import make_oracle_node

    site = cache_temp_site_with_input["site"]
    (site / "input.txt").write_text("original\n")

    node = make_oracle_node("worker", inputs=["input.txt"], outputs=["output.txt"])

    # First build with original input
    S1 = build("demo", 10, node, site=str(site), oracle_backend=basic_stub_oracle)
    assert S1["status"] == "committed"

    # Change input and delete output
    (site / "input.txt").write_text("modified\n")
    (site / "output.txt").unlink()

    # Reuse-only mode should fail (cache key changed)
    S2 = fresh_store(str(site), fuel=10, oracle_backend=basic_stub_oracle)
    S2["cache-reuse-only"] = True

    with pytest.raises(RuntimeError, match=r"cache-reuse-only mode is enabled"):
        eval_node(S2, node)


def test_reuse_only_with_imported_cache(cache_temp_site):
    """Reuse-only mode works with imported cache."""
    from husks.build import build, fresh_store
    from husks.build.cache import cache_export, cache_import
    from husks.build.eval import eval_node
    from conftest import make_oracle_node

    tmpdir = cache_temp_site["tmpdir"]

    # Site A: Build and export cache
    site_a = Path(tmpdir) / "site_a"
    site_a.mkdir()
    (site_a / "input.txt").write_text("data\n")

    def stub_oracle(S, rule_name, recipe, outputs):
        from husks.build.site import write_text, site_path
        write_text(site_path(S, outputs[0], write=True), "result\n")
        return {"tokens_in": 100, "tokens_out": 50, "cost_usd": 0.001, "fuel_steps": 1}

    node = make_oracle_node("worker", inputs=["input.txt"], outputs=["output.txt"])

    S_a = build("demo", 10, node, site=str(site_a), oracle_backend=stub_oracle)

    export_file = Path(tmpdir) / "cache.tar.gz"
    cache_export(S_a, str(export_file))

    # Site B: Import cache and use reuse-only
    site_b = Path(tmpdir) / "site_b"
    site_b.mkdir()
    (site_b / "input.txt").write_text("data\n")

    S_b = fresh_store(str(site_b), fuel=10, oracle_backend=stub_oracle)
    cache_import(S_b, str(export_file))

    S_b["cache-reuse-only"] = True

    # Should succeed using imported cache
    eval_node(S_b, node)

    assert (site_b / "output.txt").read_text() == "result\n"
