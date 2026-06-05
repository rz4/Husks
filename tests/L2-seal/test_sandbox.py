"""Tests for path sandboxing, escape detection, and staging."""

import os
from pathlib import Path

import pytest

from husks.seal import site_path, read_path, write_path


class TestSitePath:
    """site_path sandboxing."""

    def test_simple_resolve(self, tmp_store):
        p = site_path(tmp_store, "hello.txt")
        assert p.endswith("hello.txt")
        assert Path(tmp_store["site"]).resolve() in Path(p).parents

    def test_rejects_dotdot(self, tmp_store):
        with pytest.raises(ValueError, match="escapes site"):
            site_path(tmp_store, "../escape.txt")

    def test_rejects_absolute(self, tmp_store):
        with pytest.raises(ValueError, match="escapes site"):
            site_path(tmp_store, "/etc/passwd")

    def test_rejects_dotdot_nested(self, tmp_store):
        with pytest.raises(ValueError, match="escapes site"):
            site_path(tmp_store, "sub/../../escape.txt")

    def test_allows_readonly_dir(self, tmp_site, tmp_path):
        """Paths resolving into registered readonly-dirs are allowed for reads."""
        ext = tmp_path / "external"
        ext.mkdir()
        (ext / "data.txt").write_text("hello")
        link = Path(tmp_site) / "linked"
        os.symlink(str(ext), str(link))

        from husks.seal import fresh_store
        S = fresh_store(tmp_site, fuel=5, readonly_dirs=[str(ext)])
        # Should succeed - resolves into a readonly dir
        p = site_path(S, "linked/data.txt")
        assert Path(p).exists()

    def test_write_rejects_escape(self, tmp_store, tmp_path):
        """Write mode always rejects paths that escape site."""
        ext = tmp_path / "external"
        ext.mkdir()
        link = Path(tmp_store["site"]) / "linked"
        os.symlink(str(ext), str(link))
        tmp_store["readonly-dirs"] = [str(ext)]

        # read_path should work
        read_path(tmp_store, "linked")
        # write_path via site_path(write=True) - escape check depends on staging
        # Without staging, base=site, so symlink resolves outside -> rejected on write
        with pytest.raises(ValueError, match="escapes site"):
            write_path(tmp_store, "linked/file.txt")


class TestReadWritePath:
    """read_path and write_path convenience wrappers."""

    def test_read_path_delegates(self, tmp_store):
        assert read_path(tmp_store, "foo.txt") == site_path(tmp_store, "foo.txt")

    def test_write_path_delegates(self, tmp_store):
        assert write_path(tmp_store, "foo.txt") == site_path(tmp_store, "foo.txt", write=True)

    def test_staging_write_path(self, tmp_store, tmp_path):
        """Write path targets staging dir when stage is set."""
        stage = tmp_path / "stage"
        stage.mkdir()
        tmp_store["stage"] = str(stage)
        p = write_path(tmp_store, "output.txt")
        assert str(stage.resolve()) in p

    def test_staging_read_path_uses_site(self, tmp_store, tmp_path):
        """Read path still uses site dir even when stage is set."""
        stage = tmp_path / "stage"
        stage.mkdir()
        tmp_store["stage"] = str(stage)
        p = read_path(tmp_store, "input.txt")
        assert str(Path(tmp_store["site"]).resolve()) in p


class TestStagingSymlinkBreak:
    """Staging mode breaks symlinks for writes."""

    def test_breaks_parent_symlink_on_write(self, tmp_store, tmp_path):
        """When writing through a symlinked parent dir in staging, break the link."""
        stage = tmp_path / "stage"
        stage.mkdir()
        ext = tmp_path / "ext_dir"
        ext.mkdir()
        (ext / "file.txt").write_text("original")

        # Create symlink in stage dir
        link = stage / "subdir"
        os.symlink(str(ext), str(link))

        tmp_store["stage"] = str(stage)
        p = write_path(tmp_store, "subdir/file.txt")
        # After write_path, the symlink should be broken
        assert not link.is_symlink()
        assert link.is_dir()
