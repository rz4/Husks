"""
test_import_hardening.py -- Tests for Beta B4 import validation.

Beta Gate B4: Harden imports and symlink collisions.

Validates import local names at runtime. Rejects internal paths, path traversal,
collisions with outputs, and existing symlinks pointing to wrong targets.
"""

import tempfile
import shutil
import os
from pathlib import Path


def test_import_internal_path_rejected():
    """Import local names starting with '.' are rejected."""
    from husks.build.site import setup_links

    tmpdir = tempfile.mkdtemp(prefix="b4-internal-")
    try:
        site = Path(tmpdir) / "site"
        site.mkdir()

        external = Path(tmpdir) / "external"
        external.mkdir()
        (external / "data.txt").write_text("data\n")

        # Try to import with internal path name
        try:
            setup_links(str(site), {".hidden": str(external / "data.txt")})
            assert False, "Should have raised ValueError"
        except ValueError as e:
            assert "cannot start with '.'" in str(e)

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_import_path_traversal_rejected():
    """Import local names with path traversal are rejected."""
    from husks.build.site import setup_links

    tmpdir = tempfile.mkdtemp(prefix="b4-traversal-")
    try:
        site = Path(tmpdir) / "site"
        site.mkdir()

        external = Path(tmpdir) / "external"
        external.mkdir()
        (external / "data.txt").write_text("data\n")

        # Try to import with path traversal
        try:
            setup_links(str(site), {"../escape": str(external / "data.txt")})
            assert False, "Should have raised ValueError"
        except ValueError as e:
            # Caught by either "starts with '.'" or "path traversal" check
            assert ("cannot start with" in str(e)) or ("path traversal" in str(e))

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_import_absolute_path_rejected():
    """Import local names that are absolute paths are rejected."""
    from husks.build.site import setup_links

    tmpdir = tempfile.mkdtemp(prefix="b4-absolute-")
    try:
        site = Path(tmpdir) / "site"
        site.mkdir()

        external = Path(tmpdir) / "external"
        external.mkdir()
        (external / "data.txt").write_text("data\n")

        # Try to import with absolute path as local name
        try:
            setup_links(str(site), {"/absolute/path": str(external / "data.txt")})
            assert False, "Should have raised ValueError"
        except ValueError as e:
            assert "must be relative" in str(e)

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_import_collision_with_existing_file():
    """Cannot create import link if file already exists at that path."""
    from husks.build.site import setup_links

    tmpdir = tempfile.mkdtemp(prefix="b4-file-collision-")
    try:
        site = Path(tmpdir) / "site"
        site.mkdir()

        # Create existing file in site
        (site / "existing.txt").write_text("already here\n")

        external = Path(tmpdir) / "external"
        external.mkdir()
        (external / "data.txt").write_text("data\n")

        # Try to import where file exists
        try:
            setup_links(str(site), {"existing.txt": str(external / "data.txt")})
            assert False, "Should have raised ValueError"
        except ValueError as e:
            assert "file or directory already exists" in str(e)

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_import_symlink_wrong_target():
    """Existing symlink pointing to wrong target is rejected."""
    from husks.build.site import setup_links

    tmpdir = tempfile.mkdtemp(prefix="b4-wrong-target-")
    try:
        site = Path(tmpdir) / "site"
        site.mkdir()

        # Create two external files
        external1 = Path(tmpdir) / "external1"
        external1.mkdir()
        (external1 / "data.txt").write_text("data1\n")

        external2 = Path(tmpdir) / "external2"
        external2.mkdir()
        (external2 / "data.txt").write_text("data2\n")

        # Create symlink to external1
        link = site / "link.txt"
        os.symlink(str(external1 / "data.txt"), str(link))

        # Try to import external2 with same local name
        try:
            setup_links(str(site), {"link.txt": str(external2 / "data.txt")})
            assert False, "Should have raised ValueError"
        except ValueError as e:
            assert "points to wrong target" in str(e)

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_import_symlink_correct_target_ok():
    """Existing symlink pointing to correct target is allowed (idempotent)."""
    from husks.build.site import setup_links

    tmpdir = tempfile.mkdtemp(prefix="b4-correct-target-")
    try:
        site = Path(tmpdir) / "site"
        site.mkdir()

        external = Path(tmpdir) / "external"
        external.mkdir()
        (external / "data.txt").write_text("data\n")

        # Create symlink
        link = site / "link.txt"
        os.symlink(str(external / "data.txt"), str(link))

        # Setup same import again (idempotent)
        readonly = setup_links(str(site), {"link.txt": str(external / "data.txt")})

        # Should succeed and return readonly dir
        assert len(readonly) == 1
        # Compare resolved paths (macOS has /var -> /private/var symlink)
        assert Path(readonly[0]).resolve() == external.resolve()

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_import_nonexistent_external_path():
    """Import with nonexistent external path is rejected."""
    from husks.build.site import setup_links

    tmpdir = tempfile.mkdtemp(prefix="b4-nonexistent-")
    try:
        site = Path(tmpdir) / "site"
        site.mkdir()

        # Try to import nonexistent path
        try:
            setup_links(str(site), {"data": "/nonexistent/path"})
            assert False, "Should have raised ValueError"
        except ValueError as e:
            assert "does not exist" in str(e)

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_import_valid_nested_path():
    """Valid nested import paths are allowed."""
    from husks.build.site import setup_links

    tmpdir = tempfile.mkdtemp(prefix="b4-nested-")
    try:
        site = Path(tmpdir) / "site"
        site.mkdir()

        external = Path(tmpdir) / "external"
        external.mkdir()
        (external / "data.txt").write_text("data\n")

        # Import with nested path (no traversal)
        readonly = setup_links(str(site), {"imports/data.txt": str(external / "data.txt")})

        # Should succeed
        assert (site / "imports" / "data.txt").is_symlink()
        assert (site / "imports" / "data.txt").read_text() == "data\n"

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_import_directory():
    """Importing a directory creates symlink to directory."""
    from husks.build.site import setup_links

    tmpdir = tempfile.mkdtemp(prefix="b4-dir-import-")
    try:
        site = Path(tmpdir) / "site"
        site.mkdir()

        external_dir = Path(tmpdir) / "external_dir"
        external_dir.mkdir()
        (external_dir / "file1.txt").write_text("file1\n")
        (external_dir / "file2.txt").write_text("file2\n")

        # Import directory
        readonly = setup_links(str(site), {"extdir": str(external_dir)})

        # Should create symlink to directory
        assert (site / "extdir").is_symlink()
        assert (site / "extdir").is_dir()
        assert (site / "extdir" / "file1.txt").read_text() == "file1\n"

        # Readonly should point to the directory itself
        assert len(readonly) == 1
        # Compare resolved paths (macOS has /var -> /private/var symlink)
        assert Path(readonly[0]).resolve() == external_dir.resolve()

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_import_integration_with_build():
    """Imports work correctly in full build context."""
    from husks.build import build, rule, action
    from husks.build.site import site_path
    from husks.designs.ir import _setup_imports

    tmpdir = tempfile.mkdtemp(prefix="b4-integration-")
    try:
        site = Path(tmpdir) / "site"
        site.mkdir()

        external = Path(tmpdir) / "external"
        external.mkdir()
        (external / "input.txt").write_text("imported data\n")

        # Setup imports
        imports = {"ext": str(external)}
        readonly = _setup_imports(str(site), imports)

        def use_import(S):
            # Read from imported path
            input_path = site_path(S, "ext/input.txt")
            data = Path(input_path).read_text()

            # Write output
            output_path = site_path(S, "output.txt", write=True)
            Path(output_path).write_text(f"processed: {data}")

        node = rule(
            "process-import",
            inputs=["ext/input.txt"],
            outputs=["output.txt"],
            recipe=action(use_import),
        )

        S = build("import-test", 10, node, site=str(site), readonly_dirs=readonly)
        assert S["status"] == "committed"
        assert (site / "output.txt").read_text() == "processed: imported data\n"

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)
