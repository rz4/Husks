"""Test sandbox() function path escaping (P24).

Tests for:
- Symlink races (TOCTOU)
- Parent directory traversal (..)
- Nested readonly-root overlaps
- Write vs read permission boundaries
"""

import tempfile
import shutil
import os
from pathlib import Path


def test_sandbox_rejects_parent_traversal():
    """sandbox() must reject .. paths that escape site root."""
    from husks.oracle.tools import sandbox, set_site_root

    tmpdir = tempfile.mkdtemp(prefix="sandbox-parent-")
    try:
        site = Path(tmpdir) / "site"
        site.mkdir()

        secret = Path(tmpdir) / "secret.txt"
        secret.write_text("SECRET\n")

        set_site_root(str(site))
        try:
            # Try to escape using ..
            import pytest
            with pytest.raises(ValueError, match="outside the site root"):
                sandbox("../secret.txt", write=False)

            with pytest.raises(ValueError, match="outside the site root"):
                sandbox("../secret.txt", write=True)

            # Try nested ..
            (site / "subdir").mkdir()
            with pytest.raises(ValueError, match="outside the site root"):
                sandbox("subdir/../../secret.txt", write=False)

        finally:
            set_site_root(None)

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_sandbox_rejects_absolute_path_escape():
    """sandbox() must reject absolute paths outside site root."""
    from husks.oracle.tools import sandbox, set_site_root

    tmpdir = tempfile.mkdtemp(prefix="sandbox-absolute-")
    try:
        site = Path(tmpdir) / "site"
        site.mkdir()

        secret = Path(tmpdir) / "secret"
        secret.mkdir()
        (secret / "data.txt").write_text("SECRET\n")

        set_site_root(str(site))
        try:
            import pytest
            # Absolute path outside site root
            secret_file = str(secret / "data.txt")
            with pytest.raises(ValueError, match="outside the site root"):
                sandbox(secret_file, write=False)

            with pytest.raises(ValueError, match="outside the site root"):
                sandbox(secret_file, write=True)

        finally:
            set_site_root(None)

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_sandbox_symlink_within_site():
    """sandbox() should allow symlinks that stay within site root."""
    from husks.oracle.tools import sandbox, set_site_root

    tmpdir = tempfile.mkdtemp(prefix="sandbox-internal-link-")
    try:
        site = Path(tmpdir) / "site"
        site.mkdir()

        # Create legitimate content
        data = site / "data"
        data.mkdir()
        (data / "file.txt").write_text("content\n")

        # Create internal symlink
        link = site / "link"
        os.symlink(str(data), str(link))

        set_site_root(str(site))
        try:
            # Should allow reading through internal symlink
            p = sandbox("link/file.txt", write=False)
            assert p.exists()
            assert p.read_text() == "content\n"

            # Should allow writing through internal symlink
            p = sandbox("link/new.txt", write=True)
            # Verify it resolves to a path under site
            assert str(p).startswith(str(site.resolve()))

        finally:
            set_site_root(None)

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_sandbox_symlink_escape_read():
    """sandbox() must reject symlinks that escape site root (read)."""
    from husks.oracle.tools import sandbox, set_site_root

    tmpdir = tempfile.mkdtemp(prefix="sandbox-escape-link-")
    try:
        site = Path(tmpdir) / "site"
        site.mkdir()

        secret = Path(tmpdir) / "secret"
        secret.mkdir()
        (secret / "data.txt").write_text("SECRET\n")

        # Malicious symlink pointing outside
        escape_link = site / "escape"
        os.symlink(str(secret), str(escape_link))

        set_site_root(str(site))
        try:
            import pytest
            # Should reject reading through escaping symlink
            with pytest.raises(ValueError, match="outside the site root"):
                sandbox("escape/data.txt", write=False)

        finally:
            set_site_root(None)

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_sandbox_symlink_escape_write():
    """sandbox() must reject symlinks that escape site root (write)."""
    from husks.oracle.tools import sandbox, set_site_root

    tmpdir = tempfile.mkdtemp(prefix="sandbox-escape-write-")
    try:
        site = Path(tmpdir) / "site"
        site.mkdir()

        secret = Path(tmpdir) / "secret"
        secret.mkdir()

        # Malicious symlink pointing outside
        escape_link = site / "escape"
        os.symlink(str(secret), str(escape_link))

        set_site_root(str(site))
        try:
            import pytest
            # P29: Write must never follow symlinks outside site root
            with pytest.raises(ValueError, match="write denied"):
                sandbox("escape/malicious.txt", write=True)

        finally:
            set_site_root(None)

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_sandbox_readonly_root_read_allowed():
    """sandbox() should allow reads through symlinks into readonly roots."""
    from husks.oracle.tools import sandbox, set_site_root

    tmpdir = tempfile.mkdtemp(prefix="sandbox-readonly-")
    try:
        site = Path(tmpdir) / "site"
        site.mkdir()

        readonly = Path(tmpdir) / "readonly"
        readonly.mkdir()
        (readonly / "lib.txt").write_text("library code\n")

        # Symlink from site to readonly
        link = site / "imports"
        os.symlink(str(readonly), str(link))

        set_site_root(str(site), readonly=[str(readonly)])
        try:
            # Should allow reading through readonly symlink
            p = sandbox("imports/lib.txt", write=False)
            assert p.exists()
            assert p.read_text() == "library code\n"

        finally:
            set_site_root(None)

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_sandbox_readonly_root_write_denied():
    """P29: sandbox() must reject writes through symlinks into readonly roots."""
    from husks.oracle.tools import sandbox, set_site_root

    tmpdir = tempfile.mkdtemp(prefix="sandbox-readonly-write-")
    try:
        site = Path(tmpdir) / "site"
        site.mkdir()

        readonly = Path(tmpdir) / "readonly"
        readonly.mkdir()
        (readonly / "lib.txt").write_text("library code\n")

        # Symlink from site to readonly
        link = site / "imports"
        os.symlink(str(readonly), str(link))

        set_site_root(str(site), readonly=[str(readonly)])
        try:
            import pytest
            # P29: Must reject writing into readonly root
            with pytest.raises(ValueError, match="write denied"):
                sandbox("imports/malicious.txt", write=True)

        finally:
            set_site_root(None)

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_sandbox_nested_readonly_overlap():
    """sandbox() should handle nested readonly roots correctly."""
    from husks.oracle.tools import sandbox, set_site_root

    tmpdir = tempfile.mkdtemp(prefix="sandbox-nested-")
    try:
        site = Path(tmpdir) / "site"
        site.mkdir()

        # Create nested readonly structure
        outer = Path(tmpdir) / "outer"
        outer.mkdir()
        inner = outer / "inner"
        inner.mkdir()
        (inner / "file.txt").write_text("inner content\n")

        # Link to inner directory
        link = site / "link"
        os.symlink(str(inner), str(link))

        # Register only inner as readonly
        set_site_root(str(site), readonly=[str(inner)])
        try:
            # Should allow reading inner content
            p = sandbox("link/file.txt", write=False)
            assert p.exists()

            import pytest
            # Should reject writes
            with pytest.raises(ValueError, match="write denied"):
                sandbox("link/new.txt", write=True)

        finally:
            set_site_root(None)

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_sandbox_race_condition_mitigation():
    """sandbox() resolves symlinks immediately to mitigate TOCTOU races.

    While we can't fully prevent race conditions (attacker could swap
    symlink between sandbox() check and actual file operation), we ensure
    sandbox() validates the resolved path, not just the symlink name.
    """
    from husks.oracle.tools import sandbox, set_site_root

    tmpdir = tempfile.mkdtemp(prefix="sandbox-race-")
    try:
        site = Path(tmpdir) / "site"
        site.mkdir()

        good = site / "good"
        good.mkdir()
        (good / "data.txt").write_text("good\n")

        evil = Path(tmpdir) / "evil"
        evil.mkdir()

        # Create symlink to good directory
        link = site / "link"
        os.symlink(str(good), str(link))

        set_site_root(str(site))
        try:
            # This should pass - link points to good directory inside site
            p1 = sandbox("link/data.txt", write=False)
            assert p1.exists()

            # Now swap the symlink to point outside (simulating race)
            os.unlink(str(link))
            os.symlink(str(evil), str(link))

            import pytest
            # sandbox() should reject the swapped symlink
            with pytest.raises(ValueError, match="outside the site root"):
                sandbox("link/data.txt", write=False)

        finally:
            set_site_root(None)

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_sandbox_without_site_root_allows_all():
    """sandbox() with no site root allows all paths (testing/debugging mode)."""
    from husks.oracle.tools import sandbox, set_site_root

    tmpdir = tempfile.mkdtemp(prefix="sandbox-no-root-")
    try:
        # Ensure no sandbox is active
        set_site_root(None)

        # Create file outside any "site"
        external = Path(tmpdir) / "external.txt"
        external.write_text("external\n")

        # Without sandbox, all paths should be allowed
        p = sandbox(str(external), write=False)
        assert p.exists()

        # Writes should also be allowed (for testing)
        p = sandbox(str(external), write=True)
        # Just verify it returns a path
        assert isinstance(p, Path)

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)
