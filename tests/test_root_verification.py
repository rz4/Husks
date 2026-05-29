"""
test_root_verification.py -- Beta Gate C3: Root verification in status.

Tests that status command recomputes .husk roots against the live site
and exposes root validity for cross-machine comparison.

Tests cover:
- Valid root verification
- Invalid root detection (tampered outputs)
- Missing .husk file
- Corrupt .husk file
- JSON output includes root_valid field
"""

import tempfile
import shutil
from pathlib import Path


def test_status_verifies_valid_root():
    """Status command verifies valid .husk root."""
    from husks.build import build, rule, action
    from conftest import make_site
    from husks.cli.commands import _cmd_status

    class Args:
        json_output = True
        fail_if_dirty = False
        fail_if_stale = False
        site = None

    tmpdir = tempfile.mkdtemp(prefix="c3-valid-")
    try:
        site = make_site(tmpdir)

        def write_output(S):
            from husks.build.site import write_path
            Path(write_path(S, "out.txt")).write_text("hello\n")

        node = rule("test", outputs=["out.txt"], recipe=action(write_output))
        S = build("test-build", 10, node, site=site)

        assert S["status"] == "committed"
        assert S["build-root"] is not None

        # Run status command
        args = Args()
        args.site = site

        import io
        import sys
        old_stdout = sys.stdout
        sys.stdout = captured = io.StringIO()
        try:
            _cmd_status(args)
        finally:
            sys.stdout = old_stdout

        import json
        status = json.loads(captured.getvalue())

        # Beta C3: Verify root_valid field is present and True
        assert "root_valid" in status, "status should include root_valid"
        assert status["root_valid"] is True, "valid root should be verified"
        assert status["root"] == status.get("recomputed_root"), \
            "manifest root should match recomputed root"

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_status_detects_invalid_root():
    """Status command detects invalid root (tampered output)."""
    from husks.build import build, rule, action
    from conftest import make_site
    from husks.cli.commands import _cmd_status

    class Args:
        json_output = True
        fail_if_dirty = False
        fail_if_stale = False
        site = None

    tmpdir = tempfile.mkdtemp(prefix="c3-invalid-")
    try:
        site = make_site(tmpdir)

        def write_output(S):
            from husks.build.site import write_path
            Path(write_path(S, "out.txt")).write_text("original\n")

        node = rule("test", outputs=["out.txt"], recipe=action(write_output))
        S = build("test-build", 10, node, site=site)

        assert S["status"] == "committed"

        # Tamper with output file
        (Path(site) / "out.txt").write_text("tampered\n")

        # Run status command
        args = Args()
        args.site = site

        import io
        import sys
        old_stdout = sys.stdout
        sys.stdout = captured = io.StringIO()
        try:
            _cmd_status(args)
        finally:
            sys.stdout = old_stdout

        import json
        status = json.loads(captured.getvalue())

        # Beta C3: Root should be invalid due to tampered output
        assert "root_valid" in status
        assert status["root_valid"] is False, "tampered output should invalidate root"
        assert status["root"] != status.get("recomputed_root"), \
            "manifest root should not match recomputed root after tampering"

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_status_missing_husk_file():
    """Status handles missing .husk file gracefully."""
    from husks.build import build, rule, action
    from conftest import make_site
    from husks.cli.commands import _cmd_status

    class Args:
        json_output = True
        fail_if_dirty = False
        fail_if_stale = False
        site = None

    tmpdir = tempfile.mkdtemp(prefix="c3-missing-husk-")
    try:
        site = make_site(tmpdir)

        def write_output(S):
            from husks.build.site import write_path
            Path(write_path(S, "out.txt")).write_text("hello\n")

        node = rule("test", outputs=["out.txt"], recipe=action(write_output))
        S = build("test-build", 10, node, site=site)

        assert S["status"] == "committed"

        # Delete .husk file
        (Path(site) / "test-build.husk").unlink()

        # Run status command
        args = Args()
        args.site = site

        import io
        import sys
        old_stdout = sys.stdout
        sys.stdout = captured = io.StringIO()
        try:
            _cmd_status(args)
        finally:
            sys.stdout = old_stdout

        import json
        status = json.loads(captured.getvalue())

        # Beta C3: Missing .husk means we can't verify
        # root_valid should not be present if .husk is missing
        assert status.get("root_valid") is None, \
            "root_valid should be None when .husk is missing"

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_status_corrupt_husk_file():
    """Status detects corrupt .husk file."""
    from husks.build import build, rule, action
    from conftest import make_site
    from husks.cli.commands import _cmd_status

    class Args:
        json_output = True
        fail_if_dirty = False
        fail_if_stale = False
        site = None

    tmpdir = tempfile.mkdtemp(prefix="c3-corrupt-husk-")
    try:
        site = make_site(tmpdir)

        def write_output(S):
            from husks.build.site import write_path
            Path(write_path(S, "out.txt")).write_text("hello\n")

        node = rule("test", outputs=["out.txt"], recipe=action(write_output))
        S = build("test-build", 10, node, site=site)

        assert S["status"] == "committed"

        # Corrupt .husk file
        (Path(site) / "test-build.husk").write_bytes(b"corrupt data")

        # Run status command
        args = Args()
        args.site = site

        import io
        import sys
        old_stdout = sys.stdout
        sys.stdout = captured = io.StringIO()
        try:
            _cmd_status(args)
        finally:
            sys.stdout = old_stdout

        import json
        status = json.loads(captured.getvalue())

        # Beta C3: Corrupt .husk should result in root_valid=False
        assert "root_valid" in status
        assert status["root_valid"] is False, \
            "corrupt .husk should result in invalid root"

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_status_json_output_includes_verification_fields():
    """Status JSON output includes root verification fields."""
    from husks.build import build, rule, action
    from conftest import make_site
    from husks.cli.commands import _cmd_status

    class Args:
        json_output = True
        fail_if_dirty = False
        fail_if_stale = False
        site = None

    tmpdir = tempfile.mkdtemp(prefix="c3-json-")
    try:
        site = make_site(tmpdir)

        def write_output(S):
            from husks.build.site import write_path
            Path(write_path(S, "out.txt")).write_text("test\n")

        node = rule("worker", outputs=["out.txt"], recipe=action(write_output))
        S = build("demo", 10, node, site=site)

        assert S["status"] == "committed"

        # Run status command
        args = Args()
        args.site = site

        import io
        import sys
        old_stdout = sys.stdout
        sys.stdout = captured = io.StringIO()
        try:
            _cmd_status(args)
        finally:
            sys.stdout = old_stdout

        import json
        status = json.loads(captured.getvalue())

        # Beta C3: JSON output should include verification fields
        assert "root" in status, "JSON should include root"
        assert "root_valid" in status, "JSON should include root_valid"
        assert "recomputed_root" in status, "JSON should include recomputed_root"

        # Both roots should be present and match
        assert status["root"] is not None
        assert status["recomputed_root"] is not None
        assert status["root"] == status["recomputed_root"]
        assert status["root_valid"] is True

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)
