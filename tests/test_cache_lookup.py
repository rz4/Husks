"""
test_cache_lookup.py -- Beta Gate D2: Cache lookup before oracle execution.

Tests cache integration with oracle evaluation, including cache hits,
cache misses, usage tracking, and cache disabling.

Tests cover:
- Oracle cache miss (first execution)
- Oracle cache hit (second execution reuses cached output)
- Cache disabled via store flag
- Cached usage shows zero cost/tokens
- Input changes invalidate cache
- Recipe changes invalidate cache
- Cache reuse increments counter
"""

import pytest
from pathlib import Path
from conftest import make_oracle_node


pytestmark = [pytest.mark.beta, pytest.mark.gate_d]


def test_oracle_cache_miss_then_hit(cache_temp_site_with_input, basic_stub_oracle, counting_oracle):
    """First oracle execution caches, second reuses cache."""
    from husks.build import build, oracle, rule

    site = cache_temp_site_with_input["site"]
    (site / "input.txt").write_text("test input\n")

    # First build (cache miss)
    node = rule(
        "worker",
        inputs=["input.txt"],
        outputs=["output.txt"],
        recipe=oracle("Generate output", fuel=5),
    )
    S1 = build("demo", 10, node, site=str(site), oracle_backend=basic_stub_oracle)

    assert S1["status"] == "committed"
    assert (site / "output.txt").read_text() == "result\n"
    assert S1["usage"]["total_cost_usd"] == 0.001

    # Second build (cache hit) - counting oracle should not be called
    S2 = build("demo", 10, node, site=str(site), oracle_backend=counting_oracle)

    assert S2["status"] == "committed"
    assert (site / "output.txt").read_text() == "result\n"  # Cached version
    assert counting_oracle.count["n"] == 0, "oracle should not execute on cache hit"
    assert S2["usage"]["total_cost_usd"] == 0.0


def test_oracle_cache_disabled(cache_temp_site_with_input):
    """Cache can be disabled via store flag."""
    from husks.build import build, rule, oracle

    site = cache_temp_site_with_input["site"]
    (site / "input.txt").write_text("test input\n")

    call_count = {"n": 0}
    def counting_oracle(S, rule_name, recipe, outputs):
        # Increment counter each time oracle is called
        call_count["n"] += 1
        from husks.build.site import write_text, site_path
        write_text(
            site_path(S, outputs[0], write=True),
            f"result {call_count['n']}\n"
        )
        return {"tokens_in": 100, "tokens_out": 50, "cost_usd": 0.001, "fuel_steps": 1}

    # Wrapper oracle that disables cache
    def cache_disabled_oracle(S, rule_name, recipe, outputs):
        S["cache-disabled"] = True
        return counting_oracle(S, rule_name, recipe, outputs)

    node = rule(
        "worker",
        inputs=["input.txt"],
        outputs=["output.txt"],
        recipe=oracle(prompt="Test", fuel=5),
    )

    # First build with cache disabled
    S1 = build("demo", 10, node, site=str(site), oracle_backend=cache_disabled_oracle)
    assert call_count["n"] == 1
    assert (site / "output.txt").read_text() == "result 1\n"

    # Delete output to make rule stale
    (site / "output.txt").unlink()

    # Second build with cache disabled (should execute again, not use cache)
    S2 = build("demo", 10, node, site=str(site), oracle_backend=cache_disabled_oracle)
    assert call_count["n"] == 2, "oracle should execute when cache disabled"
    assert (site / "output.txt").read_text() == "result 2\n"


def test_oracle_input_change_invalidates_cache(cache_temp_site_with_input):
    """Changing input invalidates oracle cache."""
    from husks.build import build, rule, oracle

    site = cache_temp_site_with_input["site"]
    (site / "input.txt").write_text("original\n")

    call_count = {"n": 0}
    def input_echo_oracle(S, rule_name, recipe, outputs):
        """Oracle that echoes input to output."""
        call_count["n"] += 1
        from husks.build.site import read_text, write_text, site_path
        content = read_text(site_path(S, "input.txt"))
        write_text(site_path(S, outputs[0], write=True), f"oracle: {content}")
        return {"tokens_in": 100, "tokens_out": 50, "cost_usd": 0.001, "fuel_steps": 1}

    node = rule(
        "worker",
        inputs=["input.txt"],
        outputs=["output.txt"],
        recipe=oracle("Echo input", fuel=5),
    )

    # First build
    S1 = build("demo", 10, node, site=str(site), oracle_backend=input_echo_oracle)
    assert call_count["n"] == 1
    assert (site / "output.txt").read_text() == "oracle: original\n"

    # Change input
    (site / "input.txt").write_text("modified\n")

    # Second build (cache miss due to input change)
    S2 = build("demo", 10, node, site=str(site), oracle_backend=input_echo_oracle)
    assert call_count["n"] == 2, "oracle should re-execute when input changes"
    assert (site / "output.txt").read_text() == "oracle: modified\n"


def test_oracle_recipe_change_invalidates_cache(cache_temp_site_with_input):
    """Changing oracle recipe invalidates cache."""
    from husks.build import build, rule, oracle

    site = cache_temp_site_with_input["site"]
    (site / "input.txt").write_text("data\n")

    call_count = {"n": 0}
    def stub_oracle(S, rule_name, recipe, outputs):
        call_count["n"] += 1
        from husks.build.site import write_text, site_path
        prompt = recipe.get("prompt", "")
        write_text(site_path(S, outputs[0], write=True), f"result: {prompt}\n")
        return {"tokens_in": 100, "tokens_out": 50, "cost_usd": 0.001, "fuel_steps": 1}

    # First build with prompt A
    node1 = rule(
        "worker",
        inputs=["input.txt"],
        outputs=["output.txt"],
        recipe=oracle(prompt="prompt A", fuel=5),
    )
    S1 = build("demo", 10, node1, site=str(site), oracle_backend=stub_oracle)
    assert call_count["n"] == 1
    assert (site / "output.txt").read_text() == "result: prompt A\n"

    # Second build with different prompt (cache miss)
    node2 = rule(
        "worker",
        inputs=["input.txt"],
        outputs=["output.txt"],
        recipe=oracle(prompt="prompt B", fuel=5),
    )
    S2 = build("demo", 10, node2, site=str(site), oracle_backend=stub_oracle)
    assert call_count["n"] == 2, "oracle should re-execute when recipe changes"
    assert (site / "output.txt").read_text() == "result: prompt B\n"


def test_cached_usage_has_zero_cost(cache_temp_site_with_input, expensive_oracle):
    """Cached oracle execution reports zero cost and tokens."""
    from husks.build import build, rule, oracle

    site = cache_temp_site_with_input["site"]
    (site / "input.txt").write_text("data\n")

    node = rule(
        "worker",
        inputs=["input.txt"],
        outputs=["output.txt"],
        recipe=oracle("Expensive prompt", fuel=5),
    )

    # First build (expensive)
    S1 = build("demo", 10, node, site=str(site), oracle_backend=expensive_oracle)
    assert S1["usage"]["total_cost_usd"] == 0.10
    assert S1["usage"]["total_input_tokens"] == 1000
    assert S1["usage"]["total_output_tokens"] == 500

    # Second build (cached, free)
    S2 = build("demo", 10, node, site=str(site), oracle_backend=expensive_oracle)
    assert S2["usage"]["total_cost_usd"] == 0.0, "cached execution should have zero cost"
    assert S2["usage"]["total_input_tokens"] == 0, "cached execution should have zero input tokens"
    assert S2["usage"]["total_output_tokens"] == 0, "cached execution should have zero output tokens"


def test_cache_reuse_increments_counter(cache_temp_site_with_input, basic_stub_oracle):
    """Cache reuse counter increments on each cache hit."""
    from husks.build import build, rule, oracle
    from husks.build.cache import cache_list

    site = cache_temp_site_with_input["site"]
    (site / "input.txt").write_text("data\n")

    node = rule(
        "worker",
        inputs=["input.txt"],
        outputs=["output.txt"],
        recipe=oracle("Test", fuel=5),
    )

    # First build (creates cache entry)
    S1 = build("demo", 10, node, site=str(site), oracle_backend=basic_stub_oracle)

    # Check initial reuse count
    entries = cache_list(S1)
    assert len(entries) == 1
    assert entries[0]["reuse_count"] == 0

    # Delete output to make rule stale (but keep inputs/recipe same for cache hit)
    (site / "output.txt").unlink()

    # Second build (cache hit because inputs/recipe unchanged)
    S2 = build("demo", 10, node, site=str(site), oracle_backend=basic_stub_oracle)
    entries = cache_list(S2)
    assert entries[0]["reuse_count"] == 1, "reuse count should increment on cache hit"

    # Delete output again
    (site / "output.txt").unlink()

    # Third build (another cache hit)
    S3 = build("demo", 10, node, site=str(site), oracle_backend=basic_stub_oracle)
    entries = cache_list(S3)
    assert entries[0]["reuse_count"] == 2, "reuse count should increment again"


def test_multiple_oracles_use_separate_caches(cache_temp_site):
    """Different oracles create separate cache entries."""
    from husks.build import build, rule, oracle
    from husks.build.cache import cache_list

    site = cache_temp_site["site"]

    (site / "input1.txt").write_text("data1\n")
    (site / "input2.txt").write_text("data2\n")

    def stub_oracle(S, rule_name, recipe, outputs):
        from husks.build.site import write_text, site_path
        write_text(site_path(S, outputs[0], write=True), f"result for {rule_name}\n")
        return {"tokens_in": 100, "tokens_out": 50, "cost_usd": 0.001, "fuel_steps": 1}

    # Build first oracle rule
    node1 = rule(
        "oracle1",
        inputs=["input1.txt"],
        outputs=["output1.txt"],
        recipe=oracle("Prompt A", fuel=5),
    )
    S1 = build("demo", 10, node1, site=str(site), oracle_backend=stub_oracle)

    # Build second oracle rule
    node2 = rule(
        "oracle2",
        inputs=["input2.txt"],
        outputs=["output2.txt"],
        recipe=oracle("Prompt B", fuel=5),
    )
    S2 = build("demo", 10, node2, site=str(site), oracle_backend=stub_oracle)

    # Should have two cache entries
    entries = cache_list(S2)
    assert len(entries) == 2, "should have separate cache entries for different oracles"
