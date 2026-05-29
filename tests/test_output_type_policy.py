"""
test_output_type_policy.py -- Tests for Beta B3 output type policy.

Beta Gate B3: Define output type policy.

For beta, declared outputs must be regular files only. Reject directories,
symlinks (broken or not), and special files before sealing.
"""

import tempfile
import shutil
import os
from pathlib import Path


def test_regular_file_output_accepted():
    """Regular files are accepted as valid outputs."""
    from husks.build import build, rule, action
    from husks.build.site import site_path

    tmpdir = tempfile.mkdtemp(prefix="b3-regular-")
    try:
        site = Path(tmpdir) / "site"
        site.mkdir()

        def write_regular_file(S):
            output = site_path(S, "output.txt", write=True)
            Path(output).write_text("regular file\n")

        node = rule(
            "write-file",
            outputs=["output.txt"],
            recipe=action(write_regular_file),
        )

        S = build("regular-file", 10, node, site=str(site))
        assert S["status"] == "committed"
        assert (site / "output.txt").is_file()

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_directory_output_rejected():
    """Directories are rejected as outputs."""
    from husks.build import build, rule, action
    from husks.build.site import site_path

    tmpdir = tempfile.mkdtemp(prefix="b3-directory-")
    try:
        site = Path(tmpdir) / "site"
        site.mkdir()

        def write_directory(S):
            output = site_path(S, "output_dir", write=True)
            Path(output).mkdir(parents=True, exist_ok=True)
            # Create a file inside to make it a real directory
            (Path(output) / "file.txt").write_text("inside\n")

        node = rule(
            "write-dir",
            outputs=["output_dir"],
            recipe=action(write_directory),
        )

        S = build("directory-output", 10, node, site=str(site))
        assert S["status"] == "halted"
        assert "produced directory output" in S["value"]
        assert "must be regular files, not directories" in S["value"]

        # Seal should not exist
        seal = site / ".traces" / "write-dir.seal"
        assert not seal.exists()

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_symlink_output_rejected():
    """Symlinks are rejected as outputs."""
    from husks.build import build, rule, action
    from husks.build.site import site_path

    tmpdir = tempfile.mkdtemp(prefix="b3-symlink-")
    try:
        site = Path(tmpdir) / "site"
        site.mkdir()

        # Create a target file
        (site / "target.txt").write_text("target\n")

        def write_symlink(S):
            output = site_path(S, "link.txt", write=True)
            # Create symlink to existing file
            target = site_path(S, "target.txt")
            os.symlink(target, output)

        node = rule(
            "write-link",
            outputs=["link.txt"],
            recipe=action(write_symlink),
        )

        S = build("symlink-output", 10, node, site=str(site))
        assert S["status"] == "halted"
        assert "produced symlink output" in S["value"]
        assert "must be regular files, not symlinks" in S["value"]

        # Seal should not exist
        seal = site / ".traces" / "write-link.seal"
        assert not seal.exists()

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_broken_symlink_output_rejected():
    """Broken symlinks are rejected as outputs."""
    from husks.build import build, rule, action
    from husks.build.site import site_path

    tmpdir = tempfile.mkdtemp(prefix="b3-broken-link-")
    try:
        site = Path(tmpdir) / "site"
        site.mkdir()

        def write_broken_symlink(S):
            output = site_path(S, "broken_link.txt", write=True)
            # Create symlink to nonexistent file
            os.symlink("/nonexistent/path", output)

        node = rule(
            "write-broken-link",
            outputs=["broken_link.txt"],
            recipe=action(write_broken_symlink),
        )

        S = build("broken-symlink", 10, node, site=str(site))
        assert S["status"] == "halted"
        assert "produced symlink output" in S["value"]

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_fifo_output_rejected():
    """FIFOs (named pipes) are rejected as outputs."""
    from husks.build import build, rule, action
    from husks.build.site import site_path

    tmpdir = tempfile.mkdtemp(prefix="b3-fifo-")
    try:
        site = Path(tmpdir) / "site"
        site.mkdir()

        def write_fifo(S):
            output = site_path(S, "pipe", write=True)
            # Create a FIFO
            os.mkfifo(output)

        node = rule(
            "write-fifo",
            outputs=["pipe"],
            recipe=action(write_fifo),
        )

        S = build("fifo-output", 10, node, site=str(site))
        assert S["status"] == "halted"
        assert "produced special file output" in S["value"]
        assert "must be regular files" in S["value"]

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_output_type_policy_with_transaction():
    """BuildTransaction enforces output type policy."""
    from husks.build.eval import BuildTransaction
    from husks.build.site import fresh_store, site_path

    tmpdir = tempfile.mkdtemp(prefix="b3-txn-")
    try:
        site = Path(tmpdir) / "site"
        site.mkdir()

        S = fresh_store(str(site), fuel=10)

        # Test directory rejection
        with BuildTransaction(S, ["output_dir"]) as txn:
            output = site_path(S, "output_dir", write=True)
            Path(output).mkdir(parents=True)

            try:
                txn.validate_outputs("test", {"type": "action"})
                assert False, "Should have raised RuntimeError"
            except RuntimeError as e:
                assert "produced directory output" in str(e)

        # Test symlink rejection
        (site / "target.txt").write_text("target\n")
        with BuildTransaction(S, ["link.txt"]) as txn:
            output = site_path(S, "link.txt", write=True)
            os.symlink(str(site / "target.txt"), output)

            try:
                txn.validate_outputs("test", {"type": "action"})
                assert False, "Should have raised RuntimeError"
            except RuntimeError as e:
                assert "produced symlink output" in str(e)

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_multiple_outputs_one_invalid_type():
    """If one output has invalid type, validation fails before promoting any."""
    from husks.build import build, rule, action
    from husks.build.site import site_path

    tmpdir = tempfile.mkdtemp(prefix="b3-mixed-")
    try:
        site = Path(tmpdir) / "site"
        site.mkdir()

        def write_mixed_outputs(S):
            # Write valid regular file
            file1 = site_path(S, "valid.txt", write=True)
            Path(file1).write_text("valid\n")

            # Write invalid directory
            dir1 = site_path(S, "invalid_dir", write=True)
            Path(dir1).mkdir()

        node = rule(
            "mixed-outputs",
            outputs=["valid.txt", "invalid_dir"],
            recipe=action(write_mixed_outputs),
        )

        S = build("mixed-types", 10, node, site=str(site))
        assert S["status"] == "halted"
        assert "produced directory output" in S["value"]

        # Neither output should be promoted (atomic validation)
        # The staging failed, so outputs weren't promoted
        # But the directory was created in staging

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_empty_file_still_valid_for_actions():
    """Empty regular files are valid for action recipes (only oracles reject empty)."""
    from husks.build import build, rule, action
    from husks.build.site import site_path

    tmpdir = tempfile.mkdtemp(prefix="b3-empty-")
    try:
        site = Path(tmpdir) / "site"
        site.mkdir()

        def write_empty_file(S):
            output = site_path(S, "empty.txt", write=True)
            Path(output).write_text("")

        node = rule(
            "write-empty",
            outputs=["empty.txt"],
            recipe=action(write_empty_file),
        )

        S = build("empty-action", 10, node, site=str(site))
        assert S["status"] == "committed"
        assert (site / "empty.txt").is_file()
        assert (site / "empty.txt").stat().st_size == 0

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_nested_output_paths_still_regular_files():
    """Outputs in nested directories must still be regular files."""
    from husks.build import build, rule, action
    from husks.build.site import site_path

    tmpdir = tempfile.mkdtemp(prefix="b3-nested-")
    try:
        site = Path(tmpdir) / "site"
        site.mkdir()

        def write_nested_file(S):
            output = site_path(S, "subdir/nested.txt", write=True)
            Path(output).parent.mkdir(parents=True, exist_ok=True)
            Path(output).write_text("nested content\n")

        node = rule(
            "write-nested",
            outputs=["subdir/nested.txt"],
            recipe=action(write_nested_file),
        )

        S = build("nested-file", 10, node, site=str(site))
        assert S["status"] == "committed"
        assert (site / "subdir" / "nested.txt").is_file()

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)
