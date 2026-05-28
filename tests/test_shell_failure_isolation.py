"""Test that failed shell actions do not mutate the live site."""

import tempfile
import shutil
from pathlib import Path


def test_failed_shell_action_does_not_mutate_live_site():
    """A shell command that writes output then fails must not mutate live site.

    Regression test: shell actions should run in staging isolation. If a
    command writes files and then exits nonzero, those partial writes must
    not be promoted to the live site.
    """
    from husks.build import build, rule

    tmpdir = tempfile.mkdtemp(prefix="shell-failure-test-")
    try:
        site = Path(tmpdir) / "site"
        site.mkdir()

        # Rule with shell command that writes output then fails
        node = rule(
            "failing-writer",
            outputs=["out.txt"],
            run="echo 'partial output' > out.txt && exit 1",
        )

        # Build should fail (shell command exits 1)
        S = build("shell-failure", 10, node, site=str(site))

        # Build should have halted due to command failure
        assert S["status"] == "halted", f"Expected halted, got {S['status']}"

        # Critical assertion: live site must NOT contain the partial output
        # The failed command wrote to staging, but staging should not be promoted
        assert not (site / "out.txt").exists(), \
            "Failed shell command leaked partial output to live site!"

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_failed_shell_preserves_existing_output():
    """If a shell command fails, existing live site outputs must be preserved.

    When a rule re-runs with new inputs and the command fails, the old
    (good) output must remain unchanged in the live site.
    """
    from husks.build import build, rule

    tmpdir = tempfile.mkdtemp(prefix="shell-failure-preserve-test-")
    try:
        site = Path(tmpdir) / "site"
        site.mkdir()

        # Create input file
        (site / "input.txt").write_text("initial\n")

        # First build: successful command
        node1 = rule(
            "processor",
            inputs=["input.txt"],
            outputs=["out.txt"],
            run="cp input.txt out.txt",
        )
        S1 = build("preserve-test", 10, node1, site=str(site))
        assert S1["status"] == "committed"
        assert (site / "out.txt").read_text() == "initial\n"

        # Modify input
        (site / "input.txt").write_text("updated\n")

        # Second build: command that writes then fails
        node2 = rule(
            "processor",
            inputs=["input.txt"],
            outputs=["out.txt"],
            run="echo 'bad partial' > out.txt && exit 1",
        )
        S2 = build("preserve-test", 10, node2, site=str(site))

        # Build should halt
        assert S2["status"] == "halted"

        # Critical: live site must still have the OLD (good) output,
        # not the partial output from the failed command
        assert (site / "out.txt").read_text() == "initial\n", \
            "Failed command corrupted existing live site output!"

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)
