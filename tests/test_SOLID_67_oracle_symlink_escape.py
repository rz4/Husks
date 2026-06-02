"""Test that oracle cannot escape sandbox via self-created symlinks (P28).

An oracle agent might try to create a symlink pointing outside the site
root, then read through it to exfiltrate data. The sandbox must reject
such attempts.
"""

import tempfile
import shutil
import os
from pathlib import Path


def test_oracle_cannot_read_self_created_escape_symlink():
    """Oracle creating an escape symlink and trying to read through it is blocked."""
    from husks.oracle import tools

    tmpdir = tempfile.mkdtemp(prefix="oracle-escape-")
    try:
        site = Path(tmpdir) / "site"
        site.mkdir()

        # Create secret outside site
        secret = Path(tmpdir) / "secret"
        secret.mkdir()
        secret_file = secret / "password.txt"
        secret_file.write_text("SECRET_PASSWORD\n")

        # Activate sandbox
        tools.set_site_root(str(site))
        try:
            # Simulate oracle creating an escape symlink
            escape_link = site / "escape"
            os.symlink(str(secret), str(escape_link))

            # Oracle tries to read through the escape symlink
            result = tools.dispatch("read-file", {"path": "escape/password.txt"})

            # Must be rejected
            assert result.startswith("Error:"), \
                "Oracle read through escape symlink should be rejected"
            assert "outside the site root" in result, \
                f"Error message should mention sandbox violation: {result}"
            assert "SECRET_PASSWORD" not in result, \
                "Oracle must not be able to read secret content"

        finally:
            tools.set_site_root(None)

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_oracle_cannot_write_through_self_created_escape_symlink():
    """Oracle creating an escape symlink and trying to write through it is blocked."""
    from husks.oracle import tools

    tmpdir = tempfile.mkdtemp(prefix="oracle-write-escape-")
    try:
        site = Path(tmpdir) / "site"
        site.mkdir()

        # Create target directory outside site
        outside = Path(tmpdir) / "outside"
        outside.mkdir()

        tools.set_site_root(str(site))
        try:
            # Simulate oracle creating an escape symlink
            escape_link = site / "escape"
            os.symlink(str(outside), str(escape_link))

            # Oracle tries to write through the escape symlink
            result = tools.dispatch("write-file", {
                "path": "escape/malicious.txt",
                "content": "MALICIOUS CONTENT\n"
            })

            # P29: Must be rejected
            assert result.startswith("Error:"), \
                "Oracle write through escape symlink should be rejected"
            assert "write denied" in result or "outside" in result, \
                f"Error message should mention write denial: {result}"

            # Verify the file was NOT created outside site
            malicious_file = outside / "malicious.txt"
            assert not malicious_file.exists(), \
                "Oracle must not write through escape symlink"

        finally:
            tools.set_site_root(None)

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_oracle_cannot_traverse_parent_directories():
    """Oracle trying to use .. to escape site root is blocked."""
    from husks.oracle import tools

    tmpdir = tempfile.mkdtemp(prefix="oracle-parent-")
    try:
        site = Path(tmpdir) / "site"
        site.mkdir()

        # Create secret outside site
        secret = Path(tmpdir) / "secret.txt"
        secret.write_text("SECRET\n")

        tools.set_site_root(str(site))
        try:
            # Oracle tries to read using ..
            result = tools.dispatch("read-file", {"path": "../secret.txt"})

            # Must be rejected
            assert result.startswith("Error:"), \
                "Oracle parent traversal should be rejected"
            assert "outside the site root" in result, \
                f"Error message should mention sandbox violation: {result}"
            assert "SECRET" not in result, \
                "Oracle must not read secret content"

        finally:
            tools.set_site_root(None)

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_oracle_cannot_write_via_parent_traversal():
    """Oracle trying to write outside site using .. is blocked."""
    from husks.oracle import tools

    tmpdir = tempfile.mkdtemp(prefix="oracle-parent-write-")
    try:
        site = Path(tmpdir) / "site"
        site.mkdir()

        tools.set_site_root(str(site))
        try:
            # Oracle tries to write using ..
            result = tools.dispatch("write-file", {
                "path": "../malicious.txt",
                "content": "MALICIOUS\n"
            })

            # Must be rejected
            assert result.startswith("Error:"), \
                "Oracle parent traversal write should be rejected"
            assert "write denied" in result or "outside" in result, \
                f"Error message should mention write denial: {result}"

            # Verify file was NOT created
            malicious = Path(tmpdir) / "malicious.txt"
            assert not malicious.exists(), \
                "Oracle must not write outside site via .."

        finally:
            tools.set_site_root(None)

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_oracle_cannot_use_absolute_paths_to_escape():
    """Oracle trying to use absolute paths outside site is blocked."""
    from husks.oracle import tools

    tmpdir = tempfile.mkdtemp(prefix="oracle-absolute-")
    try:
        site = Path(tmpdir) / "site"
        site.mkdir()

        # Create secret with absolute path
        secret = Path(tmpdir) / "secret.txt"
        secret.write_text("SECRET\n")

        tools.set_site_root(str(site))
        try:
            # Oracle tries to read using absolute path
            result = tools.dispatch("read-file", {"path": str(secret)})

            # Must be rejected
            assert result.startswith("Error:"), \
                "Oracle absolute path read should be rejected"
            assert "outside the site root" in result, \
                f"Error message should mention sandbox violation: {result}"
            assert "SECRET" not in result, \
                "Oracle must not read via absolute path"

        finally:
            tools.set_site_root(None)

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_oracle_list_dir_blocked_on_escape_symlink():
    """Oracle trying to list directory through escape symlink is blocked."""
    from husks.oracle import tools

    tmpdir = tempfile.mkdtemp(prefix="oracle-list-escape-")
    try:
        site = Path(tmpdir) / "site"
        site.mkdir()

        # Create secret directory outside site
        secret = Path(tmpdir) / "secret"
        secret.mkdir()
        (secret / "confidential.txt").write_text("CONFIDENTIAL\n")

        tools.set_site_root(str(site))
        try:
            # Oracle creates escape symlink
            escape_link = site / "escape"
            os.symlink(str(secret), str(escape_link))

            # Oracle tries to list directory through escape symlink
            result = tools.dispatch("list-dir", {"path": "escape"})

            # Must be rejected
            assert result.startswith("Error:"), \
                "Oracle list-dir through escape symlink should be rejected"
            assert "outside the site root" in result, \
                f"Error message should mention sandbox violation: {result}"
            assert "confidential.txt" not in result, \
                "Oracle must not list files outside site"

        finally:
            tools.set_site_root(None)

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_oracle_tree_blocked_on_escape_symlink():
    """Oracle trying to tree through escape symlink is blocked."""
    from husks.oracle import tools

    tmpdir = tempfile.mkdtemp(prefix="oracle-tree-escape-")
    try:
        site = Path(tmpdir) / "site"
        site.mkdir()

        # Create secret directory outside site
        secret = Path(tmpdir) / "secret"
        secret.mkdir()
        (secret / "password.txt").write_text("PASSWORD\n")

        tools.set_site_root(str(site))
        try:
            # Oracle creates escape symlink
            escape_link = site / "escape"
            os.symlink(str(secret), str(escape_link))

            # Oracle tries to tree through escape symlink
            result = tools.dispatch("tree", {"path": "escape", "depth": 3})

            # tree() should skip the escaping symlink during recursive descent
            # (see test_SOLID_61_tree_sandbox_traversal.py for tree() behavior)
            assert isinstance(result, str), f"Expected string result, got {type(result)}"

            # Secret content must not appear in tree output
            assert "PASSWORD" not in result, \
                "Oracle must not expose secret content via tree"
            assert "password.txt" not in result, \
                "Oracle must not expose secret filenames via tree"

        finally:
            tools.set_site_root(None)

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_oracle_can_use_readonly_imports():
    """Oracle should be able to read through symlinks to readonly roots (imports)."""
    from husks.oracle import tools

    tmpdir = tempfile.mkdtemp(prefix="oracle-readonly-")
    try:
        site = Path(tmpdir) / "site"
        site.mkdir()

        # Create readonly import directory
        readonly = Path(tmpdir) / "readonly"
        readonly.mkdir()
        lib_file = readonly / "library.txt"
        lib_file.write_text("library code\n")

        tools.set_site_root(str(site), readonly=[str(readonly)])
        try:
            # Create symlink to readonly root (import)
            import_link = site / "imports"
            os.symlink(str(readonly), str(import_link))

            # Oracle should be able to read through readonly import
            result = tools.dispatch("read-file", {"path": "imports/library.txt"})

            assert not result.startswith("Error:"), \
                f"Oracle should read readonly imports: {result}"
            assert "library code" in result, \
                "Oracle should access readonly import content"

        finally:
            tools.set_site_root(None)

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_oracle_cannot_write_to_readonly_imports():
    """P29: Oracle must not write to readonly import directories."""
    from husks.oracle import tools

    tmpdir = tempfile.mkdtemp(prefix="oracle-readonly-write-")
    try:
        site = Path(tmpdir) / "site"
        site.mkdir()

        # Create readonly import directory
        readonly = Path(tmpdir) / "readonly"
        readonly.mkdir()

        tools.set_site_root(str(site), readonly=[str(readonly)])
        try:
            # Create symlink to readonly root
            import_link = site / "imports"
            os.symlink(str(readonly), str(import_link))

            # Oracle tries to write to readonly import
            result = tools.dispatch("write-file", {
                "path": "imports/malicious.txt",
                "content": "MALICIOUS\n"
            })

            # P29: Must be rejected
            assert result.startswith("Error:"), \
                "Oracle write to readonly import should be rejected"
            assert "write denied" in result or "outside" in result, \
                f"Error message should mention write denial: {result}"

            # Verify file was NOT created in readonly directory
            malicious = readonly / "malicious.txt"
            assert not malicious.exists(), \
                "Oracle must not write to readonly import"

        finally:
            tools.set_site_root(None)

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)
