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


def test_nested_staging_with_parent_directory_symlinks():
    """Multiple rules writing to same directory must not interfere via symlinks.

    Regression test for the bug where:
    - Rule A writes dir/a.txt (creates staging with dir/ as symlink to site/dir/)
    - Rule B writes dir/b.txt (stage/dir/ is still a symlink, so writes through to site/dir/)

    The fix ensures parent directory symlinks are broken and replaced with real
    staged directories before writes, so each rule writes to the staging area.
    """
    from husks.build import build, rule

    tmpdir = tempfile.mkdtemp(prefix="nested-staging-test-")
    try:
        site = Path(tmpdir) / "site"
        site.mkdir()

        # Create input directory with one file
        input_dir = site / "inputs"
        input_dir.mkdir()
        (input_dir / "source.txt").write_text("source data\n")

        # First build: Rule A writes outputs/a.txt
        rule_a = rule(
            "write-a",
            inputs=["inputs/source.txt"],
            outputs=["outputs/a.txt"],
            run="mkdir -p outputs && echo 'from rule A' > outputs/a.txt",
        )

        S1 = build("nested-staging-a", 10, rule_a, site=str(site))
        assert S1["status"] == "committed", f"Build A failed: {S1['status']}, {S1.get('value')}"
        assert (site / "outputs" / "a.txt").exists(), "outputs/a.txt missing after first build"

        # Second build: Rule B writes outputs/b.txt to the same directory
        # This tests that staging properly breaks the outputs/ symlink when it already exists
        rule_b = rule(
            "write-b",
            inputs=["inputs/source.txt"],
            outputs=["outputs/b.txt"],
            run="echo 'from rule B' > outputs/b.txt",
        )

        S2 = build("nested-staging-b", 10, rule_b, site=str(site))
        assert S2["status"] == "committed", f"Build B failed: {S2['status']}, {S2.get('value')}"

        # Both outputs must exist in the live site
        assert (site / "outputs" / "a.txt").exists(), "outputs/a.txt missing after second build"
        assert (site / "outputs" / "b.txt").exists(), "outputs/b.txt missing after second build"

        # Verify content
        assert (site / "outputs" / "a.txt").read_text().strip() == "from rule A"
        assert (site / "outputs" / "b.txt").read_text().strip() == "from rule B"

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_deeply_nested_staging_path():
    """Test staging with deeply nested paths (dir/subdir/file.txt)."""
    from husks.build import build, rule

    tmpdir = tempfile.mkdtemp(prefix="deep-nested-staging-")
    try:
        site = Path(tmpdir) / "site"
        site.mkdir()

        # Rule writes to a deeply nested path
        node = rule(
            "deep-writer",
            outputs=["level1/level2/level3/deep.txt"],
            run="mkdir -p level1/level2/level3 && echo 'deep content' > level1/level2/level3/deep.txt",
        )

        S = build("deep-nested", 10, node, site=str(site))
        assert S["status"] == "committed", f"Build failed: {S['status']}, {S.get('value')}"

        # Output must exist at the nested path
        deep_file = site / "level1" / "level2" / "level3" / "deep.txt"
        assert deep_file.exists(), "Deeply nested output missing"
        assert deep_file.read_text().strip() == "deep content"

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)
