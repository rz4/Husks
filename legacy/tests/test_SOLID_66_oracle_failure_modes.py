"""Test that oracle agent failures prevent sealing of partial outputs.

When the oracle agent returns error, halt, kill, or say (non-stop statuses),
the build must halt and not seal partial outputs.
"""

import tempfile
import shutil
from pathlib import Path


def test_oracle_agent_error_prevents_sealing():
    """Oracle agent error (e.g., bad tool call) must halt build without sealing."""
    from husks.build import build, rule, oracle

    tmpdir = tempfile.mkdtemp(prefix="oracle-error-")
    try:
        site = Path(tmpdir) / "site"
        site.mkdir()
        (site / "input.txt").write_text("data\n")

        # Create a custom oracle backend that simulates agent error
        def error_oracle_backend(S, rule_name, recipe, outputs):
            """Mock backend that raises RuntimeError for agent error."""
            raise RuntimeError("oracle agent error: test-tool not in scope")

        node = rule(
            "processor",
            inputs=["input.txt"],
            outputs=["output.txt"],
            recipe=oracle(
                prompt="Write output",
                tools=["write-file"],
                fuel=3,
            ),
        )

        S = build("error-test", 10, node, site=str(site), oracle_backend=error_oracle_backend)

        # Build must halt on agent error
        assert S["status"] == "halted", f"Expected halted, got {S['status']}"
        assert "oracle agent error" in S["value"], f"Error message missing: {S['value']}"

        # Must not seal the rule
        seal_file = site / ".traces" / "processor.seal"
        assert not seal_file.exists(), "Rule was sealed despite agent error"

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_oracle_agent_halt_prevents_sealing():
    """Oracle agent fuel exhaustion must halt build without sealing."""
    from husks.build import build, rule, oracle

    tmpdir = tempfile.mkdtemp(prefix="oracle-halt-")
    try:
        site = Path(tmpdir) / "site"
        site.mkdir()
        (site / "input.txt").write_text("data\n")

        def halt_oracle_backend(S, rule_name, recipe, outputs):
            """Mock backend that raises RuntimeError for fuel exhaustion."""
            raise RuntimeError("oracle agent ran out of fuel")

        node = rule(
            "processor",
            inputs=["input.txt"],
            outputs=["output.txt"],
            recipe=oracle(
                prompt="Write output",
                tools=["write-file"],
                fuel=1,
            ),
        )

        S = build("halt-test", 10, node, site=str(site), oracle_backend=halt_oracle_backend)

        assert S["status"] == "halted", f"Expected halted, got {S['status']}"
        assert "ran out of fuel" in S["value"], f"Error message missing: {S['value']}"

        seal_file = site / ".traces" / "processor.seal"
        assert not seal_file.exists(), "Rule was sealed despite agent halt"

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_oracle_agent_say_prevents_sealing():
    """Oracle agent producing text without stopping must halt build."""
    from husks.build import build, rule, oracle

    tmpdir = tempfile.mkdtemp(prefix="oracle-say-")
    try:
        site = Path(tmpdir) / "site"
        site.mkdir()
        (site / "input.txt").write_text("data\n")

        def say_oracle_backend(S, rule_name, recipe, outputs):
            """Mock backend that raises RuntimeError for text-without-stop."""
            raise RuntimeError(
                "oracle agent produced text without stopping: I'm thinking about this task..."
            )

        node = rule(
            "processor",
            inputs=["input.txt"],
            outputs=["output.txt"],
            recipe=oracle(
                prompt="Write output",
                tools=["write-file"],
                fuel=3,
            ),
        )

        S = build("say-test", 10, node, site=str(site), oracle_backend=say_oracle_backend)

        assert S["status"] == "halted", f"Expected halted, got {S['status']}"
        assert "text without stopping" in S["value"], f"Error message missing: {S['value']}"

        seal_file = site / ".traces" / "processor.seal"
        assert not seal_file.exists(), "Rule was sealed despite agent say"

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_oracle_agent_kill_prevents_sealing():
    """Oracle agent interrupt must halt build without sealing."""
    from husks.build import build, rule, oracle

    tmpdir = tempfile.mkdtemp(prefix="oracle-kill-")
    try:
        site = Path(tmpdir) / "site"
        site.mkdir()
        (site / "input.txt").write_text("data\n")

        def kill_oracle_backend(S, rule_name, recipe, outputs):
            """Mock backend that raises RuntimeError for interrupt."""
            raise RuntimeError("oracle agent interrupted")

        node = rule(
            "processor",
            inputs=["input.txt"],
            outputs=["output.txt"],
            recipe=oracle(
                prompt="Write output",
                tools=["write-file"],
                fuel=3,
            ),
        )

        S = build("kill-test", 10, node, site=str(site), oracle_backend=kill_oracle_backend)

        assert S["status"] == "halted", f"Expected halted, got {S['status']}"
        assert "interrupted" in S["value"], f"Error message missing: {S['value']}"

        seal_file = site / ".traces" / "processor.seal"
        assert not seal_file.exists(), "Rule was sealed despite agent kill"

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_oracle_agent_stop_allows_sealing():
    """Oracle agent stop (success) should allow normal sealing after output guard."""
    from husks.build import build, rule, oracle, site_path

    tmpdir = tempfile.mkdtemp(prefix="oracle-stop-")
    try:
        site = Path(tmpdir) / "site"
        site.mkdir()
        (site / "input.txt").write_text("data\n")

        def stop_oracle_backend(S, rule_name, recipe, outputs):
            """Mock backend that produces the output and returns cost."""
            Path(site_path(S, "output.txt", write=True)).write_text("success\n")
            return {
                "tokens_in": 0,
                "tokens_out": 0,
                "cost_usd": 0.0,
                "fuel_steps": 1,
            }

        node = rule(
            "processor",
            inputs=["input.txt"],
            outputs=["output.txt"],
            recipe=oracle(
                prompt="Write output",
                tools=["write-file"],
                fuel=3,
            ),
        )

        S = build("stop-test", 10, node, site=str(site), oracle_backend=stop_oracle_backend)

        # Should succeed and seal
        assert S["status"] == "committed", f"Expected committed, got {S['status']}"

        seal_file = site / ".traces" / "processor.seal"
        assert seal_file.exists(), "Rule was not sealed after successful stop"

        # Output should exist and be non-empty
        output_file = site / "output.txt"
        assert output_file.exists(), "Output file not created"
        assert output_file.read_text() == "success\n", "Output content incorrect"

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)
