"""
test_cache_ledger.py -- Beta Gate D5: Record cache reuse in ledger.

Tests that cache hits and misses are recorded in build history
for audit trail and reproducibility verification.

Tests cover:
- Cache miss recorded as cached=false
- Cache hit recorded as cached=true
- History includes cache status for oracle rules
- Non-cached rules don't have cached field (or cached=false)
"""

from pathlib import Path
import pytest
from conftest import make_oracle_node, read_history

pytestmark = [pytest.mark.beta, pytest.mark.gate_d]


def test_cache_miss_recorded(cache_temp_site_with_input, basic_stub_oracle):
    """Cache miss (first execution) recorded in history."""
    from husks.build import build

    site = cache_temp_site_with_input["site"]
    (site / "input.txt").write_text("data\n")

    node = make_oracle_node("worker", inputs=["input.txt"], outputs=["output.txt"])
    S = build("demo", 10, node, site=str(site), oracle_backend=basic_stub_oracle)
    assert S["status"] == "committed"

    # Read history
    records = read_history(site, "worker")
    assert len(records) == 1

    record = records[0]
    assert "cached" in record
    assert record["cached"] is False, "first execution should be cache miss"
    assert record["cost_usd"] == 0.001, "cache miss should have oracle cost"


def test_cache_hit_recorded(cache_temp_site_with_input, basic_stub_oracle):
    """Cache hit (reuse) recorded in history."""
    from husks.build import build

    site = cache_temp_site_with_input["site"]
    (site / "input.txt").write_text("data\n")

    node = make_oracle_node("worker", inputs=["input.txt"], outputs=["output.txt"])

    # First build (cache miss)
    S1 = build("demo", 10, node, site=str(site), oracle_backend=basic_stub_oracle)
    assert S1["status"] == "committed"

    # Delete output to make rule stale
    (site / "output.txt").unlink()

    # Second build (cache hit)
    S2 = build("demo", 10, node, site=str(site), oracle_backend=basic_stub_oracle)
    assert S2["status"] == "committed"

    # Read history
    records = read_history(site, "worker")
    assert len(records) == 2

    # First record: cache miss
    assert records[0]["cached"] is False
    assert records[0]["cost_usd"] == 0.001

    # Second record: cache hit
    assert records[1]["cached"] is True, "second execution should be cache hit"
    assert records[1]["cost_usd"] == 0.0, "cache hit should have zero cost"


def test_action_rules_not_cached(cache_temp_site_with_input):
    """Action rules have cached=false (not cached)."""
    from husks.build import build, rule, action

    site = cache_temp_site_with_input["site"]
    (site / "input.txt").write_text("data\n")

    def write_output(S):
        from husks.build.site import site_path
        Path(site_path(S, "output.txt", write=True)).write_text("result\n")

    node = rule(
        "worker",
        inputs=["input.txt"],
        outputs=["output.txt"],
        recipe=action(write_output),
    )

    S = build("demo", 10, node, site=str(site))
    assert S["status"] == "committed"

    # Read history
    records = read_history(site, "worker")
    assert len(records) == 1

    record = records[0]
    assert "cached" in record
    assert record["cached"] is False, "action rules should not be cached"


def test_history_includes_recipe_digest(cache_temp_site_with_input, basic_stub_oracle):
    """History includes recipe digest for cache correlation."""
    from husks.build import build

    site = cache_temp_site_with_input["site"]
    (site / "input.txt").write_text("data\n")

    node = make_oracle_node("worker", inputs=["input.txt"], outputs=["output.txt"])
    S = build("demo", 10, node, site=str(site), oracle_backend=basic_stub_oracle)

    # Read history
    records = read_history(site, "worker")

    record = records[0]
    assert "recipe_digest" in record
    assert isinstance(record["recipe_digest"], str)
    assert len(record["recipe_digest"]) == 64, "should be SHA-256 hex"


def test_multiple_cache_reuses_recorded(cache_temp_site_with_input, basic_stub_oracle):
    """Multiple cache reuses each create history entry."""
    from husks.build import build

    site = cache_temp_site_with_input["site"]
    (site / "input.txt").write_text("data\n")

    node = make_oracle_node("worker", inputs=["input.txt"], outputs=["output.txt"])

    # First build
    S1 = build("demo", 10, node, site=str(site), oracle_backend=basic_stub_oracle)

    # Second build (cache hit 1)
    (site / "output.txt").unlink()
    S2 = build("demo", 10, node, site=str(site), oracle_backend=basic_stub_oracle)

    # Third build (cache hit 2)
    (site / "output.txt").unlink()
    S3 = build("demo", 10, node, site=str(site), oracle_backend=basic_stub_oracle)

    # Read history
    records = read_history(site, "worker")
    assert len(records) == 3

    # First: cache miss
    assert records[0]["cached"] is False

    # Second and third: cache hits
    assert records[1]["cached"] is True
    assert records[2]["cached"] is True


def test_cache_field_in_all_records(cache_temp_site):
    """All history records have cached field for consistency."""
    from husks.build import build, rule, action

    site = cache_temp_site["site"]

    (site / "input1.txt").write_text("data\n")
    (site / "input2.txt").write_text("data\n")

    def stub_oracle(S, rule_name, recipe, outputs):
        from husks.build.site import write_text, site_path
        write_text(site_path(S, outputs[0], write=True), "result\n")
        return {"tokens_in": 100, "tokens_out": 50, "cost_usd": 0.001, "fuel_steps": 1}

    def write_output(S):
        from husks.build.site import site_path
        Path(site_path(S, "action_output.txt", write=True)).write_text("action\n")

    # Build with oracle and action rules
    oracle_node = make_oracle_node("oracle_rule", inputs=["input1.txt"], outputs=["oracle_output.txt"])
    action_node = rule(
        "action_rule",
        inputs=["input2.txt"],
        outputs=["action_output.txt"],
        recipe=action(write_output),
    )

    S1 = build("demo", 10, oracle_node, site=str(site), oracle_backend=stub_oracle)
    S2 = build("demo", 10, action_node, site=str(site))

    # Check both history files have cached field
    oracle_records = read_history(site, "oracle_rule")
    action_records = read_history(site, "action_rule")

    # All records should have cached field
    for record in oracle_records + action_records:
        assert "cached" in record, "all history records should have cached field"
