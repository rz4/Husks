"""Test that shell commands cannot bypass staging via symlinks."""

import tempfile
import shutil
from pathlib import Path


def test_shell_cannot_bypass_staging_with_symlink():
    """Shell commands must not bypass staging by creating symlinks to live site.

    A malicious or buggy command could try to create a symlink from the
    staging output back to the live site, then write to it. This test
    verifies that such attempts are blocked and the live site is restored.
    """
    from husks.build import build, rule

    tmpdir = tempfile.mkdtemp(prefix="symlink-bypass-test-")
    try:
        site = Path(tmpdir) / "site"
        site.mkdir()

        # Create an existing output in live site
        (site / "out.txt").write_text("original content\n")

        # Command that tries to bypass staging via symlink
        node = rule(
            "symlink-attacker",
            outputs=["out.txt"],
            run=f"ln -s {site}/out.txt out.txt && echo 'bypassed!' > out.txt",
        )

        # Build should halt due to symlink violation
        S = build("symlink-bypass", 10, node, site=str(site))

        assert S["status"] == "halted", \
            "Build should halt when command creates symlink"

        # Critical: live site must be restored to original content
        # even if command wrote through the symlink before detection
        assert (site / "out.txt").read_text() == "original content\n", \
            "Live site was not properly restored after symlink violation!"

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)
