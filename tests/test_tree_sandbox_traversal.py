"""Test that tree() validates each child and doesn't follow symlinks outside the site.

The tree tool must not expose content outside the sandbox by following symlinks
during recursive descent. Each child must be validated, not just the initial root.
"""

import tempfile
import shutil
import os
from pathlib import Path


def test_tree_does_not_follow_symlinks_outside_site():
    """tree() must skip symlinks that resolve outside the site root."""
    from husks.oracle import tools

    tmpdir = tempfile.mkdtemp(prefix="tree-symlink-test-")
    try:
        # Create site directory
        site = Path(tmpdir) / "site"
        site.mkdir()

        # Create legitimate content in site
        (site / "file.txt").write_text("site content\n")
        subdir = site / "subdir"
        subdir.mkdir()
        (subdir / "safe.txt").write_text("safe content\n")

        # Create a secret directory outside the site
        secret = Path(tmpdir) / "secret"
        secret.mkdir()
        (secret / "password.txt").write_text("SECRET_PASSWORD\n")
        (secret / "keys.txt").write_text("SECRET_KEYS\n")

        # Create a malicious symlink inside site that points outside to secret
        malicious_link = subdir / "escape"
        os.symlink(str(secret), str(malicious_link))

        # Activate sandbox with site root
        tools.set_site_root(str(site))
        try:
            # tree() should not expose content from secret directory
            result = tools.dispatch("tree", {"path": ".", "depth": 5})

            # Result should be a string, not an error
            assert isinstance(result, str), f"Expected string result, got {type(result)}"
            assert not result.startswith("Error:"), f"tree() failed: {result}"

            # Critical: secret content must NOT appear in tree output
            assert "SECRET_PASSWORD" not in result, \
                "tree() exposed content outside site via symlink!"
            assert "SECRET_KEYS" not in result, \
                "tree() exposed content outside site via symlink!"
            assert "password.txt" not in result, \
                "tree() exposed filenames outside site via symlink!"
            assert "keys.txt" not in result, \
                "tree() exposed filenames outside site via symlink!"

            # Safe content should still appear
            assert "file.txt" in result, "tree() should show safe site content"
            assert "safe.txt" in result, "tree() should show safe site content"

        finally:
            tools.set_site_root(None)

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_tree_allows_internal_symlinks():
    """tree() should follow symlinks that stay within the site root."""
    from husks.oracle import tools

    tmpdir = tempfile.mkdtemp(prefix="tree-internal-link-")
    try:
        site = Path(tmpdir) / "site"
        site.mkdir()

        # Create legitimate content
        data_dir = site / "data"
        data_dir.mkdir()
        (data_dir / "source.txt").write_text("source data\n")

        # Create internal symlink (within site)
        link_dir = site / "link"
        os.symlink(str(data_dir), str(link_dir))

        tools.set_site_root(str(site))
        try:
            result = tools.dispatch("tree", {"path": ".", "depth": 3})

            assert isinstance(result, str), f"Expected string result, got {type(result)}"
            assert not result.startswith("Error:"), f"tree() failed: {result}"

            # Should show the linked content (internal symlink is OK)
            assert "data" in result, "tree() should show data directory"
            assert "link" in result, "tree() should show symlink"
            assert "source.txt" in result, "tree() should follow internal symlink"

        finally:
            tools.set_site_root(None)

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_tree_with_readonly_roots():
    """tree() should allow reading symlinks into readonly roots but skip others."""
    from husks.oracle import tools

    tmpdir = tempfile.mkdtemp(prefix="tree-readonly-")
    try:
        site = Path(tmpdir) / "site"
        site.mkdir()

        # Create readonly directory (import target)
        readonly = Path(tmpdir) / "readonly"
        readonly.mkdir()
        (readonly / "lib.txt").write_text("library code\n")

        # Create secret directory (not in readonly list)
        secret = Path(tmpdir) / "secret"
        secret.mkdir()
        (secret / "secret.txt").write_text("SECRET\n")

        # Create symlinks in site
        readonly_link = site / "lib_link"
        os.symlink(str(readonly), str(readonly_link))

        secret_link = site / "secret_link"
        os.symlink(str(secret), str(secret_link))

        # Activate sandbox with readonly roots
        tools.set_site_root(str(site), readonly=[str(readonly)])
        try:
            result = tools.dispatch("tree", {"path": ".", "depth": 3})

            assert isinstance(result, str), f"Expected string result, got {type(result)}"
            assert not result.startswith("Error:"), f"tree() failed: {result}"

            # Should show readonly content (allowed)
            assert "lib_link" in result, "tree() should show readonly symlink"
            assert "lib.txt" in result, "tree() should follow readonly symlink"

            # Should NOT show secret content (not in readonly list)
            assert "SECRET" not in result, \
                "tree() exposed content outside allowed roots!"
            assert "secret.txt" not in result, \
                "tree() exposed secret filename!"

        finally:
            tools.set_site_root(None)

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_tree_skips_broken_symlinks():
    """tree() should gracefully skip broken symlinks."""
    from husks.oracle import tools

    tmpdir = tempfile.mkdtemp(prefix="tree-broken-link-")
    try:
        site = Path(tmpdir) / "site"
        site.mkdir()

        (site / "good.txt").write_text("good content\n")

        # Create a broken symlink
        broken_link = site / "broken"
        os.symlink("/nonexistent/path", str(broken_link))

        tools.set_site_root(str(site))
        try:
            # Should not crash on broken symlink
            result = tools.dispatch("tree", {"path": ".", "depth": 2})

            assert isinstance(result, str), f"Expected string result, got {type(result)}"
            assert not result.startswith("Error:"), f"tree() failed: {result}"

            # Good content should still appear
            assert "good.txt" in result, "tree() should show good content"

        finally:
            tools.set_site_root(None)

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_tree_without_sandbox_allows_all():
    """tree() without sandbox should work normally (no restrictions)."""
    from husks.oracle import tools

    tmpdir = tempfile.mkdtemp(prefix="tree-no-sandbox-")
    try:
        site = Path(tmpdir) / "site"
        site.mkdir()

        outside = Path(tmpdir) / "outside"
        outside.mkdir()
        (outside / "external.txt").write_text("external\n")

        # Create symlink to outside
        link = site / "link"
        os.symlink(str(outside), str(link))

        # No sandbox active - should follow all symlinks
        result = tools.dispatch("tree", {"path": str(site), "depth": 3})

        assert isinstance(result, str), f"Expected string result, got {type(result)}"
        assert not result.startswith("Error:"), f"tree() failed: {result}"

        # Without sandbox, external content is accessible
        assert "external.txt" in result, \
            "tree() without sandbox should follow all symlinks"

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)
