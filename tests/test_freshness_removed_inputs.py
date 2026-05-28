"""Test that removing inputs from a rule makes it stale."""

import tempfile
import shutil
from pathlib import Path


def test_rule_becomes_stale_when_input_removed():
    """Rule must be stale if an input is removed from its declaration.

    Regression test: A rule previously sealed with inputs [a.txt, b.txt]
    should become stale when re-declared with only [a.txt], even if a.txt
    hasn't changed and the recipe is identical. The removed input represents
    a dependency change that should trigger re-evaluation.
    """
    from husks.build import build, rule

    tmpdir = tempfile.mkdtemp(prefix="removed-input-test-")
    try:
        site = Path(tmpdir) / "site"
        site.mkdir()

        # Create input files
        (site / "a.txt").write_text("content A\n")
        (site / "b.txt").write_text("content B\n")

        # First build: rule with two inputs, shell recipe
        node1 = rule(
            "copier",
            inputs=["a.txt", "b.txt"],
            outputs=["out.txt"],
            run="cat a.txt > out.txt",  # Only uses a.txt despite declaring b.txt
        )

        S1 = build("removed-input", 10, node1, site=str(site))
        assert S1["status"] == "committed"
        assert (site / "out.txt").read_text() == "content A\n"

        # Second build: same recipe, but b.txt removed from inputs
        node2 = rule(
            "copier",
            inputs=["a.txt"],  # b.txt removed from declaration!
            outputs=["out.txt"],
            run="cat a.txt > out.txt",  # Identical recipe
        )

        S2 = build("removed-input", 10, node2, site=str(site))
        assert S2["status"] == "committed"

        # Critical assertion: rule must fire (be stale), not sealed
        # The prior seal had inputs [a.txt, b.txt], current has [a.txt]
        # Even though the recipe is identical and a.txt hasn't changed,
        # the input list changed, so the rule should be stale
        fired = any(e.get("event") == "fired" and e.get("rule") == "copier"
                    for e in S2["trace"])
        sealed = any(e.get("event") == "sealed" and e.get("rule") == "copier"
                     for e in S2["trace"])

        assert fired and not sealed, \
            "Rule should be stale when input is removed, but was sealed!"

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_rule_becomes_stale_when_input_added():
    """Rule must be stale if an input is added to its declaration.

    This should already work (new input will have old_hash == ""), but
    we test it for completeness.
    """
    from husks.build import build, rule, action

    tmpdir = tempfile.mkdtemp(prefix="added-input-test-")
    try:
        site = Path(tmpdir) / "site"
        site.mkdir()

        # Create input files
        (site / "a.txt").write_text("content A\n")
        (site / "b.txt").write_text("content B\n")

        # First build: rule with one input
        def read_a_action(S):
            from husks.build.site import site_path, read_text, write_text
            a = read_text(site_path(S, "a.txt"))
            write_text(site_path(S, "out.txt", write=True), a)

        node1 = rule(
            "reader",
            inputs=["a.txt"],
            outputs=["out.txt"],
            recipe=action(read_a_action),
        )

        S1 = build("added-input", 10, node1, site=str(site))
        assert S1["status"] == "committed"
        assert (site / "out.txt").read_text() == "content A\n"

        # Second build: add b.txt to inputs
        def concat_action(S):
            from husks.build.site import site_path, read_text, write_text
            a = read_text(site_path(S, "a.txt"))
            b = read_text(site_path(S, "b.txt"))
            write_text(site_path(S, "out.txt", write=True), a + b)

        node2 = rule(
            "reader",
            inputs=["a.txt", "b.txt"],  # b.txt added!
            outputs=["out.txt"],
            recipe=action(concat_action),
        )

        S2 = build("added-input", 10, node2, site=str(site))
        assert S2["status"] == "committed"

        # Rule should fire (be stale) because a new input was added
        fired = any(e.get("event") == "fired" and e.get("rule") == "reader"
                    for e in S2["trace"])
        sealed = any(e.get("event") == "sealed" and e.get("rule") == "reader"
                     for e in S2["trace"])

        assert fired and not sealed, \
            "Rule should be stale when input is added!"

        assert (site / "out.txt").read_text() == "content A\ncontent B\n"

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)
