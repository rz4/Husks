"""Test that output validation during staging rejects live-site writes."""

import tempfile
import shutil
from pathlib import Path


def test_failed_action_cannot_seal_live_writes():
    """Python actions that fail after writing to live site must not seal.

    Regression test: Actions that write to live site and then fail (exception)
    do not seal those outputs. The exception halts the build before sealing.
    """
    from husks.build import build, rule, action
    from husks.build.site import site_path

    tmpdir = tempfile.mkdtemp(prefix="output-validation-")
    try:
        site = Path(tmpdir) / "site"
        site.mkdir()

        # Create input to trigger staging
        (site / "input.txt").write_text("data\n")

        # Python action that writes to live site then fails
        def bad_action(S):
            # Write to live site (bypassing staging - legacy compatibility)
            live_path = site_path(S, "output.txt")
            Path(live_path).write_text("partial write before failure\n")
            # Now fail
            raise RuntimeError("action failed after live write")

        node = rule(
            "failing-writer",
            inputs=["input.txt"],
            outputs=["output.txt"],
            recipe=action(bad_action),
        )

        # Build should halt due to exception
        S = build("fail-test", 10, node, site=str(site))
        assert S["status"] == "halted", f"Expected halted, got {S['status']}"
        assert "action failed after live write" in S["value"]

        # Live write exists from the action
        assert (site / "output.txt").exists(), "Live file exists from bypass write"

        # Verify no seal was written (exception prevented sealing)
        seal_path = site / ".traces" / "failing-writer.seal"
        assert not seal_path.exists(), "Seal must not exist when action fails"

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_action_writing_to_staging_succeeds():
    """Python actions that correctly use staging should work normally."""
    from husks.build import build, rule, action
    from husks.build.site import site_path

    tmpdir = tempfile.mkdtemp(prefix="staging-success-")
    try:
        site = Path(tmpdir) / "site"
        site.mkdir()

        # Create input to trigger staging
        (site / "input.txt").write_text("data\n")

        # Python action that correctly writes to staging
        def good_action(S):
            # Correctly use write=True to write to staging
            staged_path = site_path(S, "output.txt", write=True)
            Path(staged_path).parent.mkdir(parents=True, exist_ok=True)
            Path(staged_path).write_text("staged correctly\n")

        node = rule(
            "correct-writer",
            inputs=["input.txt"],
            outputs=["output.txt"],
            recipe=action(good_action),
        )

        # Build should succeed
        S = build("staging-success", 10, node, site=str(site))
        assert S["status"] == "committed", f"Build failed: {S['status']}, {S.get('value')}"

        # Output should be promoted to live site
        assert (site / "output.txt").exists()
        assert (site / "output.txt").read_text() == "staged correctly\n"

        # Seal should exist
        seal_path = site / ".traces" / "correct-writer.seal"
        assert seal_path.exists(), "Seal should exist for successful build"

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_oracle_cannot_bypass_staging():
    """Oracle recipes must write to staging - no fallback to live site.

    Unlike action recipes (which allow legacy bypass for compatibility),
    oracle and trial recipes are framework-controlled and must write to
    staging correctly during staged builds.
    """
    from husks.build import build, rule, oracle
    from husks.build.site import site_path, write_text

    tmpdir = tempfile.mkdtemp(prefix="oracle-staging-")
    try:
        site = Path(tmpdir) / "site"
        site.mkdir()

        # Create input to trigger staging
        (site / "input.txt").write_text("data\n")

        # Mock oracle backend that bypasses staging (writes to live site)
        def bad_oracle_backend(S, rule_name, recipe, outputs):
            # Intentionally bypass staging - write to live site
            for o in outputs:
                live_path = site_path(S, o)  # Missing write=True
                write_text(live_path, "bypassed staging from oracle\n")
            return {"tokens_in": 10, "tokens_out": 20, "cost_usd": 0.001, "fuel_steps": 1}

        node = rule(
            "oracle-bypasser",
            inputs=["input.txt"],
            outputs=["result.txt"],
            recipe=oracle("test prompt"),
        )

        # Build with bad backend
        S = build("oracle-test", 10, node, site=str(site), oracle_backend=bad_oracle_backend)

        # Build should fail - oracle outputs not found in staging
        assert S["status"] == "halted", f"Expected halted, got {S['status']}"
        assert "did not produce declared output" in S["value"], \
            f"Expected validation error, got: {S['value']}"

        # Verify no seal written (validation failed)
        seal_path = site / ".traces" / "oracle-bypasser.seal"
        assert not seal_path.exists(), "Seal must not exist for failed oracle"

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_non_staged_build_still_validates_outputs():
    """Outside staging (no existing outputs), validation still works."""
    from husks.build import build, rule, action
    from husks.build.site import site_path

    tmpdir = tempfile.mkdtemp(prefix="non-staged-")
    try:
        site = Path(tmpdir) / "site"
        site.mkdir()

        # Action that fails to create output
        def no_output_action(S):
            # Intentionally don't create the output
            pass

        node = rule(
            "no-output",
            outputs=["missing.txt"],
            recipe=action(no_output_action),
        )

        # Build should fail validation
        S = build("no-output-test", 10, node, site=str(site))
        assert S["status"] == "halted"
        assert "did not produce declared output" in S["value"]

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)
