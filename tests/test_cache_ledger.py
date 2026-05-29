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

import tempfile
import shutil
import json
from pathlib import Path


def test_cache_miss_recorded():
    """Cache miss (first execution) recorded in history."""
    from husks.build import build, rule, oracle

    tmpdir = tempfile.mkdtemp(prefix="d5-miss-")
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
        assert S["status"] == "committed"

        # Read history
        history_file = site / ".traces" / "worker.history.jsonl"
        assert history_file.exists()

        records = [json.loads(line) for line in history_file.read_text().splitlines()]
        assert len(records) == 1

        record = records[0]
        assert "cached" in record
        assert record["cached"] is False, "first execution should be cache miss"
        assert record["cost_usd"] == 0.001, "cache miss should have oracle cost"

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_cache_hit_recorded():
    """Cache hit (reuse) recorded in history."""
    from husks.build import build, rule, oracle

    tmpdir = tempfile.mkdtemp(prefix="d5-hit-")
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

        # First build (cache miss)
        S1 = build("demo", 10, node, site=str(site), oracle_backend=stub_oracle)
        assert S1["status"] == "committed"

        # Delete output to make rule stale
        (site / "output.txt").unlink()

        # Second build (cache hit)
        S2 = build("demo", 10, node, site=str(site), oracle_backend=stub_oracle)
        assert S2["status"] == "committed"

        # Read history
        history_file = site / ".traces" / "worker.history.jsonl"
        records = [json.loads(line) for line in history_file.read_text().splitlines()]
        assert len(records) == 2

        # First record: cache miss
        assert records[0]["cached"] is False
        assert records[0]["cost_usd"] == 0.001

        # Second record: cache hit
        assert records[1]["cached"] is True, "second execution should be cache hit"
        assert records[1]["cost_usd"] == 0.0, "cache hit should have zero cost"

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_action_rules_not_cached():
    """Action rules have cached=false (not cached)."""
    from husks.build import build, rule, action

    tmpdir = tempfile.mkdtemp(prefix="d5-action-")
    try:
        site = Path(tmpdir) / "site"
        site.mkdir()

        (site / "input.txt").write_text("data\n")

        def write_output(S):
            from husks.build.site import write_text, site_path
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
        history_file = site / ".traces" / "worker.history.jsonl"
        records = [json.loads(line) for line in history_file.read_text().splitlines()]
        assert len(records) == 1

        record = records[0]
        assert "cached" in record
        assert record["cached"] is False, "action rules should not be cached"

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_history_includes_recipe_digest():
    """History includes recipe digest for cache correlation."""
    from husks.build import build, rule, oracle

    tmpdir = tempfile.mkdtemp(prefix="d5-digest-")
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

        # Read history
        history_file = site / ".traces" / "worker.history.jsonl"
        records = [json.loads(line) for line in history_file.read_text().splitlines()]

        record = records[0]
        assert "recipe_digest" in record
        assert isinstance(record["recipe_digest"], str)
        assert len(record["recipe_digest"]) == 64, "should be SHA-256 hex"

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_multiple_cache_reuses_recorded():
    """Multiple cache reuses each create history entry."""
    from husks.build import build, rule, oracle

    tmpdir = tempfile.mkdtemp(prefix="d5-multiple-")
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

        # First build
        S1 = build("demo", 10, node, site=str(site), oracle_backend=stub_oracle)

        # Second build (cache hit 1)
        (site / "output.txt").unlink()
        S2 = build("demo", 10, node, site=str(site), oracle_backend=stub_oracle)

        # Third build (cache hit 2)
        (site / "output.txt").unlink()
        S3 = build("demo", 10, node, site=str(site), oracle_backend=stub_oracle)

        # Read history
        history_file = site / ".traces" / "worker.history.jsonl"
        records = [json.loads(line) for line in history_file.read_text().splitlines()]
        assert len(records) == 3

        # First: cache miss
        assert records[0]["cached"] is False

        # Second and third: cache hits
        assert records[1]["cached"] is True
        assert records[2]["cached"] is True

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_cache_field_in_all_records():
    """All history records have cached field for consistency."""
    from husks.build import build, rule, oracle, action

    tmpdir = tempfile.mkdtemp(prefix="d5-all-records-")
    try:
        site = Path(tmpdir) / "site"
        site.mkdir()

        (site / "input1.txt").write_text("data\n")
        (site / "input2.txt").write_text("data\n")

        def stub_oracle(S, rule_name, recipe, outputs):
            from husks.build.site import write_text, site_path
            write_text(site_path(S, outputs[0], write=True), "result\n")
            return {"tokens_in": 100, "tokens_out": 50, "cost_usd": 0.001, "fuel_steps": 1}

        def write_output(S):
            from husks.build.site import write_text, site_path
            Path(site_path(S, "action_output.txt", write=True)).write_text("action\n")

        # Build with oracle and action rules
        oracle_node = rule(
            "oracle_rule",
            inputs=["input1.txt"],
            outputs=["oracle_output.txt"],
            recipe=oracle(prompt="Test", fuel=5),
        )

        action_node = rule(
            "action_rule",
            inputs=["input2.txt"],
            outputs=["action_output.txt"],
            recipe=action(write_output),
        )

        S1 = build("demo", 10, oracle_node, site=str(site), oracle_backend=stub_oracle)
        S2 = build("demo", 10, action_node, site=str(site))

        # Check both history files have cached field
        oracle_history = site / ".traces" / "oracle_rule.history.jsonl"
        action_history = site / ".traces" / "action_rule.history.jsonl"

        oracle_records = [json.loads(line) for line in oracle_history.read_text().splitlines()]
        action_records = [json.loads(line) for line in action_history.read_text().splitlines()]

        # All records should have cached field
        for record in oracle_records + action_records:
            assert "cached" in record, "all history records should have cached field"

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)
