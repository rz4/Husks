"""Test that BuildTransaction protects imported (readonly) directories.

The staging mirror replaces symlinks that target readonly-dirs with
read-only copies so shell actions cannot write through to external paths.
"""

import stat
from pathlib import Path

from husks.engine import BuildTransaction


def test_readonly_dir_is_copied_not_symlinked(tmp_path):
    """Imported dir in stage should be a read-only copy, not a symlink."""
    # Set up an external directory that the site imports via symlink
    external = tmp_path / "external_data"
    external.mkdir()
    (external / "input.txt").write_text("original content")

    # Set up a site with a symlink to the external dir
    site = tmp_path / "site"
    site.mkdir()
    (site / "imported").symlink_to(external)
    (site / "local.txt").write_text("local file")

    S = {
        "site": str(site),
        "readonly-dirs": [str(external)],
    }
    tx = BuildTransaction(S, outputs=[])

    with tx:
        stage = Path(tx.stage_dir)
        imported_in_stage = stage / "imported"

        # Should be a real directory, not a symlink
        assert imported_in_stage.is_dir()
        assert not imported_in_stage.is_symlink()

        # Contents should be present
        assert (imported_in_stage / "input.txt").read_text() == "original content"

        # Directory and file should be read-only
        dir_mode = stat.S_IMODE(imported_in_stage.stat().st_mode)
        assert dir_mode & stat.S_IWUSR == 0, f"dir should be read-only, got {oct(dir_mode)}"

        file_mode = stat.S_IMODE((imported_in_stage / "input.txt").stat().st_mode)
        assert file_mode & stat.S_IWUSR == 0, f"file should be read-only, got {oct(file_mode)}"

        # Non-imported items should still be symlinks
        local_in_stage = stage / "local.txt"
        assert local_in_stage.is_symlink()


def test_write_to_imported_dir_does_not_affect_external(tmp_path):
    """Shell action writing to imported dir in stage must not mutate external."""
    external = tmp_path / "external_data"
    external.mkdir()
    (external / "input.txt").write_text("original content")

    site = tmp_path / "site"
    site.mkdir()
    (site / "imported").symlink_to(external)

    S = {
        "site": str(site),
        "readonly-dirs": [str(external)],
    }
    tx = BuildTransaction(S, outputs=[])

    with tx:
        stage = Path(tx.stage_dir)
        target_file = stage / "imported" / "input.txt"

        # Attempting to write should fail (read-only)
        try:
            target_file.write_text("malicious overwrite")
        except PermissionError:
            pass  # Expected: file is read-only

    # External directory must be unchanged regardless
    assert (external / "input.txt").read_text() == "original content"


def test_readonly_file_symlink_is_copied(tmp_path):
    """A symlink to a file inside a readonly dir is also copied read-only."""
    external = tmp_path / "external_data"
    external.mkdir()
    (external / "data.csv").write_text("col1,col2\n1,2\n")

    site = tmp_path / "site"
    site.mkdir()
    # Symlink to a specific file inside the external dir
    (site / "data.csv").symlink_to(external / "data.csv")

    S = {
        "site": str(site),
        "readonly-dirs": [str(external)],
    }
    tx = BuildTransaction(S, outputs=[])

    with tx:
        stage = Path(tx.stage_dir)
        staged_file = stage / "data.csv"

        # Should be a real file, not a symlink
        assert staged_file.is_file()
        assert not staged_file.is_symlink()
        assert staged_file.read_text() == "col1,col2\n1,2\n"

        # Should be read-only
        mode = stat.S_IMODE(staged_file.stat().st_mode)
        assert mode & stat.S_IWUSR == 0, f"file should be read-only, got {oct(mode)}"
