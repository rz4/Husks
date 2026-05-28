"""
test_13_trial_fuel.py -- Trial branches must charge global fuel.

Each trial branch fired costs 1 global fuel. A trial with 3 branches
and global fuel=2 fires at most 2 branches.
"""

import shutil
import tempfile

from conftest import make_site


def _stub_oracle(S, rule_name, recipe, outputs):
    """Oracle that writes placeholder outputs."""
    from husks.build import site_path, write_text
    for o in outputs:
        write_text(site_path(S, o), f"output from {rule_name}\n")
    return {"tokens_in": 10, "tokens_out": 10, "cost_usd": 0.001, "fuel_steps": 1}


def test_trial_charges_global_fuel():
    """A trial with 3 branches at global fuel=4 should fire all 3, leaving fuel=0.

    burn() is called for the rule itself (1 fuel) + 3 branches (3 fuel) = 4 total.
    """
    from husks.build import build, rule, trial, oracle
    tmpdir = tempfile.mkdtemp(prefix="trial-fuel-")
    try:
        site = make_site(tmpdir)
        branch_a = oracle(prompt="A", tools=["write-file"], fuel=1)
        branch_a["name"] = "a"
        branch_b = oracle(prompt="B", tools=["write-file"], fuel=1)
        branch_b["name"] = "b"
        branch_c = oracle(prompt="C", tools=["write-file"], fuel=1)
        branch_c["name"] = "c"
        t = trial(branch_a, branch_b, branch_c)
        node = rule(
            "picker",
            inputs=["input.txt"],
            outputs=["result.txt"],
            recipe=t,
        )
        S = build("trial-fuel-test", 4, node, site=site, oracle_backend=_stub_oracle)
        # 1 burn for the rule + 3 burns for branches = 4 total from initial 4
        assert S["fuel"] == 0, f"expected fuel=0, got {S['fuel']}"
        assert S["status"] == "committed"
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_trial_stops_at_fuel_limit():
    """A trial with 3 branches at global fuel=3 fires only 2 branches.

    burn() for the rule itself costs 1, leaving 2 for branches.
    """
    from husks.build import build, rule, trial, oracle
    tmpdir = tempfile.mkdtemp(prefix="trial-fuel-limit-")
    try:
        site = make_site(tmpdir)
        branch_a = oracle(prompt="A", tools=["write-file"], fuel=1)
        branch_a["name"] = "a"
        branch_b = oracle(prompt="B", tools=["write-file"], fuel=1)
        branch_b["name"] = "b"
        branch_c = oracle(prompt="C", tools=["write-file"], fuel=1)
        branch_c["name"] = "c"
        t = trial(branch_a, branch_b, branch_c)
        node = rule(
            "picker",
            inputs=["input.txt"],
            outputs=["result.txt"],
            recipe=t,
        )
        S = build("trial-fuel-limit", 3, node, site=site, oracle_backend=_stub_oracle)
        # 1 for rule + 2 for branches = 3 total; 3rd branch never fires
        assert S["fuel"] == 0, f"expected fuel=0, got {S['fuel']}"
        # Build should still commit (verdict picks from 2 successful branches)
        assert S["status"] == "committed"
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_trial_halts_at_zero_fuel():
    """A trial at fuel=1 fires the rule but can fire 0 branches -> halt."""
    from husks.build import build, rule, trial, oracle
    tmpdir = tempfile.mkdtemp(prefix="trial-fuel-zero-")
    try:
        site = make_site(tmpdir)
        branch_a = oracle(prompt="A", tools=["write-file"], fuel=1)
        branch_a["name"] = "a"
        t = trial(branch_a)
        node = rule(
            "picker",
            inputs=["input.txt"],
            outputs=["result.txt"],
            recipe=t,
        )
        S = build("trial-fuel-zero", 1, node, site=site, oracle_backend=_stub_oracle)
        # 1 fuel for the rule itself, then 0 fuel left for any branch
        # burn on first branch should exhaust fuel -> halt
        assert S["status"] == "halted"
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_trial_branch_history_records_actual_fuel_steps():
    """Trial branch history records actual oracle fuel_steps, not hardcoded 1.

    Global fuel burn is always 1 per branch, but the convergence history
    for each branch should record the actual fuel_steps (tool calls) that
    the oracle used within that branch.
    """
    from husks.build import build, rule, trial, oracle
    from husks.designs.convergence import read_history

    tmpdir = tempfile.mkdtemp(prefix="trial-fuel-steps-")
    try:
        site = make_site(tmpdir)

        # Oracle backend that uses 5 tool steps
        def oracle_with_five_steps(S, rule_name, recipe, outputs):
            from husks.build import site_path, write_text
            write_text(site_path(S, outputs[0], write=True), f"output from {rule_name}\n")
            return {
                "tokens_in": 50,
                "tokens_out": 25,
                "cost_usd": 0.005,
                "fuel_steps": 5,  # Oracle used 5 tool calls
            }

        # Trial with 2 branches, each oracle uses fuel=10 (allowing up to 10 steps)
        branch_a = oracle(prompt="Branch A", fuel=10)
        branch_a["name"] = "branch-a"
        branch_b = oracle(prompt="Branch B", fuel=10)
        branch_b["name"] = "branch-b"

        node = rule(
            "trial-rule",
            inputs=["input.txt"],
            outputs=["result.txt"],
            recipe=trial(branch_a, branch_b),
        )

        # Build with global fuel=3 (1 for rule + 2 for branches)
        S = build(
            "trial-fuel-steps",
            3,
            node,
            site=site,
            oracle_backend=oracle_with_five_steps,
        )

        assert S["status"] == "committed", "Build should succeed"
        # Global fuel should be 0 (1 rule + 2 branches = 3 burns)
        assert S["fuel"] == 0, f"Expected fuel=0 after 3 burns, got {S['fuel']}"

        # Check branch history: fuel_consumed should be 5 (actual steps), not 1
        history_a = read_history(site, "trial-rule.branch-a")
        assert len(history_a) == 1, "Branch A should have 1 history entry"
        assert history_a[0]["fuel_consumed"] == 5, \
            f"Branch A history should record fuel_consumed=5, got {history_a[0]['fuel_consumed']}"

        history_b = read_history(site, "trial-rule.branch-b")
        assert len(history_b) == 1, "Branch B should have 1 history entry"
        assert history_b[0]["fuel_consumed"] == 5, \
            f"Branch B history should record fuel_consumed=5, got {history_b[0]['fuel_consumed']}"

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_trial_action_branch_uses_store_usage():
    """Trial action branch should use branch store usage, not global trace scan.

    Action branches that make nested oracle calls should report usage from
    the branch store's accumulated totals (BS["usage"]), not by scanning
    global trace events which could be incorrect or mix costs.
    """
    from husks.build import build, rule, trial, action, oracle
    from husks.build.eval import eval_oracle
    from pathlib import Path
    import json

    tmpdir = tempfile.mkdtemp(prefix="trial-action-store-")
    try:
        site = make_site(tmpdir)

        # Stub oracle backend with known usage
        def stub_oracle_with_usage(S, rule_name, recipe, outputs):
            from husks.build import write_text, site_path
            write_text(site_path(S, outputs[0], write=True), "action output\n")
            return {
                "tokens_in": 150,
                "tokens_out": 75,
                "cost_usd": 0.0025,
                "fuel_steps": 3,
            }

        # Action that calls an oracle, accumulating usage in S
        def action_with_oracle(S):
            from husks.build import write_text, site_path
            # Call oracle directly - usage accumulates in S["usage"]
            oracle_recipe = oracle(prompt="Test oracle", fuel=5)
            eval_oracle(S, "nested-oracle", oracle_recipe, ["result.txt"])

        # Trial with one action branch
        branch = action(action_with_oracle)
        branch["name"] = "action-branch"

        node = rule(
            "action-trial",
            outputs=["result.txt"],
            recipe=trial(branch),
        )

        S = build(
            "trial-action-store",
            2,  # 1 for trial rule + 1 for action branch
            node,
            site=site,
            oracle_backend=stub_oracle_with_usage,
        )

        assert S["status"] == "committed", "Build should succeed"

        # Read trial report to verify branch usage
        report_path = Path(site) / ".traces" / "action-trial.trial.json"
        assert report_path.exists(), "Trial report should exist"

        with open(report_path) as f:
            report = json.load(f)

        assert len(report["branches"]) == 1, "Should have 1 branch"
        branch = report["branches"][0]

        # Verify cost matches what oracle returned (via store, not trace scan)
        # This proves we're using BS["usage"] not T._oracle_events
        assert branch["cost_usd"] == 0.0025, \
            f"Expected cost_usd=0.0025 from store, got {branch['cost_usd']}"
        assert branch["selected"] is True, "Branch should be selected as winner"

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)
