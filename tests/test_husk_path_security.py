"""Test that recompute_root() rejects malicious paths in .husk files."""

import tempfile
import shutil
from pathlib import Path
import pytest


def test_recompute_root_rejects_absolute_path_in_inputs():
    """recompute_root must reject .husk files with absolute input paths.

    Security: A malicious .husk could specify inputs=["/etc/passwd"] to
    cause verification to read arbitrary files. This must be rejected.
    """
    from husks.core import encode, atom, recompute_root

    tmpdir = tempfile.mkdtemp(prefix="husk-abs-input-")
    try:
        site = Path(tmpdir) / "site"
        site.mkdir()

        # Craft a malicious .husk with absolute path in inputs
        malicious_husk = [
            b"husk",
            b"2",
            [
                b"build",
                atom("evil"),
                atom("10"),
                [
                    b"rule",
                    atom("test"),
                    [b"action", atom("noop")],
                    [atom("/etc/passwd")],  # ABSOLUTE path in inputs!
                    [],  # no outputs
                ]
            ]
        ]

        husk_bytes = encode(malicious_husk)

        # Attempting to verify should raise ValueError
        with pytest.raises(ValueError, match="absolute path in .husk"):
            recompute_root(husk_bytes, str(site))

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_recompute_root_rejects_traversal_path_in_outputs():
    """recompute_root must reject .husk files with traversal output paths.

    Security: A malicious .husk could specify outputs=["../../secret"] to
    cause verification to read outside the site directory.
    """
    from husks.core import encode, atom, recompute_root

    tmpdir = tempfile.mkdtemp(prefix="husk-traversal-output-")
    try:
        site = Path(tmpdir) / "site"
        site.mkdir()

        # Craft a malicious .husk with traversal path in outputs
        # Structure: (husk version (build name fuel (rule name recipe (inputs) (outputs))))
        malicious_husk = [
            b"husk",
            b"2",
            [
                b"build",
                atom("evil"),
                atom("10"),
                [
                    b"rule",
                    atom("test"),
                    [b"action", atom("noop")],
                    [],  # no inputs
                    [atom("../secret.txt")],  # TRAVERSAL in outputs!
                ]
            ]
        ]

        husk_bytes = encode(malicious_husk)

        # Should reject traversal path
        with pytest.raises(ValueError, match="path traversal in .husk"):
            recompute_root(husk_bytes, str(site))

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_recompute_root_accepts_valid_relative_paths():
    """recompute_root should accept normal relative paths."""
    from husks.build import build, rule
    from husks.core import recompute_root

    tmpdir = tempfile.mkdtemp(prefix="husk-valid-paths-")
    try:
        site = Path(tmpdir) / "site"
        site.mkdir()

        # Create simple build with flat paths (no subdirectories)
        (site / "input.txt").write_text("data\n")
        node = rule(
            "test",
            inputs=["input.txt"],
            outputs=["output.txt"],
            run="cp input.txt output.txt",
        )
        S = build("test", 10, node, site=str(site))
        assert S["status"] == "committed"

        # Verify should succeed with valid relative paths
        husk_bytes = (site / "test.husk").read_bytes()
        root = recompute_root(husk_bytes, str(site))

        # Should match the build-root
        assert root == S["build-root"]

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_validate_husk_path_rejects_various_attacks():
    """Test _validate_husk_path helper rejects all attack patterns."""
    from husks.core import _validate_husk_path

    # Valid paths should pass
    _validate_husk_path("input.txt")
    _validate_husk_path("subdir/input.txt")
    _validate_husk_path("a/b/c/file.txt")

    # Absolute paths should fail
    with pytest.raises(ValueError, match="absolute path"):
        _validate_husk_path("/etc/passwd")

    with pytest.raises(ValueError, match="absolute path"):
        _validate_husk_path("/tmp/foo")

    # Traversal paths should fail
    with pytest.raises(ValueError, match="path traversal"):
        _validate_husk_path("../secret")

    with pytest.raises(ValueError, match="path traversal"):
        _validate_husk_path("foo/../../bar")

    with pytest.raises(ValueError, match="path traversal"):
        _validate_husk_path("../../etc/passwd")

    # Empty path should fail
    with pytest.raises(ValueError, match="empty path"):
        _validate_husk_path("")


def test_recompute_root_with_windows_absolute_path():
    """Test that Windows-style absolute paths are also rejected."""
    from husks.core import _validate_husk_path
    import os

    # Only test on actual Windows systems
    if os.name == 'nt':
        with pytest.raises(ValueError, match="absolute path"):
            _validate_husk_path("C:\\Windows\\System32\\config")

        with pytest.raises(ValueError, match="absolute path"):
            _validate_husk_path("C:/Windows/System32/config")
    else:
        # On Unix, Windows paths are not considered absolute, so skip
        pytest.skip("Windows path test only runs on Windows")
