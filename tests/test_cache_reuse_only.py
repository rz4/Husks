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

import tempfile
import shutil
from pathlib import Path
import pytest


def test_reuse_only_with_cache_hit():
    """Reuse-only mode succeeds when cache available."""
    from husks.build import build, rule, oracle

    tmpdir = tempfile.mkdtemp(prefix="d4-hit-")
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

        # First build to populate cache
        S1 = build("demo", 10, node, site=str(site), oracle_backend=stub_oracle)
        assert S1["status"] == "committed"

        # Delete output to make rule stale
        (site / "output.txt").unlink()

        # Second build with reuse-only mode (should use cache)
        from husks.build import fresh_store
        from husks.build.eval import eval_node

        S2 = fresh_store(str(site), fuel=10, oracle_backend=stub_oracle)
        S2["cache-reuse-only"] = True

        # Should succeed using cached result
        eval_node(S2, node)

        assert (site / "output.txt").read_text() == "result\n"

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_reuse_only_with_cache_miss():
    """Reuse-only mode fails when cache unavailable."""
    from husks.build import build, rule, oracle

    tmpdir = tempfile.mkdtemp(prefix="d4-miss-")
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

        # Build with reuse-only mode but no cache
        from husks.build import fresh_store
        from husks.build.eval import eval_node

        S = fresh_store(str(site), fuel=10, oracle_backend=stub_oracle)
        S["cache-reuse-only"] = True

        # Should fail with cache miss
        with pytest.raises(RuntimeError, match=r"cache-reuse-only mode is enabled"):
            eval_node(S, node)

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_reuse_only_error_identifies_oracle():
    """Reuse-only error message identifies the oracle rule."""
    from husks.build import build, rule, oracle

    tmpdir = tempfile.mkdtemp(prefix="d4-error-")
    try:
        site = Path(tmpdir) / "site"
        site.mkdir()

        (site / "input.txt").write_text("data\n")

        def stub_oracle(S, rule_name, recipe, outputs):
            from husks.build.site import write_text, site_path
            write_text(site_path(S, outputs[0], write=True), "result\n")
            return {"tokens_in": 100, "tokens_out": 50, "cost_usd": 0.001, "fuel_steps": 1}

        node = rule(
            "my-oracle-rule",
            inputs=["input.txt"],
            outputs=["output.txt"],
            recipe=oracle(prompt="Test", fuel=5),
        )

        from husks.build import fresh_store
        from husks.build.eval import eval_node

        S = fresh_store(str(site), fuel=10, oracle_backend=stub_oracle)
        S["cache-reuse-only"] = True

        # Error should mention rule name
        with pytest.raises(RuntimeError, match=r"oracle 'my-oracle-rule'"):
            eval_node(S, node)

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_reuse_only_disabled_allows_execution():
    """With reuse-only disabled, oracle executes normally."""
    from husks.build import build, rule, oracle

    tmpdir = tempfile.mkdtemp(prefix="d4-disabled-")
    try:
        site = Path(tmpdir) / "site"
        site.mkdir()

        (site / "input.txt").write_text("data\n")

        call_count = {"n": 0}
        def counting_oracle(S, rule_name, recipe, outputs):
            call_count["n"] += 1
            from husks.build.site import write_text, site_path
            write_text(site_path(S, outputs[0], write=True), "result\n")
            return {"tokens_in": 100, "tokens_out": 50, "cost_usd": 0.001, "fuel_steps": 1}

        node = rule(
            "worker",
            inputs=["input.txt"],
            outputs=["output.txt"],
            recipe=oracle(prompt="Test", fuel=5),
        )

        # Build without reuse-only (normal execution)
        S = build("demo", 10, node, site=str(site), oracle_backend=counting_oracle)

        assert S["status"] == "committed"
        assert call_count["n"] == 1, "oracle should execute normally"

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_reuse_only_with_changed_input():
    """Reuse-only fails when input changes (different cache key)."""
    from husks.build import build, rule, oracle

    tmpdir = tempfile.mkdtemp(prefix="d4-changed-input-")
    try:
        site = Path(tmpdir) / "site"
        site.mkdir()

        (site / "input.txt").write_text("original\n")

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

        # First build with original input
        S1 = build("demo", 10, node, site=str(site), oracle_backend=stub_oracle)
        assert S1["status"] == "committed"

        # Change input and delete output
        (site / "input.txt").write_text("modified\n")
        (site / "output.txt").unlink()

        # Reuse-only mode should fail (cache key changed)
        from husks.build import fresh_store
        from husks.build.eval import eval_node

        S2 = fresh_store(str(site), fuel=10, oracle_backend=stub_oracle)
        S2["cache-reuse-only"] = True

        with pytest.raises(RuntimeError, match=r"cache-reuse-only mode is enabled"):
            eval_node(S2, node)

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_reuse_only_with_imported_cache():
    """Reuse-only mode works with imported cache."""
    from husks.build import build, rule, oracle
    from husks.build.cache import cache_export, cache_import

    tmpdir = tempfile.mkdtemp(prefix="d4-imported-")
    try:
        # Site A: Build and export cache
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

        export_file = Path(tmpdir) / "cache.tar.gz"
        cache_export(S_a, str(export_file))

        # Site B: Import cache and use reuse-only
        site_b = Path(tmpdir) / "site_b"
        site_b.mkdir()
        (site_b / "input.txt").write_text("data\n")

        from husks.build import fresh_store
        from husks.build.eval import eval_node

        S_b = fresh_store(str(site_b), fuel=10, oracle_backend=stub_oracle)
        cache_import(S_b, str(export_file))

        S_b["cache-reuse-only"] = True

        # Should succeed using imported cache
        eval_node(S_b, node)

        assert (site_b / "output.txt").read_text() == "result\n"

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)
