"""test_sandbox.py -- Tool sandbox path confinement tests."""

import os
import pytest
from pathlib import Path
from oracle import sandbox, dispatch, read_file, write_file, list_dir, tree, schemas


# ── sandbox() ────────────────────────────────────────────────────

class TestSandbox:
    def test_relative_path_resolves_under_site(self, tmp_site):
        p = sandbox("foo.txt", site_root=tmp_site)
        assert p == (tmp_site / "foo.txt").resolve()

    def test_absolute_path_under_site_ok(self, tmp_site):
        p = sandbox(str(tmp_site / "foo.txt"), site_root=tmp_site)
        assert p == (tmp_site / "foo.txt").resolve()

    def test_escape_raises(self, tmp_site):
        with pytest.raises(ValueError, match="outside site root"):
            sandbox("../escape.txt", site_root=tmp_site)

    def test_absolute_escape_raises(self, tmp_site):
        with pytest.raises(ValueError, match="outside site root"):
            sandbox("/tmp/evil.txt", site_root=tmp_site)

    def test_no_site_root_returns_resolved(self, tmp_site):
        p = sandbox("foo.txt", site_root=None)
        assert p == Path("foo.txt").resolve()

    def test_write_rejects_readonly_root(self, tmp_site, tmp_path):
        ro = tmp_path / "imports"
        ro.mkdir()
        with pytest.raises(ValueError, match="write denied"):
            sandbox(str(ro / "x.txt"), write=True, site_root=tmp_site, readonly_roots={ro})

    def test_read_allows_readonly_root(self, tmp_site, tmp_path):
        ro = tmp_path / "imports"
        ro.mkdir()
        p = sandbox(str(ro / "x.txt"), write=False, site_root=tmp_site, readonly_roots={ro})
        assert p == (ro / "x.txt").resolve()


# ── read_file sandbox ────────────────────────────────────────────

class TestReadFileSandbox:
    def test_reads_file_under_site(self, tmp_site):
        (tmp_site / "hello.txt").write_text("world")
        out = read_file("hello.txt", site_root=tmp_site)
        assert out == "world"

    def test_rejects_escape(self, tmp_site):
        out = read_file("../escape.txt", site_root=tmp_site)
        assert "Error" in out and "outside" in out

    def test_nonexistent(self, tmp_site):
        out = read_file("nope.txt", site_root=tmp_site)
        assert "does not exist" in out

    def test_directory_error(self, tmp_site):
        (tmp_site / "subdir").mkdir()
        out = read_file("subdir", site_root=tmp_site)
        assert "directory" in out


# ── write_file sandbox ───────────────────────────────────────────

class TestWriteFileSandbox:
    def test_writes_file(self, tmp_site):
        out = write_file("out.txt", "data", site_root=tmp_site)
        assert out == "ok"
        assert (tmp_site / "out.txt").read_text() == "data"

    def test_creates_parents(self, tmp_site):
        out = write_file("a/b/c.txt", "deep", site_root=tmp_site)
        assert out == "ok"
        assert (tmp_site / "a" / "b" / "c.txt").read_text() == "deep"

    def test_rejects_escape(self, tmp_site):
        out = write_file("../evil.txt", "bad", site_root=tmp_site)
        assert "Error" in out

    def test_rejects_oversized(self, tmp_site):
        from oracle import MAX_WRITE_SIZE
        big = "x" * (MAX_WRITE_SIZE + 1)
        out = write_file("big.txt", big, site_root=tmp_site)
        assert "exceeds max" in out

    def test_write_rejects_readonly_target(self, tmp_site, tmp_path):
        ro = tmp_path / "imports"
        ro.mkdir()
        out = write_file(str(ro / "x.txt"), "bad", site_root=tmp_site, readonly_roots={ro})
        assert "Error" in out


# ── list_dir sandbox ─────────────────────────────────────────────

class TestListDirSandbox:
    def test_lists_contents(self, tmp_site):
        (tmp_site / "a.txt").write_text("a")
        (tmp_site / "b.txt").write_text("b")
        out = list_dir(".", site_root=tmp_site)
        assert "a.txt" in out and "b.txt" in out

    def test_nonexistent(self, tmp_site):
        out = list_dir("nope", site_root=tmp_site)
        assert "does not exist" in out


# ── tree sandbox ─────────────────────────────────────────────────

class TestTreeSandbox:
    def test_tree_shows_structure(self, tmp_site):
        (tmp_site / "sub").mkdir()
        (tmp_site / "sub" / "f.txt").write_text("x")
        out = tree(".", site_root=tmp_site)
        assert "sub/" in out
        assert "f.txt" in out

    def test_tree_skips_hidden(self, tmp_site):
        (tmp_site / ".hidden").write_text("x")
        out = tree(".", site_root=tmp_site)
        assert ".hidden" not in out


# ── dispatch ─────────────────────────────────────────────────────

class TestDispatch:
    def test_unknown_tool(self):
        assert "unknown tool" in dispatch("no-such-tool", {})

    def test_dispatch_with_context(self, tmp_site):
        (tmp_site / "x.txt").write_text("hello")
        out = dispatch("read-file", {"path": "x.txt"}, context={"site_root": tmp_site})
        assert out == "hello"

    def test_dispatch_catches_errors(self, tmp_site):
        out = dispatch("read-file", {"path": 123, "extra": "bad"},
                       context={"site_root": tmp_site})
        assert "Error" in out


# ── schemas ──────────────────────────────────────────────────────

class TestSchemas:
    def test_all_schemas(self):
        s = schemas()
        names = {d["function"]["name"] for d in s}
        assert names == {"read-file", "write-file", "list-dir", "tree"}

    def test_filtered_schemas(self):
        s = schemas(["read-file", "write-file"])
        assert len(s) == 2

    def test_unknown_name_skipped(self):
        s = schemas(["read-file", "bogus"])
        assert len(s) == 1
