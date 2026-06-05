"""
test_recipe_identity_audit.py -- Beta Gate C1: Recipe identity audit.

Comprehensive invalidation tests proving that changing any field in a
recipe or node changes the computed digest. Required for artifact
identity and cross-machine equivalence.

Tests cover:
- Action recipes: shell commands, callable actions, args
- Oracle recipes: prompt, tools, fuel, name
- Trial recipes: verdict, branches
- Node-level: inputs, outputs, rule name
"""

import tempfile
import shutil
from pathlib import Path


def test_oracle_prompt_change_changes_digest():
    """Changing oracle prompt must change recipe digest."""
    from husks.build.identity import recipe_to_cse
    from husks.core import recipe_digest

    recipe_a = {
        "type": "oracle",
        "prompt": "Write hello world",
        "tools": [],
        "fuel": 8,
    }
    recipe_b = {
        "type": "oracle",
        "prompt": "Write goodbye world",
        "tools": [],
        "fuel": 8,
    }

    digest_a = recipe_digest(recipe_to_cse(recipe_a))
    digest_b = recipe_digest(recipe_to_cse(recipe_b))

    assert digest_a != digest_b, "different prompts must produce different digests"


def test_oracle_tools_change_changes_digest():
    """Changing oracle tools must change recipe digest."""
    from husks.build.identity import recipe_to_cse
    from husks.core import recipe_digest

    recipe_a = {
        "type": "oracle",
        "prompt": "Process data",
        "tools": ["read", "write"],
        "fuel": 8,
    }
    recipe_b = {
        "type": "oracle",
        "prompt": "Process data",
        "tools": ["read", "write", "bash"],
        "fuel": 8,
    }

    digest_a = recipe_digest(recipe_to_cse(recipe_a))
    digest_b = recipe_digest(recipe_to_cse(recipe_b))

    assert digest_a != digest_b, "different tools must produce different digests"


def test_oracle_fuel_change_changes_digest():
    """Changing oracle fuel must change recipe digest."""
    from husks.build.identity import recipe_to_cse
    from husks.core import recipe_digest

    recipe_a = {
        "type": "oracle",
        "prompt": "Generate code",
        "tools": [],
        "fuel": 8,
    }
    recipe_b = {
        "type": "oracle",
        "prompt": "Generate code",
        "tools": [],
        "fuel": 16,
    }

    digest_a = recipe_digest(recipe_to_cse(recipe_a))
    digest_b = recipe_digest(recipe_to_cse(recipe_b))

    assert digest_a != digest_b, "different fuel must produce different digests"


def test_oracle_name_change_changes_digest():
    """Changing oracle name must change recipe digest."""
    from husks.build.identity import recipe_to_cse
    from husks.core import recipe_digest

    recipe_a = {
        "type": "oracle",
        "name": "writer-v1",
        "prompt": "Write code",
        "tools": [],
        "fuel": 8,
    }
    recipe_b = {
        "type": "oracle",
        "name": "writer-v2",
        "prompt": "Write code",
        "tools": [],
        "fuel": 8,
    }

    digest_a = recipe_digest(recipe_to_cse(recipe_a))
    digest_b = recipe_digest(recipe_to_cse(recipe_b))

    assert digest_a != digest_b, "different names must produce different digests"


def test_callable_action_args_change_changes_digest():
    """Changing callable action args must change recipe digest."""
    from husks.build.identity import recipe_to_cse
    from husks.core import recipe_digest

    def my_action(S, message):
        pass

    recipe_a = {
        "type": "action",
        "fn": my_action,
        "args": ("hello",),
    }
    recipe_b = {
        "type": "action",
        "fn": my_action,
        "args": ("goodbye",),
    }

    digest_a = recipe_digest(recipe_to_cse(recipe_a))
    digest_b = recipe_digest(recipe_to_cse(recipe_b))

    assert digest_a != digest_b, "different args must produce different digests"


def test_callable_action_no_args_vs_empty_args_same_digest():
    """Callable action with no args vs empty args should have same digest."""
    from husks.build.identity import recipe_to_cse
    from husks.core import recipe_digest

    def my_action(S):
        pass

    recipe_a = {
        "type": "action",
        "fn": my_action,
    }
    recipe_b = {
        "type": "action",
        "fn": my_action,
        "args": (),
    }

    digest_a = recipe_digest(recipe_to_cse(recipe_a))
    digest_b = recipe_digest(recipe_to_cse(recipe_b))

    assert digest_a == digest_b, "no args and empty args must be equivalent"


def test_trial_verdict_change_changes_digest():
    """Changing trial verdict policy must change recipe digest."""
    from husks.build.identity import recipe_to_cse
    from husks.core import recipe_digest
    from husks.build.eval import first_valid

    def custom_verdict(results):
        return results[-1]  # Pick last instead of first

    branch = {"type": "action", "fn": lambda S: None}

    recipe_a = {
        "type": "trial",
        "branches": [branch],
        "verdict": first_valid,
    }
    recipe_b = {
        "type": "trial",
        "branches": [branch],
        "verdict": custom_verdict,
    }

    digest_a = recipe_digest(recipe_to_cse(recipe_a))
    digest_b = recipe_digest(recipe_to_cse(recipe_b))

    assert digest_a != digest_b, "different verdicts must produce different digests"


def test_trial_branches_change_changes_digest():
    """Changing trial branches must change recipe digest."""
    from husks.build.identity import recipe_to_cse
    from husks.core import recipe_digest

    def action_a(S):
        pass

    def action_b(S):
        pass

    recipe_a = {
        "type": "trial",
        "branches": [{"type": "action", "fn": action_a}],
        "verdict": None,
    }
    recipe_b = {
        "type": "trial",
        "branches": [{"type": "action", "fn": action_b}],
        "verdict": None,
    }

    digest_a = recipe_digest(recipe_to_cse(recipe_a))
    digest_b = recipe_digest(recipe_to_cse(recipe_b))

    assert digest_a != digest_b, "different branches must produce different digests"


def test_trial_branch_count_change_changes_digest():
    """Changing number of trial branches must change recipe digest."""
    from husks.build.identity import recipe_to_cse
    from husks.core import recipe_digest

    def action(S):
        pass

    branch = {"type": "action", "fn": action}

    recipe_a = {
        "type": "trial",
        "branches": [branch],
        "verdict": None,
    }
    recipe_b = {
        "type": "trial",
        "branches": [branch, branch],
        "verdict": None,
    }

    digest_a = recipe_digest(recipe_to_cse(recipe_a))
    digest_b = recipe_digest(recipe_to_cse(recipe_b))

    assert digest_a != digest_b, "different branch counts must produce different digests"


def test_node_inputs_change_changes_root():
    """Changing node inputs must change build root."""
    from husks.build import build, rule, action
    from conftest import make_site

    tmpdir = tempfile.mkdtemp(prefix="c1-inputs-")
    try:
        site_a = make_site(tmpdir + "/a")
        site_b = make_site(tmpdir + "/b")

        def write_output(S):
            from husks.build.site import write_path
            Path(write_path(S, "out.txt")).write_text("output\n")

        node_a = rule(
            "processor",
            inputs=["input_a.txt"],
            outputs=["out.txt"],
            recipe=action(write_output),
        )
        node_b = rule(
            "processor",
            inputs=["input_b.txt"],
            outputs=["out.txt"],
            recipe=action(write_output),
        )

        Sa = build("inputs-test", 10, node_a, site=site_a)
        Sb = build("inputs-test", 10, node_b, site=site_b)

        assert Sa["build-root"] != Sb["build-root"], (
            "different inputs must produce different roots"
        )
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_node_outputs_change_changes_root():
    """Changing node outputs must change build root."""
    from husks.build import build, rule, action
    from conftest import make_site

    tmpdir = tempfile.mkdtemp(prefix="c1-outputs-")
    try:
        site_a = make_site(tmpdir + "/a")
        site_b = make_site(tmpdir + "/b")

        def write_a(S):
            from husks.build.site import write_path
            Path(write_path(S, "output_a.txt")).write_text("output\n")

        def write_b(S):
            from husks.build.site import write_path
            Path(write_path(S, "output_b.txt")).write_text("output\n")

        node_a = rule(
            "generator",
            outputs=["output_a.txt"],
            recipe=action(write_a),
        )
        node_b = rule(
            "generator",
            outputs=["output_b.txt"],
            recipe=action(write_b),
        )

        Sa = build("outputs-test", 10, node_a, site=site_a)
        Sb = build("outputs-test", 10, node_b, site=site_b)

        assert Sa["build-root"] != Sb["build-root"], (
            "different outputs must produce different roots"
        )
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_node_name_change_changes_root():
    """Changing rule name must change build root."""
    from husks.build import build, rule, action
    from conftest import make_site

    tmpdir = tempfile.mkdtemp(prefix="c1-name-")
    try:
        site_a = make_site(tmpdir + "/a")
        site_b = make_site(tmpdir + "/b")

        def write_output(S):
            from husks.build.site import write_path
            Path(write_path(S, "out.txt")).write_text("output\n")

        node_a = rule(
            "rule-v1",
            outputs=["out.txt"],
            recipe=action(write_output),
        )
        node_b = rule(
            "rule-v2",
            outputs=["out.txt"],
            recipe=action(write_output),
        )

        Sa = build("name-test", 10, node_a, site=site_a)
        Sb = build("name-test", 10, node_b, site=site_b)

        assert Sa["build-root"] != Sb["build-root"], (
            "different rule names must produce different roots"
        )
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_same_recipe_same_inputs_outputs_same_root():
    """Identical recipe, inputs, and outputs must produce same root."""
    from husks.build import build, rule, action
    from conftest import make_site

    tmpdir = tempfile.mkdtemp(prefix="c1-same-")
    try:
        site_a = make_site(tmpdir + "/a")
        site_b = make_site(tmpdir + "/b")

        def write_output(S):
            from husks.build.site import write_path
            Path(write_path(S, "out.txt")).write_text("identical\n")

        # Same rule definition used twice
        node = rule(
            "identical-rule",
            inputs=["in.txt"],
            outputs=["out.txt"],
            recipe=action(write_output),
        )

        Sa = build("same-test", 10, node, site=site_a)
        Sb = build("same-test", 10, node, site=site_b)

        assert Sa["build-root"] == Sb["build-root"], (
            "identical recipe/inputs/outputs must produce same root"
        )
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)
