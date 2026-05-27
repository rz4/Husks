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
