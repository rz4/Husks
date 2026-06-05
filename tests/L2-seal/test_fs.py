"""Tests for atomic filesystem operations, file_sig, ensure_dir."""

from pathlib import Path

import pytest

from husks.seal import (
    ensure_dir, read_text, write_text, write_bytes_atomic,
    file_exists, file_sig,
)
from husks.kernel import ABSENT


class TestEnsureDir:
    def test_creates_nested(self, tmp_path):
        p = str(tmp_path / "a" / "b" / "c")
        result = ensure_dir(p)
        assert result == p
        assert Path(p).is_dir()

    def test_idempotent(self, tmp_path):
        p = str(tmp_path / "d")
        ensure_dir(p)
        ensure_dir(p)  # no error
        assert Path(p).is_dir()


class TestWriteText:
    def test_creates_parents(self, tmp_path):
        p = str(tmp_path / "nested" / "dir" / "file.txt")
        write_text(p, "hello")
        assert Path(p).read_text() == "hello"

    def test_returns_path(self, tmp_path):
        p = str(tmp_path / "file.txt")
        assert write_text(p, "x") == p

    def test_overwrites(self, tmp_path):
        p = str(tmp_path / "file.txt")
        write_text(p, "first")
        write_text(p, "second")
        assert Path(p).read_text() == "second"

    def test_unicode(self, tmp_path):
        p = str(tmp_path / "unicode.txt")
        write_text(p, "日本語テスト")
        assert read_text(p) == "日本語テスト"


class TestReadText:
    def test_round_trip(self, tmp_path):
        p = str(tmp_path / "rt.txt")
        write_text(p, "round-trip test")
        assert read_text(p) == "round-trip test"

    def test_missing_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            read_text(str(tmp_path / "missing.txt"))


class TestWriteBytesAtomic:
    def test_writes_bytes(self, tmp_path):
        p = str(tmp_path / "bin.dat")
        data = b"\x00\x01\x02\xff"
        write_bytes_atomic(p, data)
        assert Path(p).read_bytes() == data

    def test_creates_parents(self, tmp_path):
        p = str(tmp_path / "sub" / "bin.dat")
        write_bytes_atomic(p, b"data")
        assert Path(p).read_bytes() == b"data"

    def test_returns_path(self, tmp_path):
        p = str(tmp_path / "x.bin")
        assert write_bytes_atomic(p, b"x") == p


class TestFileExists:
    def test_exists(self, tmp_path):
        p = tmp_path / "yes.txt"
        p.write_text("hi")
        assert file_exists(str(p))

    def test_missing(self, tmp_path):
        assert not file_exists(str(tmp_path / "no.txt"))


class TestFileSig:
    def test_regular_file(self, tmp_path):
        p = tmp_path / "f.txt"
        p.write_text("content")
        sig = file_sig(str(p))
        assert isinstance(sig, bytes)
        assert sig != ABSENT
        assert len(sig) == 64  # hex sha256

    def test_missing_returns_absent(self, tmp_path):
        assert file_sig(str(tmp_path / "missing.txt")) == ABSENT

    def test_directory_returns_absent(self, tmp_path):
        d = tmp_path / "adir"
        d.mkdir()
        assert file_sig(str(d)) == ABSENT

    def test_deterministic(self, tmp_path):
        p = tmp_path / "det.txt"
        p.write_text("same")
        assert file_sig(str(p)) == file_sig(str(p))

    def test_different_content_different_sig(self, tmp_path):
        a = tmp_path / "a.txt"
        b = tmp_path / "b.txt"
        a.write_text("alpha")
        b.write_text("beta")
        assert file_sig(str(a)) != file_sig(str(b))
