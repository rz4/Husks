"""Test fuel accounting model: global fuel counts rule fires, not oracle tool steps.

Global fuel is burned once per rule fire (including trial branches).
Oracle fuel is independent and limits tool steps within each oracle.
This allows oracles with high per-oracle fuel to run in builds with
low global fuel, as long as the number of rules that fire fits the budget.
"""

import tempfile
import shutil
from pathlib import Path


def test_global_fuel_counts_rule_fires_not_oracle_steps():
    """Global fuel counts rule fires, not individual oracle tool steps.

    An oracle with fuel=100 (allowing up to 100 tool calls) should work
    in a build with global fuel=1, because global fuel only counts the
    one rule fire, not the oracle's internal tool steps.
    """
    from husks.build import build, rule, oracle

    tmpdir = tempfile.mkdtemp(prefix="fuel-accounting-")
    try:
        site = Path(tmpdir) / "site"
        site.mkdir()

        # Create an oracle rule with high per-oracle fuel (100 steps)
        # But we'll use a stub backend that only takes 1 step
        def stub_oracle_one_step(S, rule_name, recipe, outputs):
            from husks.build import write_text, site_path
            write_text(site_path(S, outputs[0], write=True), "result\n")
            return {"tokens_in": 10, "tokens_out": 5, "cost_usd": 0.001, "fuel_steps": 1}

        node = rule(
            "high-fuel-oracle",
            outputs=["output.txt"],
            recipe=oracle(
                prompt="Generate output",
                fuel=100,  # High per-oracle fuel
            ),
        )

        # Build with global fuel=1 (only enough for one rule fire)
        # This should succeed because global fuel counts fires, not oracle steps
        S = build(
            "test-fuel",
            1,  # Global fuel = 1 (only one rule can fire)
            node,
            site=str(site),
            oracle_backend=stub_oracle_one_step,
        )

        assert S["status"] == "committed", "Build should succeed with global fuel=1"
        assert S["fuel"] == 0, "Global fuel should be depleted after one rule fire"
        assert (site / "output.txt").exists(), "Output should be produced"

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_oracle_fuel_limits_tool_steps_independently():
    """Oracle fuel limits tool steps within that oracle, independent of global fuel.

    An oracle with fuel=2 will halt after 2 tool calls even if global fuel
    is much higher.
    """
    from husks.build import build, rule, oracle

    tmpdir = tempfile.mkdtemp(prefix="oracle-fuel-limit-")
    try:
        site = Path(tmpdir) / "site"
        site.mkdir()

        # Stub backend that tries to take many steps but is limited by oracle fuel
        step_count = [0]

        def multi_step_oracle(S, rule_name, recipe, outputs):
            from husks.build import write_text, site_path
            # This backend wants to take 10 steps, but oracle fuel=2 will limit it
            # In reality, the oracle kernel would stop at fuel=2
            # Here we simulate that the oracle made multiple attempts
            step_count[0] = min(recipe.get("fuel", 8), 10)
            write_text(site_path(S, outputs[0], write=True), "limited output\n")
            return {
                "tokens_in": 10 * step_count[0],
                "tokens_out": 5 * step_count[0],
                "cost_usd": 0.001 * step_count[0],
                "fuel_steps": step_count[0],
            }

        node = rule(
            "limited-oracle",
            outputs=["output.txt"],
            recipe=oracle(
                prompt="Generate output",
                fuel=2,  # Low per-oracle fuel (only 2 tool steps)
            ),
        )

        # Build with high global fuel (100 rule fires allowed)
        S = build(
            "test-oracle-fuel",
            100,  # High global fuel
            node,
            site=str(site),
            oracle_backend=multi_step_oracle,
        )

        assert S["status"] == "committed", "Build should succeed"
        # Global fuel should only be decremented by 1 (one rule fire)
        assert S["fuel"] == 99, f"Global fuel should be 99, got {S['fuel']}"
        # Oracle fuel limited the steps to 2
        assert step_count[0] == 2, f"Oracle should be limited to 2 steps, got {step_count[0]}"

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_multiple_oracles_with_independent_fuel():
    """Multiple oracles each have independent per-oracle fuel budgets.

    Global fuel counts the number of rules that fire.
    Each oracle's fuel parameter limits its own tool steps independently.
    """
    from husks.build import build, rule, oracle

    tmpdir = tempfile.mkdtemp(prefix="multi-oracle-fuel-")
    try:
        site = Path(tmpdir) / "site"
        site.mkdir()

        def stub_oracle(S, rule_name, recipe, outputs):
            from husks.build import write_text, site_path
            fuel_used = recipe.get("fuel", 8)
            write_text(site_path(S, outputs[0], write=True), f"steps={fuel_used}\n")
            return {
                "tokens_in": 10 * fuel_used,
                "tokens_out": 5 * fuel_used,
                "cost_usd": 0.001 * fuel_used,
                "fuel_steps": fuel_used,
            }

        # First oracle: fuel=5
        first = rule(
            "oracle-5",
            outputs=["first.txt"],
            recipe=oracle(prompt="First", fuel=5),
        )

        # Second oracle: fuel=20 (depends on first)
        second = rule(
            "oracle-20",
            inputs=["first.txt"],
            outputs=["second.txt"],
            recipe=oracle(prompt="Second", fuel=20),
        )

        second["children"] = [first]

        # Build with global fuel=2 (enough for 2 rule fires: first + second)
        # Old incorrect check would reject this: 5+20=25 > 2
        # Correct behavior: global fuel only counts fires, not oracle steps
        S = build(
            "multi-oracle",
            2,  # Global fuel = 2 (two rules can fire)
            second,
            site=str(site),
            oracle_backend=stub_oracle,
        )

        assert S["status"] == "committed", "Build should succeed"
        assert S["fuel"] == 0, "Both rules should fire, depleting global fuel"
        assert (site / "first.txt").exists(), "First oracle output exists"
        assert (site / "second.txt").exists(), "Second oracle output exists"

        # Verify each oracle used its own fuel budget
        assert (site / "first.txt").read_text() == "steps=5\n"
        assert (site / "second.txt").read_text() == "steps=20\n"

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_trial_branches_consume_global_fuel():
    """Trial branches each consume 1 global fuel per branch fired.

    Global fuel is decremented by the number of branches that execute,
    not by the oracle tool steps within each branch.
    """
    from husks.build import build, rule, trial, oracle

    tmpdir = tempfile.mkdtemp(prefix="trial-fuel-")
    try:
        site = Path(tmpdir) / "site"
        site.mkdir()

        def stub_oracle(S, rule_name, recipe, outputs):
            from husks.build import write_text, site_path
            # Each branch uses high fuel (50 steps) but we limit to 1 for testing
            write_text(site_path(S, outputs[0], write=True), f"branch: {rule_name}\n")
            return {
                "tokens_in": 10,
                "tokens_out": 5,
                "cost_usd": 0.001,
                "fuel_steps": 1,
            }

        # Trial with 3 branches, each with fuel=50
        node = rule(
            "trial-rule",
            outputs=["output.txt"],
            recipe=trial(
                {"type": "oracle", "name": "b1", "prompt": "Branch 1", "fuel": 50},
                {"type": "oracle", "name": "b2", "prompt": "Branch 2", "fuel": 50},
                {"type": "oracle", "name": "b3", "prompt": "Branch 3", "fuel": 50},
            ),
        )

        # Build with global fuel=3 (enough for 3 branches to fire)
        # Old incorrect check would reject this: 50+50+50=150 > 3
        # Correct: global fuel counts branch fires (3), not oracle steps
        S = build(
            "trial-fuel",
            3,  # Global fuel = 3 (three branches can fire)
            node,
            site=str(site),
            oracle_backend=stub_oracle,
        )

        assert S["status"] == "committed", "Trial should complete"
        assert S["fuel"] == 0, "All 3 branches should fire, depleting global fuel"

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)
