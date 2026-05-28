"""Test that shell actions write to staging directory, not live site."""

import tempfile
import shutil
from pathlib import Path


def test_shell_action_respects_staging():
    """Shell commands must write to staging dir, not follow symlinks to live site.

    Regression test for the bug where shell commands like 'cp input.txt out.txt'
    would follow symlinks created by the staging context and write directly to
    the live site instead of the staging directory.
    """
    from husks.build import build, rule

    tmpdir = tempfile.mkdtemp(prefix="shell-staging-test-")
    try:
        site = Path(tmpdir) / "site"
        site.mkdir()

        # Create input file
        (site / "input.txt").write_text("initial content\n")

        # Define rule with shell command that copies input to output
        node = rule(
            "copier",
            inputs=["input.txt"],
            outputs=["out.txt"],
            run="cp input.txt out.txt",
        )

        # First build: creates out.txt
        S1 = build("shell-staging", 10, node, site=str(site))
        assert S1["status"] == "committed"
        assert (site / "out.txt").read_text() == "initial content\n"

        # Modify input for second build
        (site / "input.txt").write_text("updated content\n")

        # Second build: triggers staging since out.txt already exists
        # The shell command must write to staging, not follow symlink to live site
        S2 = build("shell-staging", 10, node, site=str(site))
        assert S2["status"] == "committed"
        assert (site / "out.txt").read_text() == "updated content\n"

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_shell_stdout_capture_when_no_output_created():
    """When shell command doesn't create output, stdout should be captured."""
    from husks.build import build, rule

    tmpdir = tempfile.mkdtemp(prefix="shell-stdout-test-")
    try:
        site = Path(tmpdir) / "site"
        site.mkdir()

        # Shell command that outputs to stdout but doesn't create a file
        node = rule(
            "echo",
            outputs=["result.txt"],
            run="echo 'hello from stdout'",
        )

        S = build("shell-stdout", 10, node, site=str(site))
        assert S["status"] == "committed"
        assert (site / "result.txt").exists()
        assert "hello from stdout" in (site / "result.txt").read_text()

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)
