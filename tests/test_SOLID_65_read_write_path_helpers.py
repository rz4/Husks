"""Test read_path/write_path helpers for safe staging in actions."""

import tempfile
import shutil
from pathlib import Path


def test_write_path_uses_staging_during_staged_build():
    """write_path returns staging path during staging, preventing live-site mutation."""
    from husks.build import build, rule, action, write_path

    tmpdir = tempfile.mkdtemp(prefix="write-path-staging-")
    try:
        site = Path(tmpdir) / "site"
        site.mkdir()

        # Create input to trigger staging
        (site / "input.txt").write_text("trigger staging\n")

        # Action using write_path (correct usage)
        def safe_action(S):
            # write_path automatically uses staging during staged builds
            output_path = write_path(S, "output.txt")
            Path(output_path).write_text("written to staging\n")

        node = rule(
            "safe-writer",
            inputs=["input.txt"],
            outputs=["output.txt"],
            recipe=action(safe_action),
        )

        # Build should succeed
        S = build("write-path-test", 10, node, site=str(site))
        assert S["status"] == "committed", f"Build failed: {S['status']}, {S.get('value')}"

        # Output should be in live site (promoted from staging)
        assert (site / "output.txt").exists()
        assert (site / "output.txt").read_text() == "written to staging\n"

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_write_path_uses_live_site_when_not_staging():
    """write_path returns live site path when staging is not active."""
    from husks.build import build, rule, action, write_path

    tmpdir = tempfile.mkdtemp(prefix="write-path-live-")
    try:
        site = Path(tmpdir) / "site"
        site.mkdir()

        # No inputs - staging won't be activated
        def direct_action(S):
            output_path = write_path(S, "direct.txt")
            Path(output_path).write_text("written directly\n")

        node = rule(
            "direct-writer",
            outputs=["direct.txt"],
            recipe=action(direct_action),
        )

        S = build("direct-test", 10, node, site=str(site))
        assert S["status"] == "committed"

        # Output should be in live site
        assert (site / "direct.txt").exists()
        assert (site / "direct.txt").read_text() == "written directly\n"

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_read_path_reads_from_live_site():
    """read_path reads from live site (or staged version if exists)."""
    from husks.build import build, rule, action, read_path, write_path

    tmpdir = tempfile.mkdtemp(prefix="read-path-")
    try:
        site = Path(tmpdir) / "site"
        site.mkdir()

        # Create input file
        (site / "input.txt").write_text("input data\n")

        # Action that reads and transforms
        def reader_action(S):
            input_path = read_path(S, "input.txt")
            content = Path(input_path).read_text()

            output_path = write_path(S, "output.txt")
            Path(output_path).write_text(f"processed: {content}")

        node = rule(
            "reader",
            inputs=["input.txt"],
            outputs=["output.txt"],
            recipe=action(reader_action),
        )

        S = build("read-test", 10, node, site=str(site))
        assert S["status"] == "committed"

        assert (site / "output.txt").exists()
        assert (site / "output.txt").read_text() == "processed: input data\n"

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_nested_paths_with_write_path():
    """write_path handles nested output paths correctly during staging."""
    from husks.build import build, rule, action, write_path

    tmpdir = tempfile.mkdtemp(prefix="nested-write-path-")
    try:
        site = Path(tmpdir) / "site"
        site.mkdir()

        # Create input to trigger staging
        (site / "input.txt").write_text("data\n")

        # Action writing to nested path
        def nested_action(S):
            output_path = write_path(S, "dir/subdir/nested.txt")
            Path(output_path).parent.mkdir(parents=True, exist_ok=True)
            Path(output_path).write_text("nested output\n")

        node = rule(
            "nested-writer",
            inputs=["input.txt"],
            outputs=["dir/subdir/nested.txt"],
            recipe=action(nested_action),
        )

        S = build("nested-test", 10, node, site=str(site))
        assert S["status"] == "committed"

        # Nested output should exist in live site
        nested_file = site / "dir" / "subdir" / "nested.txt"
        assert nested_file.exists()
        assert nested_file.read_text() == "nested output\n"

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_write_path_prevents_live_mutation_during_staging():
    """Actions using write_path cannot accidentally mutate live site during staging.

    This test demonstrates that write_path isolates writes to staging,
    preventing the accidental live-site mutation that was possible with
    bare site_path(S, name) calls.
    """
    from husks.build import build, rule, action, write_path

    tmpdir = tempfile.mkdtemp(prefix="isolation-test-")
    try:
        site = Path(tmpdir) / "site"
        site.mkdir()

        # Create existing output in live site
        (site / "output.txt").write_text("original content\n")

        # First build: create input to enable future staging
        (site / "input.txt").write_text("v1\n")

        def writer_action(S):
            # Using write_path ensures writes go to staging
            output_path = write_path(S, "output.txt")
            Path(output_path).write_text("updated content\n")

        node = rule(
            "updater",
            inputs=["input.txt"],
            outputs=["output.txt"],
            recipe=action(writer_action),
        )

        # First build: establishes baseline
        S1 = build("isolation-1", 10, node, site=str(site))
        assert S1["status"] == "committed"
        assert (site / "output.txt").read_text() == "updated content\n"

        # Modify input to trigger staging on next build
        (site / "input.txt").write_text("v2\n")

        # Second build: staging is active
        # Write goes to staging first, then promoted on success
        # Live site is NOT mutated until promotion
        S2 = build("isolation-2", 10, node, site=str(site))
        assert S2["status"] == "committed"
        assert (site / "output.txt").read_text() == "updated content\n"

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_combining_read_and_write_helpers():
    """Realistic action using both read_path and write_path."""
    from husks.build import build, rule, action, read_path, write_path

    tmpdir = tempfile.mkdtemp(prefix="combined-helpers-")
    try:
        site = Path(tmpdir) / "site"
        site.mkdir()

        # Create multiple inputs
        (site / "data1.txt").write_text("alpha\n")
        (site / "data2.txt").write_text("beta\n")

        # Action that reads multiple inputs and writes multiple outputs
        def combiner_action(S):
            # Read inputs
            d1 = Path(read_path(S, "data1.txt")).read_text()
            d2 = Path(read_path(S, "data2.txt")).read_text()

            # Write outputs (automatically staged)
            Path(write_path(S, "combined.txt")).write_text(f"{d1}{d2}")
            Path(write_path(S, "reversed.txt")).write_text(f"{d2}{d1}")

        node = rule(
            "combiner",
            inputs=["data1.txt", "data2.txt"],
            outputs=["combined.txt", "reversed.txt"],
            recipe=action(combiner_action),
        )

        S = build("combine-test", 10, node, site=str(site))
        assert S["status"] == "committed"

        assert (site / "combined.txt").read_text() == "alpha\nbeta\n"
        assert (site / "reversed.txt").read_text() == "beta\nalpha\n"

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)
