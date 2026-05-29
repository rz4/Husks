"""
test_compare_cli.py -- Beta Gate C6/C7: CLI compare command.

Tests the `husks compare` command for cross-machine artifact verification.
Validates JSON output format and equivalence detection.
"""

import json
import subprocess
import sys
import tempfile
import shutil
from pathlib import Path


def test_compare_equivalent_sites():
    """husks compare detects equivalent sites."""
    from husks.build import build, rule, action

    tmpdir = tempfile.mkdtemp(prefix="compare-equiv-")
    try:
        # Build same design in two sites
        site_a = Path(tmpdir) / "site_a"
        site_a.mkdir()

        site_b = Path(tmpdir) / "site_b"
        site_b.mkdir()

        def write_output(S):
            from husks.build.site import write_path
            Path(write_path(S, "out.txt")).write_text("identical\n")

        node = rule("worker", outputs=["out.txt"], recipe=action(write_output))

        build("demo", 10, node, site=str(site_a))
        build("demo", 10, node, site=str(site_b))

        # Run compare command
        result = subprocess.run(
            [sys.executable, "-m", "husks.cli", "compare", str(site_a), str(site_b), "--json"],
            capture_output=True,
            text=True,
            timeout=30,
        )

        assert result.returncode == 0, (
            f"compare should exit 0 for equivalent sites\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )

        # Parse JSON output
        output = json.loads(result.stdout)
        assert output["equivalent"] is True, "Sites should be equivalent"
        assert len(output["comparisons"]) == 1, "Should have one pairwise comparison"
        assert output["comparisons"][0]["equivalent"] is True

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_compare_different_sites():
    """husks compare detects non-equivalent sites."""
    from husks.build import build, rule, action

    tmpdir = tempfile.mkdtemp(prefix="compare-diff-")
    try:
        site_a = Path(tmpdir) / "site_a"
        site_a.mkdir()

        site_b = Path(tmpdir) / "site_b"
        site_b.mkdir()

        def write_a(S):
            from husks.build.site import write_path
            Path(write_path(S, "out.txt")).write_text("output A\n")

        def write_b(S):
            from husks.build.site import write_path
            Path(write_path(S, "out.txt")).write_text("output B\n")

        node_a = rule("worker", outputs=["out.txt"], recipe=action(write_a))
        node_b = rule("worker", outputs=["out.txt"], recipe=action(write_b))

        build("demo", 10, node_a, site=str(site_a))
        build("demo", 10, node_b, site=str(site_b))

        # Run compare command
        result = subprocess.run(
            [sys.executable, "-m", "husks.cli", "compare", str(site_a), str(site_b), "--json"],
            capture_output=True,
            text=True,
            timeout=30,
        )

        # Should exit non-zero for non-equivalent sites
        assert result.returncode != 0, (
            f"compare should exit non-zero for different sites, got {result.returncode}"
        )

        # Parse JSON output
        output = json.loads(result.stdout)
        assert output["equivalent"] is False, "Sites should not be equivalent"
        assert len(output["comparisons"][0]["differences"]) > 0, "Should report differences"

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_compare_three_sites():
    """husks compare handles three sites (pairwise comparisons)."""
    from husks.build import build, rule, action

    tmpdir = tempfile.mkdtemp(prefix="compare-three-")
    try:
        # Build same design in three sites
        sites = []
        for i in range(3):
            site = Path(tmpdir) / f"site_{i}"
            site.mkdir()
            sites.append(site)

            def write_output(S):
                from husks.build.site import write_path
                Path(write_path(S, "out.txt")).write_text("same\n")

            node = rule("worker", outputs=["out.txt"], recipe=action(write_output))
            build("demo", 10, node, site=str(site))

        # Run compare command on all three
        result = subprocess.run(
            [sys.executable, "-m", "husks.cli", "compare"] + [str(s) for s in sites] + ["--json"],
            capture_output=True,
            text=True,
            timeout=30,
        )

        assert result.returncode == 0, "All three sites should be equivalent"

        # Parse JSON output
        output = json.loads(result.stdout)
        assert output["equivalent"] is True
        # Three sites → 3 pairwise comparisons (0-1, 0-2, 1-2)
        assert len(output["comparisons"]) == 3, "Should have 3 pairwise comparisons"

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_compare_json_output_is_quiet():
    """JSON output contains only JSON, no console noise (Beta Gate C7)."""
    from husks.build import build, rule, action

    tmpdir = tempfile.mkdtemp(prefix="compare-quiet-")
    try:
        site_a = Path(tmpdir) / "site_a"
        site_a.mkdir()

        site_b = Path(tmpdir) / "site_b"
        site_b.mkdir()

        def write_output(S):
            from husks.build.site import write_path
            Path(write_path(S, "out.txt")).write_text("data\n")

        node = rule("worker", outputs=["out.txt"], recipe=action(write_output))

        build("demo", 10, node, site=str(site_a))
        build("demo", 10, node, site=str(site_b))

        result = subprocess.run(
            [sys.executable, "-m", "husks.cli", "compare", str(site_a), str(site_b), "--json"],
            capture_output=True,
            text=True,
            timeout=30,
        )

        # Verify output is valid JSON (no console banners)
        try:
            output = json.loads(result.stdout)
        except json.JSONDecodeError as e:
            raise AssertionError(
                f"JSON output should be valid JSON, got JSONDecodeError: {e}\n"
                f"stdout: {result.stdout}"
            )

        # Verify structure
        assert "equivalent" in output
        assert "comparisons" in output
        assert isinstance(output["comparisons"], list)

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_compare_requires_at_least_two_sites():
    """husks compare requires at least 2 sites."""
    result = subprocess.run(
        [sys.executable, "-m", "husks.cli", "compare", "/tmp/site1", "--json"],
        capture_output=True,
        text=True,
        timeout=30,
    )

    # Should fail with usage error
    assert result.returncode != 0
    assert "at least 2 sites" in result.stderr


def test_compare_roots_only_flag():
    """--roots-only flag skips output hash checks."""
    from husks.build import build, rule, action

    tmpdir = tempfile.mkdtemp(prefix="compare-roots-")
    try:
        site_a = Path(tmpdir) / "site_a"
        site_a.mkdir()

        site_b = Path(tmpdir) / "site_b"
        site_b.mkdir()

        def write_output(S):
            from husks.build.site import write_path
            Path(write_path(S, "out.txt")).write_text("same\n")

        node = rule("worker", outputs=["out.txt"], recipe=action(write_output))

        build("demo", 10, node, site=str(site_a))
        build("demo", 10, node, site=str(site_b))

        result = subprocess.run(
            [sys.executable, "-m", "husks.cli", "compare", str(site_a), str(site_b),
             "--roots-only", "--json"],
            capture_output=True,
            text=True,
            timeout=30,
        )

        assert result.returncode == 0
        output = json.loads(result.stdout)
        assert output["equivalent"] is True

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_compare_hashes_only_flag():
    """--hashes-only flag skips root checks."""
    from husks.build import build, rule, action

    tmpdir = tempfile.mkdtemp(prefix="compare-hashes-")
    try:
        site_a = Path(tmpdir) / "site_a"
        site_a.mkdir()

        site_b = Path(tmpdir) / "site_b"
        site_b.mkdir()

        def write_output(S):
            from husks.build.site import write_path
            Path(write_path(S, "out.txt")).write_text("same\n")

        node = rule("worker", outputs=["out.txt"], recipe=action(write_output))

        build("demo", 10, node, site=str(site_a))
        build("demo", 10, node, site=str(site_b))

        result = subprocess.run(
            [sys.executable, "-m", "husks.cli", "compare", str(site_a), str(site_b),
             "--hashes-only", "--json"],
            capture_output=True,
            text=True,
            timeout=30,
        )

        assert result.returncode == 0
        output = json.loads(result.stdout)
        assert output["equivalent"] is True

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)
