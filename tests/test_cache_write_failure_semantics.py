"""
test_cache_write_failure_semantics.py -- Cache write failure after promotion.

Beta Gate B7: Fix post-promotion cache write failure semantics.

Tests that cache write failures after successful promotion do not corrupt
the build state. The build should report committed status with sealed outputs,
even if cache population fails.
"""

import tempfile
import shutil
from pathlib import Path
from unittest.mock import patch


def test_cache_write_failure_does_not_corrupt_build():
    """Cache write failure after promotion should not fail the build.

    Scenario: Oracle executes successfully, outputs are promoted and sealed,
    but cache write fails. The build should still report committed status.
    """
    from husks.build import build, rule, oracle

    tmpdir = tempfile.mkdtemp(prefix="cache-write-failure-")
    try:
        site = Path(tmpdir) / "site"
        site.mkdir()

        def stub_oracle(S, rule_name, recipe, outputs):
            """Stub oracle that produces valid output."""
            from husks.build import write_path
            for o in outputs:
                output_path = write_path(S, o)
                Path(output_path).parent.mkdir(parents=True, exist_ok=True)
                Path(output_path).write_text("oracle output\n")
            return {"tokens_in": 100, "tokens_out": 50, "cost_usd": 0.001, "fuel_steps": 1}

        node = rule(
            "oracle-rule",
            outputs=["output.txt"],
            recipe=oracle(prompt="test", fuel=5),
        )

        # Mock cache_put_pending to raise an exception
        with patch("husks.build.cache.cache_put_pending") as mock_cache_put:
            mock_cache_put.side_effect = IOError("Simulated cache write failure")

            # Build should still succeed
            S = build("cache-fail-test", 10, node, site=str(site), oracle_backend=stub_oracle)

            # Build should report committed (not halted)
            assert S["status"] == "committed", (
                f"Build should commit despite cache write failure, got {S['status']}"
            )

            # Output should exist and be sealed
            assert (site / "output.txt").exists(), "Output should be promoted"
            assert (site / "output.txt").read_text() == "oracle output\n"

            # Seal should exist
            seal_path = site / ".traces" / "oracle-rule.seal"
            assert seal_path.exists(), "Seal should exist despite cache write failure"

            # Trace should record the cache staging failure
            cache_failures = [
                e for e in S["trace"]
                if e.get("event") == "cache-stage-failed"
            ]
            assert len(cache_failures) == 1, (
                f"Should record one cache stage failure, got {len(cache_failures)}"
            )
            assert "cache write failure" in cache_failures[0]["error"].lower()

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_cache_write_failure_does_not_prevent_history():
    """Cache write failure should not prevent history recording."""
    from husks.build import build, rule, oracle
    from husks.build.seal import history_file
    import json

    tmpdir = tempfile.mkdtemp(prefix="cache-fail-history-")
    try:
        site = Path(tmpdir) / "site"
        site.mkdir()

        def stub_oracle(S, rule_name, recipe, outputs):
            from husks.build import write_path
            for o in outputs:
                output_path = write_path(S, o)
                Path(output_path).parent.mkdir(parents=True, exist_ok=True)
                Path(output_path).write_text("output\n")
            return {"tokens_in": 100, "tokens_out": 50, "cost_usd": 0.001, "fuel_steps": 1}

        node = rule(
            "test-rule",
            outputs=["out.txt"],
            recipe=oracle(prompt="test", fuel=5),
        )

        # Mock cache_put to fail
        with patch("husks.build.cache.cache_put") as mock_cache_put:
            mock_cache_put.side_effect = RuntimeError("Cache unavailable")

            S = build("history-test", 10, node, site=str(site), oracle_backend=stub_oracle)

            # Build should succeed
            assert S["status"] == "committed"

            # History should be recorded
            hist_path = Path(history_file(S, "test-rule"))
            assert hist_path.exists(), "History file should exist"

            # Read and verify history
            history = [json.loads(line) for line in hist_path.read_text().strip().split('\n')]
            assert len(history) == 1, "History should have one entry"
            assert history[0]["cost_usd"] == 0.001
            assert history[0]["cached"] is False  # Was not a cache hit

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_successful_cache_write_still_works():
    """Verify that successful cache writes still work normally.

    Regression test to ensure the try/except doesn't break normal operation.
    """
    from husks.build import build, rule, oracle
    from husks.build.cache import cache_get

    tmpdir = tempfile.mkdtemp(prefix="cache-success-")
    try:
        site = Path(tmpdir) / "site"
        site.mkdir()

        def stub_oracle(S, rule_name, recipe, outputs):
            from husks.build import write_path
            for o in outputs:
                output_path = write_path(S, o)
                Path(output_path).parent.mkdir(parents=True, exist_ok=True)
                Path(output_path).write_text("cached content\n")
            return {"tokens_in": 100, "tokens_out": 50, "cost_usd": 0.001, "fuel_steps": 1}

        node = rule(
            "cacheable",
            outputs=["out.txt"],
            recipe=oracle(prompt="test", fuel=5),
        )

        # First build should cache the output
        S1 = build("cache-test-1", 10, node, site=str(site), oracle_backend=stub_oracle)
        assert S1["status"] == "committed"

        # Verify cache was populated
        recipe = {"type": "oracle", "prompt": "test", "tools": [], "fuel": 5}
        cached = cache_get(S1, recipe, [])
        assert cached is not None, "Cache should be populated"
        assert cached["out.txt"] == "cached content\n"

        # No cache write failures should be recorded
        cache_failures = [
            e for e in S1["trace"]
            if e.get("event") == "cache-write-failed"
        ]
        assert len(cache_failures) == 0, "Should have no cache failures on success"

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_cache_disabled_flag_skips_cache_write():
    """Verify cache-disabled flag prevents cache write attempts.

    When cache is disabled, cache_put should not be called at all,
    so failures cannot occur.
    """
    from husks.build import build, rule, oracle
    from unittest.mock import MagicMock

    tmpdir = tempfile.mkdtemp(prefix="cache-disabled-")
    try:
        site = Path(tmpdir) / "site"
        site.mkdir()

        def stub_oracle(S, rule_name, recipe, outputs):
            from husks.build import write_path
            for o in outputs:
                output_path = write_path(S, o)
                Path(output_path).parent.mkdir(parents=True, exist_ok=True)
                Path(output_path).write_text("output\n")
            return {"tokens_in": 100, "tokens_out": 50, "cost_usd": 0.001, "fuel_steps": 1}

        node = rule(
            "no-cache",
            outputs=["out.txt"],
            recipe=oracle(prompt="test", fuel=5),
        )

        # Mock cache_put to track calls
        with patch("husks.build.cache.cache_put") as mock_cache_put:
            # Build with cache disabled
            from husks.build.site import fresh_store
            S = fresh_store(str(site), fuel=10, oracle_backend=stub_oracle)
            S["cache-disabled"] = True

            from husks.build.eval import eval_node
            eval_node(S, node)

            # cache_put should not have been called
            assert not mock_cache_put.called, (
                "cache_put should not be called when cache is disabled"
            )

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)
