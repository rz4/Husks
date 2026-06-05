"""Tests for fresh_store, burn/fuel, Stop, resolve_site_inputs, setup_links."""

import os
from pathlib import Path

import pytest

from seal import (
    fresh_store, burn, Stop,
    resolve_site_inputs, setup_links,
)


# ── fresh_store ──────────────────────────────────────────────────

class TestFreshStore:
    def test_creates_dir(self, tmp_path):
        site = str(tmp_path / "newsite")
        S = fresh_store(site, fuel=5)
        assert Path(site).is_dir()

    def test_expected_keys(self, tmp_store):
        for key in ("site", "fuel", "status", "value", "trace",
                     "oracle-backend", "oracle-backend-name",
                     "readonly-dirs", "run-id", "usage"):
            assert key in tmp_store

    def test_fuel_set(self, tmp_path):
        S = fresh_store(str(tmp_path / "s"), fuel=42)
        assert S["fuel"] == 42

    def test_status_running(self, tmp_store):
        assert tmp_store["status"] == "running"

    def test_run_id_is_uuid(self, tmp_store):
        import uuid
        uuid.UUID(tmp_store["run-id"])  # raises if invalid

    def test_oracle_backend_default_none(self, tmp_store):
        assert tmp_store["oracle-backend"] is None

    def test_readonly_dirs_default_empty(self, tmp_store):
        assert tmp_store["readonly-dirs"] == []

    def test_usage_structure(self, tmp_store):
        u = tmp_store["usage"]
        assert u["total_cost_usd"] == 0.0
        assert u["total_input_tokens"] == 0
        assert u["total_output_tokens"] == 0
        assert u["by_rule"] == {}


# ── Burn / Fuel ──────────────────────────────────────────────────

class TestBurn:
    def test_decrements_fuel(self, tmp_store):
        initial = tmp_store["fuel"]
        burn(tmp_store, "step1")
        assert tmp_store["fuel"] == initial - 1

    def test_appends_trace(self, tmp_store):
        burn(tmp_store, "step1")
        assert len(tmp_store["trace"]) == 1
        assert tmp_store["trace"][0]["event"] == "burn"
        assert tmp_store["trace"][0]["label"] == "step1"

    def test_raises_stop_on_exhaustion(self, tmp_path):
        S = fresh_store(str(tmp_path / "s"), fuel=1)
        burn(S, "first")  # fuel -> 0
        with pytest.raises(Stop) as exc_info:
            burn(S, "second")  # fuel -> -1
        assert exc_info.value.kind == "halt"
        assert "fuel exhausted" in exc_info.value.value

    def test_sets_halted_status(self, tmp_path):
        S = fresh_store(str(tmp_path / "s"), fuel=0)
        with pytest.raises(Stop):
            burn(S, "boom")
        assert S["status"] == "halted"

    def test_multiple_burns(self, tmp_store):
        for i in range(5):
            burn(tmp_store, f"step{i}")
        assert tmp_store["fuel"] == 5  # started at 10


# ── Stop exception ───────────────────────────────────────────────

class TestStop:
    def test_kind_and_value(self):
        s = Stop("halt", "reason")
        assert s.kind == "halt"
        assert s.value == "reason"

    def test_is_exception(self):
        assert issubclass(Stop, Exception)

    def test_commit_kind(self):
        s = Stop("commit", "ok")
        assert s.kind == "commit"
        assert s.value == "ok"


# ── resolve_site_inputs ──────────────────────────────────────────

class TestResolveSiteInputs:
    def test_none_returns_empty(self):
        assert resolve_site_inputs(None) == {}

    def test_dict_passthrough(self):
        d = {"a.txt": "/data/a.txt"}
        result = resolve_site_inputs(d)
        assert result == d
        assert result is not d  # copy

    def test_list_absolute(self):
        result = resolve_site_inputs(["/tmp/data.txt"])
        assert result == {"data.txt": "/tmp/data.txt"}

    def test_list_relative(self):
        result = resolve_site_inputs(["prompt.txt"])
        assert result == {"prompt.txt": "prompt.txt"}

    def test_list_mixed(self):
        result = resolve_site_inputs(["/abs/file.txt", "rel.txt"])
        assert result == {"file.txt": "/abs/file.txt", "rel.txt": "rel.txt"}

    def test_empty_list(self):
        assert resolve_site_inputs([]) == {}

    def test_empty_dict(self):
        assert resolve_site_inputs({}) == {}


# ── setup_links ──────────────────────────────────────────────────

class TestSetupLinks:
    def test_creates_symlinks(self, tmp_path):
        site = tmp_path / "site"
        site.mkdir()
        ext = tmp_path / "external"
        ext.mkdir()
        (ext / "data.txt").write_text("hello")

        readonly = setup_links(str(site), {"ext": str(ext)})
        link = site / "ext"
        assert link.is_symlink()
        assert link.resolve() == ext.resolve()
        assert len(readonly) == 1

    def test_rejects_dotfile(self, tmp_path):
        site = tmp_path / "site"
        site.mkdir()
        ext = tmp_path / "ext"
        ext.mkdir()
        with pytest.raises(ValueError, match="cannot start with '.'"):
            setup_links(str(site), {".hidden": str(ext)})

    def test_rejects_traversal(self, tmp_path):
        site = tmp_path / "site"
        site.mkdir()
        ext = tmp_path / "ext"
        ext.mkdir()
        # "../escape" hits dotfile check first (starts with '.'); use "sub/../x"
        with pytest.raises(ValueError, match="path traversal"):
            setup_links(str(site), {"sub/../x": str(ext)})

    def test_rejects_absolute_local(self, tmp_path):
        site = tmp_path / "site"
        site.mkdir()
        ext = tmp_path / "ext"
        ext.mkdir()
        with pytest.raises(ValueError, match="must be relative"):
            setup_links(str(site), {"/abs/path": str(ext)})

    def test_rejects_missing_external(self, tmp_path):
        site = tmp_path / "site"
        site.mkdir()
        with pytest.raises(ValueError, match="does not exist"):
            setup_links(str(site), {"link": str(tmp_path / "nonexistent")})

    def test_existing_correct_symlink_ok(self, tmp_path):
        """Existing symlink pointing to correct target is accepted."""
        site = tmp_path / "site"
        site.mkdir()
        ext = tmp_path / "ext"
        ext.mkdir()
        link = site / "mylink"
        os.symlink(str(ext), str(link))
        # Should not raise
        setup_links(str(site), {"mylink": str(ext)})

    def test_existing_wrong_symlink_rejected(self, tmp_path):
        site = tmp_path / "site"
        site.mkdir()
        ext1 = tmp_path / "ext1"
        ext1.mkdir()
        ext2 = tmp_path / "ext2"
        ext2.mkdir()
        link = site / "mylink"
        os.symlink(str(ext1), str(link))
        with pytest.raises(ValueError, match="wrong target"):
            setup_links(str(site), {"mylink": str(ext2)})

    def test_existing_file_collision(self, tmp_path):
        site = tmp_path / "site"
        site.mkdir()
        (site / "blocker").write_text("I'm in the way")
        ext = tmp_path / "ext"
        ext.mkdir()
        with pytest.raises(ValueError, match="already exists"):
            setup_links(str(site), {"blocker": str(ext)})

    def test_readonly_dir_for_file_target(self, tmp_path):
        """For file targets, readonly dir should be the parent directory."""
        site = tmp_path / "site"
        site.mkdir()
        ext_file = tmp_path / "data" / "file.txt"
        ext_file.parent.mkdir()
        ext_file.write_text("data")
        readonly = setup_links(str(site), {"linked_file": str(ext_file)})
        assert str(ext_file.parent.resolve()) in readonly[0]
