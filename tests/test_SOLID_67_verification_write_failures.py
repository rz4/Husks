"""Test that verification artifact write failures are fatal."""

import tempfile
import shutil
import os
from pathlib import Path


def test_build_fails_if_husk_cannot_be_written():
    """Build must halt if .husk file cannot be written.

    A build cannot claim committed status without a verifiable build-root
    and .husk file. If filesystem errors prevent writing these artifacts,
    the build must fail fatally.
    """
    from husks.build import build, rule

    tmpdir = tempfile.mkdtemp(prefix="husk-write-fail-")
    try:
        site = Path(tmpdir) / "site"
        site.mkdir()

        # Create a simple rule
        (site / "input.txt").write_text("data\n")
        node = rule(
            "test",
            inputs=["input.txt"],
            outputs=["output.txt"],
            run="cp input.txt output.txt",
        )

        # First build: should succeed
        S1 = build("test-build-1", 10, node, site=str(site))
        assert S1["status"] == "committed"
        assert S1["build-root"] is not None
        assert (site / "test-build-1.husk").exists()

        # Make site directory read-only to prevent .husk write
        # Note: Remove the old .husk first so the second build tries to create a NEW file
        # (On some systems, overwriting existing files works in read-only directories)
        (site / "test-build-1.husk").unlink()
        os.chmod(str(site), 0o555)

        try:
            # Second build with DIFFERENT name: should fail because we can't write .husk
            # Modify input to trigger rebuild
            # Need to temporarily make writable to modify input
            os.chmod(str(site), 0o755)
            (site / "input.txt").write_text("new data\n")
            os.chmod(str(site), 0o555)

            S2 = build("test-build-2", 10, node, site=str(site))

            # Critical assertion: build must halt, not commit
            assert S2["status"] == "halted", \
                f"Build should halt when verification artifacts cannot be written, got: {S2['status']}"

            assert "verification artifacts" in S2["value"], \
                f"Error message should mention verification artifacts: {S2['value']}"

            assert S2["build-root"] is None, \
                "build-root should be None when verification write fails"

        finally:
            # Restore permissions for cleanup
            os.chmod(str(site), 0o755)

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_build_fails_if_manifest_cannot_be_written():
    """Build must halt if manifest cannot be written.

    The build manifest is critical for status/explain commands. If we can't
    write it, the build should fail.

    P21: Updated to make .traces directory read-only instead of just the manifest
    file, to work correctly with atomic writes that use temp files.
    """
    from husks.build import build, rule

    tmpdir = tempfile.mkdtemp(prefix="manifest-write-fail-")
    try:
        site = Path(tmpdir) / "site"
        site.mkdir()

        # Create a simple rule
        (site / "input.txt").write_text("data\n")
        node = rule(
            "test",
            inputs=["input.txt"],
            outputs=["output.txt"],
            run="cp input.txt output.txt",
        )

        # Make .traces directory read-only to prevent any writes
        # This prevents both direct writes and atomic temp file creation
        traces_dir = site / ".traces"
        traces_dir.mkdir(exist_ok=True)
        os.chmod(str(traces_dir), 0o555)

        try:
            S = build("test", 10, node, site=str(site))

            # Build should halt because manifest write will fail
            assert S["status"] == "halted", \
                f"Build should halt when manifest cannot be written, got: {S['status']}"

            assert "verification artifacts" in S["value"] or "Permission denied" in S["value"], \
                f"Error message should indicate write failure: {S['value']}"

        finally:
            # Restore permissions for cleanup
            os.chmod(str(traces_dir), 0o755)

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_successful_build_has_all_verification_artifacts():
    """Verify that a successful committed build has all required artifacts."""
    from husks.build import build, rule

    tmpdir = tempfile.mkdtemp(prefix="verification-success-")
    try:
        site = Path(tmpdir) / "site"
        site.mkdir()

        (site / "input.txt").write_text("data\n")
        node = rule(
            "test",
            inputs=["input.txt"],
            outputs=["output.txt"],
            run="cp input.txt output.txt",
        )

        S = build("test", 10, node, site=str(site))

        # Build succeeded
        assert S["status"] == "committed"

        # All verification artifacts present
        assert S["build-root"] is not None, "build-root must be set"
        assert (site / "test.husk").exists(), ".husk file must exist"
        assert (site / ".traces" / "build.manifest.json").exists(), \
            "build manifest must exist"

        # Verify manifest content
        import json
        manifest = json.loads((site / ".traces" / "build.manifest.json").read_text())
        assert manifest["root"] == S["build-root"], \
            "manifest root must match build-root"
        assert manifest["name"] == "test"

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)
