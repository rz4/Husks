"""Test that oracle usage is persisted in Store, not global tracker."""

import tempfile
import shutil
from pathlib import Path


def test_usage_accumulated_in_store():
    """Oracle usage must be accumulated in Store during build.

    Regression test: usage tracking moved from global get_usage() tracker
    to Store["usage"] for single source of truth.
    """
    from husks.build import build, rule, oracle

    tmpdir = tempfile.mkdtemp(prefix="usage-store-test-")
    try:
        site = Path(tmpdir) / "site"
        site.mkdir()

        # Stub oracle backend that returns known usage
        def stub_oracle(S, rule_name, recipe, outputs):
            from husks.build import write_path
            for o in outputs:
                output_path = write_path(S, o)
                Path(output_path).write_text(f"output from {rule_name}\n")
            return {
                "tokens_in": 100,
                "tokens_out": 50,
                "cost_usd": 0.005,
                "fuel_steps": 1,
            }

        # Build with two oracle rules in sequence
        first = rule(
            "first-oracle",
            outputs=["first.txt"],
            recipe=oracle("first prompt"),
        )

        second = rule(
            "second-oracle",
            inputs=["first.txt"],
            outputs=["second.txt"],
            recipe=oracle("second prompt"),
        )

        # Link them: second depends on first
        second["children"] = [first]
        node = second

        S = build("usage-test", 10, node, site=str(site), oracle_backend=stub_oracle)

        # Verify usage is in Store
        assert "usage" in S, "Store must have usage field"
        usage = S["usage"]

        # Check total usage (2 oracle calls)
        assert usage["total_cost_usd"] == 0.010, \
            f"Expected total cost 0.010, got {usage['total_cost_usd']}"
        assert usage["total_input_tokens"] == 200, \
            f"Expected 200 input tokens, got {usage['total_input_tokens']}"
        assert usage["total_output_tokens"] == 100, \
            f"Expected 100 output tokens, got {usage['total_output_tokens']}"

        # Check per-rule usage
        assert "by_rule" in usage, "Usage must track per-rule breakdown"
        assert "first-oracle" in usage["by_rule"]
        assert "second-oracle" in usage["by_rule"]

        # First oracle
        first = usage["by_rule"]["first-oracle"]
        assert first["cost_usd"] == 0.005
        assert first["input_tokens"] == 100
        assert first["output_tokens"] == 50

        # Second oracle
        second = usage["by_rule"]["second-oracle"]
        assert second["cost_usd"] == 0.005
        assert second["input_tokens"] == 100
        assert second["output_tokens"] == 50

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_report_uses_store_usage():
    """Report assembly must use usage from Store, not global tracker.

    This ensures the report's cost data comes from the build's single
    source of truth (the Store) rather than global state.
    """
    from husks.build import build, rule, oracle
    from husks.report import assemble
    from husks.utils import trace as T

    tmpdir = tempfile.mkdtemp(prefix="report-usage-test-")
    try:
        site = Path(tmpdir) / "site"
        site.mkdir()

        def stub_oracle(S, rule_name, recipe, outputs):
            from husks.build import write_path
            for o in outputs:
                output_path = write_path(S, o)
                Path(output_path).write_text(f"output from {rule_name}\n")
            return {
                "tokens_in": 100,
                "tokens_out": 50,
                "cost_usd": 0.005,
                "fuel_steps": 1,
            }

        node = rule(
            "test-oracle",
            outputs=["output.txt"],
            recipe=oracle("test prompt"),
        )

        S = build("report-test", 10, node, site=str(site), oracle_backend=stub_oracle)

        # Verify Store has usage (the single source of truth)
        assert "usage" in S
        assert S["usage"]["total_cost_usd"] == 0.005

        # Create design dict that matches the build for report assembly
        design = {
            "name": "report-test",
            "fuel": 10,
            "rules": [
                {
                    "name": "test-oracle",
                    "kind": "oracle",
                    "outputs": ["output.txt"],
                    "prompt": "test prompt",
                }
            ],
        }

        # Assemble report (gets usage from Store, not global tracker)
        report = assemble(S, T, design)

        # Verify report cost comes from Store
        assert report["cost"]["paid"] == 0.005, \
            f"Report should show paid cost from Store, got {report['cost']['paid']}"

        # Verify per-node cost
        nodes = report["nodes"]
        assert len(nodes) == 1
        node_cost = nodes[0]["cost"]["this_run"]
        assert node_cost == 0.005, \
            f"Node cost should come from Store, got {node_cost}"

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_usage_persists_across_multiple_builds():
    """Each build gets its own isolated usage tracking in its Store.

    Verifies that usage doesn't leak between builds and each build
    maintains its own isolated cost accounting.
    """
    from husks.build import build, rule, oracle

    tmpdir = tempfile.mkdtemp(prefix="multi-build-usage-")
    try:
        site = Path(tmpdir) / "site"
        site.mkdir()

        def stub_oracle(S, rule_name, recipe, outputs):
            from husks.build import write_path
            for o in outputs:
                output_path = write_path(S, o)
                Path(output_path).write_text(f"output from {rule_name}\n")
            return {
                "tokens_in": 50,
                "tokens_out": 25,
                "cost_usd": 0.002,
                "fuel_steps": 1,
            }

        node = rule(
            "oracle-rule",
            outputs=["output.txt"],
            recipe=oracle("test prompt"),
        )

        # First build
        S1 = build("build-1", 10, node, site=str(site), oracle_backend=stub_oracle)
        assert S1["usage"]["total_cost_usd"] == 0.002

        # Modify input to trigger rebuild
        (site / "trigger.txt").write_text("change\n")

        # Second build (new Store instance)
        node2 = rule(
            "oracle-rule",
            inputs=["trigger.txt"],
            outputs=["output.txt"],
            recipe=oracle("test prompt"),
        )
        S2 = build("build-2", 10, node2, site=str(site), oracle_backend=stub_oracle)

        # Each build has independent usage tracking
        assert S1["usage"]["total_cost_usd"] == 0.002, "First build usage unchanged"
        assert S2["usage"]["total_cost_usd"] == 0.002, "Second build has own usage"

        # Verify they're different Store instances
        assert S1 is not S2, "Each build should have its own Store"

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)
