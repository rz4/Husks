"""
test_trial_binary_outputs.py -- Tests for Beta B5 trial output validation.

Beta Gate B5: Make trial outputs binary-safe or explicitly text-only.

For beta, trial outputs are explicitly limited to text. Binary outputs
are rejected with a clear error message.
"""

import tempfile
import shutil
from pathlib import Path


def test_trial_text_outputs_accepted():
    """Trial branches with text outputs work normally."""
    from husks.build import build, rule, trial, action, oracle

    tmpdir = tempfile.mkdtemp(prefix="b5-text-")
    try:
        site = Path(tmpdir) / "site"
        site.mkdir()

        def write_text_a(S):
            from husks.build.site import site_path
            output = site_path(S, "result.txt", write=True)
            Path(output).write_text("branch a\n")

        def write_text_b(S):
            from husks.build.site import site_path
            output = site_path(S, "result.txt", write=True)
            Path(output).write_text("branch b\n")

        node = rule(
            "text-trial",
            outputs=["result.txt"],
            recipe=trial(
                {"name": "a", "type": "action", "fn": write_text_a},
                {"name": "b", "type": "action", "fn": write_text_b},
                verdict=lambda results: results[0],  # Pick first
            ),
        )

        S = build("text-trial-test", 10, node, site=str(site))
        assert S["status"] == "committed"
        assert (site / "result.txt").read_text() == "branch a\n"

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_trial_binary_output_rejected():
    """Trial branches that produce binary outputs are rejected."""
    from husks.build import build, rule, trial, action

    tmpdir = tempfile.mkdtemp(prefix="b5-binary-")
    try:
        site = Path(tmpdir) / "site"
        site.mkdir()

        def write_binary(S):
            from husks.build.site import site_path
            output = site_path(S, "result.bin", write=True)
            # Write binary data
            Path(output).write_bytes(b'\x00\x01\x02\xff\xfe\xfd')

        def write_text(S):
            from husks.build.site import site_path
            output = site_path(S, "result.bin", write=True)
            Path(output).write_text("text fallback\n")

        node = rule(
            "binary-trial",
            outputs=["result.bin"],
            recipe=trial(
                {"name": "binary", "type": "action", "fn": write_binary},
                {"name": "text", "type": "action", "fn": write_text},
                verdict=lambda results: results[0],  # Try binary first
            ),
        )

        S = build("binary-trial-test", 10, node, site=str(site))
        assert S["status"] == "halted"
        assert "binary data" in S["value"]
        assert "must be text-only" in S["value"]

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_trial_with_unicode_text():
    """Trial outputs can contain Unicode text."""
    from husks.build import build, rule, trial, action

    tmpdir = tempfile.mkdtemp(prefix="b5-unicode-")
    try:
        site = Path(tmpdir) / "site"
        site.mkdir()

        def write_unicode(S):
            from husks.build.site import site_path
            output = site_path(S, "result.txt", write=True)
            Path(output).write_text("Hello 世界 🌍\n", encoding="utf-8")

        node = rule(
            "unicode-trial",
            outputs=["result.txt"],
            recipe=trial(
                {"name": "unicode", "type": "action", "fn": write_unicode},
                verdict=lambda results: results[0],
            ),
        )

        S = build("unicode-trial-test", 10, node, site=str(site))
        assert S["status"] == "committed"
        content = (site / "result.txt").read_text(encoding="utf-8")
        assert "世界" in content
        assert "🌍" in content

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_trial_empty_output_is_text():
    """Empty files are valid text outputs for trials."""
    from husks.build import build, rule, trial, action

    tmpdir = tempfile.mkdtemp(prefix="b5-empty-")
    try:
        site = Path(tmpdir) / "site"
        site.mkdir()

        def write_empty(S):
            from husks.build.site import site_path
            output = site_path(S, "result.txt", write=True)
            Path(output).write_text("")

        node = rule(
            "empty-trial",
            outputs=["result.txt"],
            recipe=trial(
                {"name": "empty", "type": "action", "fn": write_empty},
                verdict=lambda results: results[0],
            ),
        )

        S = build("empty-trial-test", 10, node, site=str(site))
        assert S["status"] == "committed"
        assert (site / "result.txt").read_text() == ""

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)
