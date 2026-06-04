"""
test_cache_write_failure_semantics.py -- Cache write failure after promotion.

Beta Gate B7: Fix post-promotion cache write failure semantics.

Tests that cache write failures after successful promotion do not corrupt
the build state. The build should report committed status with sealed outputs,
even if cache population fails.
"""

from pathlib import Path
from unittest.mock import patch

from conftest import make_oracle_node, read_history


def test_cache_write_failure_does_not_corrupt_build(cache_temp_site, basic_stub_oracle):
    """Cache write failure after promotion should not fail the build.

    Scenario: Oracle executes successfully, outputs are promoted and sealed,
    but cache write fails. The build should still report committed status.
    """
    from husks.build import build
    site = cache_temp_site["site"]

    node = make_oracle_node("oracle-rule", inputs=[], outputs=["output.txt"], prompt="test")

    # Mock cache_put_pending where it's imported (eval module)
    with patch("husks.build.eval.cache_put_pending") as mock_cache_put:
        mock_cache_put.side_effect = IOError("Simulated cache write failure")

        # Build should still succeed
        S = build("cache-fail-test", 10, node, site=str(site), oracle_backend=basic_stub_oracle)

        # Build should report committed (not halted)
        assert S["status"] == "committed", (
            f"Build should commit despite cache write failure, got {S['status']}"
        )

        # Output should exist and be sealed
        assert (site / "output.txt").exists(), "Output should be promoted"
        assert (site / "output.txt").read_text() == "result\n"

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


def test_cache_write_failure_does_not_prevent_history(cache_temp_site, basic_stub_oracle):
    """Cache write failure should not prevent history recording."""
    from husks.build import build
    site = cache_temp_site["site"]

    node = make_oracle_node("test-rule", inputs=[], outputs=["out.txt"], prompt="test")

    # Mock cache_put to fail
    with patch("husks.build.cache.cache_put") as mock_cache_put:
        mock_cache_put.side_effect = RuntimeError("Cache unavailable")

        S = build("history-test", 10, node, site=str(site), oracle_backend=basic_stub_oracle)

        # Build should succeed
        assert S["status"] == "committed"

        # History should be recorded
        history = read_history(site, "test-rule")
        assert len(history) == 1, "History should have one entry"
        assert history[0]["cost_usd"] == 0.001
        assert history[0]["cached"] is False  # Was not a cache hit


def test_successful_cache_write_still_works(cache_temp_site, basic_stub_oracle):
    """Verify that successful cache writes still work normally.

    Regression test to ensure the try/except doesn't break normal operation.
    """
    from husks.build import build
    from pathlib import Path
    site = cache_temp_site["site"]

    node = make_oracle_node("cacheable", inputs=[], outputs=["out.txt"], prompt="test")

    # First build should cache the output
    S1 = build("cache-test-1", 10, node, site=str(site), oracle_backend=basic_stub_oracle)
    assert S1["status"] == "committed"

    # Verify cache was populated by checking .cache directory exists and has entries
    cache_dir = site / ".cache"
    assert cache_dir.exists(), "Cache directory should exist"
    cache_entries = list(cache_dir.iterdir())
    assert len(cache_entries) > 0, "Cache should have entries"

    # No cache write failures should be recorded
    cache_failures = [
        e for e in S1["trace"]
        if e.get("event") == "cache-write-failed"
    ]
    assert len(cache_failures) == 0, "Should have no cache failures on success"


def test_cache_disabled_flag_skips_cache_write(cache_temp_site, basic_stub_oracle):
    """Verify cache-disabled flag prevents cache write attempts.

    When cache is disabled, cache_put should not be called at all,
    so failures cannot occur.
    """
    from husks.build.site import fresh_store
    from husks.build.eval import eval_node
    from unittest.mock import patch
    site = cache_temp_site["site"]

    node = make_oracle_node("no-cache", inputs=[], outputs=["out.txt"], prompt="test")

    # Mock cache_put to track calls
    with patch("husks.build.cache.cache_put") as mock_cache_put:
        # Build with cache disabled
        S = fresh_store(str(site), fuel=10, oracle_backend=basic_stub_oracle)
        S["cache-disabled"] = True

        eval_node(S, node)

        # cache_put should not have been called
        assert not mock_cache_put.called, (
            "cache_put should not be called when cache is disabled"
        )
