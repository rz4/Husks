"""Test that file_sig() and content_hash_or_absent() handle directories gracefully.

Both functions should return ABSENT for directories instead of crashing when
trying to read_bytes() or open() a directory path.
"""

import tempfile
import shutil
from pathlib import Path


def test_file_sig_on_directory_returns_absent():
    """file_sig() must return ABSENT for directories, not crash."""
    from husks.build.site import file_sig
    from husks.core import ABSENT

    tmpdir = tempfile.mkdtemp(prefix="file-sig-dir-")
    try:
        # Create a directory
        dir_path = Path(tmpdir) / "mydir"
        dir_path.mkdir()

        # file_sig() should return ABSENT, not crash
        result = file_sig(str(dir_path))
        assert result == ABSENT, f"Expected ABSENT for directory, got {result}"

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_file_sig_on_missing_path_returns_absent():
    """file_sig() must return ABSENT for missing paths."""
    from husks.build.site import file_sig
    from husks.core import ABSENT

    tmpdir = tempfile.mkdtemp(prefix="file-sig-missing-")
    try:
        # Path that doesn't exist
        missing = Path(tmpdir) / "nonexistent.txt"

        result = file_sig(str(missing))
        assert result == ABSENT, f"Expected ABSENT for missing file, got {result}"

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_file_sig_on_regular_file_returns_hash():
    """file_sig() must return content hash for regular files."""
    from husks.build.site import file_sig
    from husks.core import ABSENT, content_hash

    tmpdir = tempfile.mkdtemp(prefix="file-sig-file-")
    try:
        # Create a regular file
        file_path = Path(tmpdir) / "file.txt"
        file_path.write_text("content\n")

        result = file_sig(str(file_path))

        # Should not be ABSENT
        assert result != ABSENT, "Expected hash for regular file, got ABSENT"

        # Should match direct content hash
        expected = content_hash(file_path.read_bytes())
        assert result == expected, f"Expected {expected}, got {result}"

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_content_hash_or_absent_consistency():
    """content_hash_or_absent should behave consistently with file_sig."""
    from husks.build.site import file_sig
    from husks.core import content_hash_or_absent, ABSENT

    tmpdir = tempfile.mkdtemp(prefix="hash-consistency-")
    try:
        # Create test paths
        dir_path = Path(tmpdir) / "dir"
        dir_path.mkdir()

        file_path = Path(tmpdir) / "file.txt"
        file_path.write_text("data\n")

        missing_path = Path(tmpdir) / "missing.txt"

        # Both functions should return ABSENT for directories
        assert file_sig(str(dir_path)) == ABSENT
        assert content_hash_or_absent(str(dir_path)) == ABSENT

        # Both functions should return ABSENT for missing paths
        assert file_sig(str(missing_path)) == ABSENT
        assert content_hash_or_absent(str(missing_path)) == ABSENT

        # Both functions should return same hash for regular files
        file_sig_result = file_sig(str(file_path))
        content_hash_result = content_hash_or_absent(str(file_path))
        assert file_sig_result == content_hash_result
        assert file_sig_result != ABSENT

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_build_with_directory_input_does_not_crash():
    """Build with directory declared as input should not crash during sealing."""
    from husks.build import build, rule

    tmpdir = tempfile.mkdtemp(prefix="build-dir-input-")
    try:
        site = Path(tmpdir) / "site"
        site.mkdir()

        # Create a directory and a file
        input_dir = site / "inputs"
        input_dir.mkdir()
        (input_dir / "data.txt").write_text("content\n")

        # Create a rule that declares the directory as input
        # (This might be a user error, but shouldn't crash)
        node = rule(
            "process-dir",
            inputs=["inputs"],  # Directory path
            outputs=["output.txt"],
            run="echo 'processed' > output.txt",
        )

        # Build should complete without crashing
        S = build("dir-input-test", 10, node, site=str(site))

        # Build should succeed (the directory input will be treated as ABSENT)
        # The build itself will succeed because the shell command creates output.txt
        assert S["status"] == "committed", f"Build failed: {S['status']}, {S.get('value')}"

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_build_with_directory_output_does_not_crash():
    """Build with directory declared as output should not crash during sealing."""
    from husks.build import build, rule

    tmpdir = tempfile.mkdtemp(prefix="build-dir-output-")
    try:
        site = Path(tmpdir) / "site"
        site.mkdir()

        # Create a rule that creates a directory as output
        node = rule(
            "make-dir",
            outputs=["outdir"],
            run="mkdir -p outdir && echo 'file' > outdir/file.txt",
        )

        # Beta B3: Directory outputs are now rejected at validation time
        S = build("dir-output-test", 10, node, site=str(site))

        # Build should halt with directory rejection (Beta Gate B3)
        assert S["status"] == "halted", f"Expected halted, got {S['status']}"
        assert "produced directory output" in S["value"], \
            f"Expected directory rejection error, got: {S['value']}"

        # Directory was created in staging but not promoted
        # (validation failed before promotion)

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_symlink_to_directory_returns_absent():
    """file_sig() should return ABSENT for symlinks to directories."""
    from husks.build.site import file_sig
    from husks.core import ABSENT
    import os

    tmpdir = tempfile.mkdtemp(prefix="symlink-dir-")
    try:
        # Create a directory
        target_dir = Path(tmpdir) / "target"
        target_dir.mkdir()

        # Create symlink to the directory
        link = Path(tmpdir) / "link"
        os.symlink(str(target_dir), str(link))

        # Symlink to directory should return ABSENT
        result = file_sig(str(link))
        assert result == ABSENT, \
            f"Expected ABSENT for symlink to directory, got {result}"

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)
