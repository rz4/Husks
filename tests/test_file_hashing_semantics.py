"""
test_file_hashing_semantics.py -- Beta Gate C4: File hashing normalization.

Tests that absent files, regular files, and unsupported paths have
consistent signature representation across seal, manifest, status,
and verification.

Tests cover:
- Regular files produce consistent hashes
- Missing files produce consistent ABSENT representation
- Directories produce consistent ABSENT representation
- Symlinks produce consistent ABSENT representation
- Consistency across core.py, site.py, and manifest.py
"""

import tempfile
import shutil
import os
from pathlib import Path


def test_regular_file_hash_consistent():
    """Regular file hashing is consistent across modules."""
    from husks.core import content_hash_or_absent, ABSENT
    from husks.build.site import file_sig
    from husks.manifest import file_hash
    import hashlib

    tmpdir = tempfile.mkdtemp(prefix="c4-regular-")
    try:
        file_path = Path(tmpdir) / "test.txt"
        file_path.write_text("hello world\n")

        # All three functions should produce the same hash
        core_result = content_hash_or_absent(str(file_path))
        site_result = file_sig(str(file_path))
        manifest_result = file_hash(str(file_path))

        # Core and site return bytes
        assert core_result == site_result, "core and site should return same bytes"
        assert core_result != ABSENT, "regular file should not be ABSENT"

        # Manifest returns hex string
        expected_hex = hashlib.sha256(b"hello world\n").hexdigest()
        assert manifest_result == expected_hex, "manifest should return correct hex"

        # Decoded bytes should match manifest result
        assert core_result.decode() == manifest_result, \
            "decoded bytes should match manifest hex"

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_missing_file_absent_consistent():
    """Missing files produce consistent ABSENT across modules."""
    from husks.core import content_hash_or_absent, ABSENT
    from husks.build.site import file_sig
    from husks.manifest import file_hash

    tmpdir = tempfile.mkdtemp(prefix="c4-missing-")
    try:
        missing_path = Path(tmpdir) / "nonexistent.txt"

        # Core and site should return ABSENT bytes
        core_result = content_hash_or_absent(str(missing_path))
        site_result = file_sig(str(missing_path))

        assert core_result == ABSENT, "core should return ABSENT for missing file"
        assert site_result == ABSENT, "site should return ABSENT for missing file"
        assert core_result == site_result, "core and site should be consistent"

        # Manifest should return None
        manifest_result = file_hash(str(missing_path))
        assert manifest_result is None, "manifest should return None for missing file"

        # When manifest converts to string, it should become "absent"
        manifest_str = manifest_result if manifest_result is not None else "absent"
        assert manifest_str == "absent", "manifest None should convert to 'absent'"
        assert manifest_str == ABSENT.decode(), "manifest string should match decoded ABSENT"

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_directory_absent_consistent():
    """Directories produce consistent ABSENT across modules."""
    from husks.core import content_hash_or_absent, ABSENT
    from husks.build.site import file_sig
    from husks.manifest import file_hash

    tmpdir = tempfile.mkdtemp(prefix="c4-directory-")
    try:
        dir_path = Path(tmpdir) / "mydir"
        dir_path.mkdir()

        # Core and site should return ABSENT for directories
        core_result = content_hash_or_absent(str(dir_path))
        site_result = file_sig(str(dir_path))

        assert core_result == ABSENT, "core should return ABSENT for directory"
        assert site_result == ABSENT, "site should return ABSENT for directory"

        # Manifest should return None for directories
        manifest_result = file_hash(str(dir_path))
        assert manifest_result is None, "manifest should return None for directory"

        # Conversion to string should match
        manifest_str = manifest_result if manifest_result is not None else "absent"
        assert manifest_str == ABSENT.decode()

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_symlink_to_directory_absent_consistent():
    """Symlinks to directories produce consistent ABSENT."""
    from husks.core import content_hash_or_absent, ABSENT
    from husks.build.site import file_sig
    from husks.manifest import file_hash

    tmpdir = tempfile.mkdtemp(prefix="c4-symlink-dir-")
    try:
        # Create directory and symlink to it
        target_dir = Path(tmpdir) / "target"
        target_dir.mkdir()

        link = Path(tmpdir) / "link"
        os.symlink(str(target_dir), str(link))

        # All should treat symlink-to-directory as ABSENT
        core_result = content_hash_or_absent(str(link))
        site_result = file_sig(str(link))
        manifest_result = file_hash(str(link))

        assert core_result == ABSENT, "core should return ABSENT for symlink to directory"
        assert site_result == ABSENT, "site should return ABSENT for symlink to directory"
        assert manifest_result is None, "manifest should return None for symlink to directory"

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_symlink_to_file_hashed_consistently():
    """Symlinks to files are hashed consistently."""
    from husks.core import content_hash_or_absent, ABSENT
    from husks.build.site import file_sig
    from husks.manifest import file_hash
    import hashlib

    tmpdir = tempfile.mkdtemp(prefix="c4-symlink-file-")
    try:
        # Create file and symlink to it
        target_file = Path(tmpdir) / "target.txt"
        target_file.write_text("content\n")

        link = Path(tmpdir) / "link.txt"
        os.symlink(str(target_file), str(link))

        # All should hash the symlink target
        core_result = content_hash_or_absent(str(link))
        site_result = file_sig(str(link))
        manifest_result = file_hash(str(link))

        expected_hash = hashlib.sha256(b"content\n").hexdigest()

        assert core_result != ABSENT, "symlink to file should be hashed"
        assert site_result != ABSENT, "symlink to file should be hashed"
        assert core_result == site_result, "core and site should agree"
        assert manifest_result == expected_hash, "manifest should return correct hash"
        assert core_result.decode() == expected_hash

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_seal_uses_absent_for_missing_input():
    """Seals correctly encode ABSENT for missing inputs."""
    from husks.build import build, rule, action
    from husks.manifest import read_seal
    from conftest import make_site

    tmpdir = tempfile.mkdtemp(prefix="c4-seal-absent-")
    try:
        site = make_site(tmpdir)

        def write_output(S):
            from husks.build.site import write_path
            Path(write_path(S, "out.txt")).write_text("output\n")

        # Declare an input that doesn't exist
        node = rule(
            "test",
            inputs=["missing.txt"],
            outputs=["out.txt"],
            recipe=action(write_output),
        )

        S = build("test-build", 10, node, site=site)
        assert S["status"] == "committed"

        # Read seal and check input signature
        seal = read_seal(site, "test")
        assert seal is not None
        assert "inputs" in seal
        assert "missing.txt" in seal["inputs"]
        # Beta C4: Missing input should be encoded as "absent" string
        assert seal["inputs"]["missing.txt"] == "absent"

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_manifest_state_uses_absent_for_missing():
    """Manifest state computation uses 'absent' for missing files."""
    from husks.manifest import compute_rule_state, read_seal
    from husks.build import build, rule, action

    tmpdir = tempfile.mkdtemp(prefix="c4-manifest-absent-")
    try:
        # Create site without make_site to avoid auto-created input.txt
        site = Path(tmpdir) / "site"
        site.mkdir()

        def write_output(S):
            from husks.build.site import write_path
            Path(write_path(S, "out.txt")).write_text("output\n")

        # Use a missing input file
        node = rule(
            "test",
            inputs=["missing_input.txt"],
            outputs=["out.txt"],
            recipe=action(write_output),
        )

        S = build("test-build", 10, node, site=str(site))
        assert S["status"] == "committed"

        # Verify seal has "absent" for missing input
        seal = read_seal(str(site), "test")
        assert seal["inputs"]["missing_input.txt"] == "absent"

        # Compute state with missing input (should be fresh since seal also has absent)
        rule_dict = {"name": "test", "inputs": ["missing_input.txt"], "outputs": ["out.txt"]}
        state, reason = compute_rule_state(str(site), rule_dict, seal)

        # Should be fresh because current (absent) matches sealed (absent)
        assert state == "fresh", f"Expected fresh but got {state}: {reason}"

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_verification_handles_absent_consistently():
    """Root recomputation handles ABSENT files consistently."""
    from husks.build import build, rule, action
    from husks.core import recompute_root
    from conftest import make_site

    tmpdir = tempfile.mkdtemp(prefix="c4-verify-absent-")
    try:
        site = make_site(tmpdir)

        def write_output(S):
            from husks.build.site import write_path
            Path(write_path(S, "out.txt")).write_text("data\n")

        # Rule with missing input
        node = rule(
            "test",
            inputs=["missing.txt"],
            outputs=["out.txt"],
            recipe=action(write_output),
        )

        S = build("demo", 10, node, site=site)
        assert S["status"] == "committed"

        original_root = S["build-root"]
        husk_path = Path(site) / "demo.husk"
        husk_bytes = husk_path.read_bytes()

        # Recompute should match original
        recomputed = recompute_root(husk_bytes, site)
        assert recomputed == original_root, \
            "recomputed root should match original with ABSENT input"

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)
