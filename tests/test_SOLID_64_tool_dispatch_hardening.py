"""Test that malformed tool arguments return controlled errors instead of crashing.

Tool dispatch must handle argument errors gracefully to prevent crashing
the oracle loop on LLM hallucinations or malformed tool calls.
"""


def test_dispatch_missing_required_argument():
    """Tool dispatch with missing required argument returns error string."""
    from husks.oracle import tools

    # read-file requires 'path' argument
    result = tools.dispatch("read-file", {})

    assert isinstance(result, str), f"Expected string result, got {type(result)}"
    assert result.startswith("Error:"), f"Expected error, got: {result}"
    assert "argument" in result.lower(), f"Error should mention argument issue: {result}"


def test_dispatch_wrong_argument_type():
    """Tool dispatch with wrong argument type returns error string."""
    from husks.oracle import tools

    # tree expects depth to be int, not string
    result = tools.dispatch("tree", {"path": ".", "depth": "not-an-int"})

    assert isinstance(result, str), f"Expected string result, got {type(result)}"
    assert result.startswith("Error:"), f"Expected error, got: {result}"


def test_dispatch_unexpected_argument():
    """Tool dispatch with unexpected argument returns error string."""
    from husks.oracle import tools

    # list-dir doesn't accept 'nonexistent_arg'
    result = tools.dispatch("list-dir", {"path": ".", "nonexistent_arg": "value"})

    assert isinstance(result, str), f"Expected string result, got {type(result)}"
    assert result.startswith("Error:"), f"Expected error, got: {result}"
    assert "argument" in result.lower(), f"Error should mention argument issue: {result}"


def test_oracle_loop_survives_malformed_tool_calls():
    """Oracle loop continues running after tool argument errors."""
    from husks.oracle.kernel import step

    call_sequence = []

    def mock_M(C):
        """Mock LLM that makes a malformed tool call, then stops."""
        iteration = len([e for e in C.get("trace", []) if "form" in e])

        if iteration == 0:
            # First call: malformed tool arguments (missing required param)
            call_sequence.append("malformed-call")
            return {
                "type": "act",
                "tool": "read-file",
                "args": {},  # Missing required 'path' argument
                "tool_call_id": "bad1",
            }
        elif iteration == 1:
            # Second call: another malformed call (wrong type)
            call_sequence.append("malformed-call-2")
            return {
                "type": "act",
                "tool": "tree",
                "args": {"path": ".", "depth": "wrong-type"},
                "tool_call_id": "bad2",
            }
        else:
            # Third call: stop successfully
            call_sequence.append("stop")
            return {"type": "stop", "value": "done"}

    result = step(mock_M, {"tools": ["read-file", "tree"]}, fuel=5)

    # Loop should complete successfully despite malformed calls
    assert result["type"] == "stop", f"Expected stop, got {result['type']}"
    assert call_sequence == ["malformed-call", "malformed-call-2", "stop"], \
        f"Loop sequence incorrect: {call_sequence}"

    # Both malformed calls should be in the trace with error outputs
    trace = result["C"]["trace"]
    errors = [e for e in trace if "out" in e and "Error:" in str(e["out"])]
    assert len(errors) == 2, f"Expected 2 error results in trace, got {len(errors)}"


def test_tool_execution_error_is_caught():
    """Tool execution errors are caught and returned as error strings."""
    from husks.oracle import tools

    # Register a test tool that raises an exception
    def failing_tool(arg: str, *, site_root=None, readonly_roots=None) -> str:
        """Test tool that always raises an exception."""
        raise RuntimeError("Simulated tool failure")

    original = tools._REGISTRY.get("test-failing-tool")
    try:
        # Manually register the failing tool
        tools._REGISTRY["test-failing-tool"] = {
            "fn": failing_tool,
            "schema": {"type": "function", "function": {"name": "test-failing-tool"}},
        }

        # Dispatch should catch the exception and return error string
        result = tools.dispatch("test-failing-tool", {"arg": "test"})

        assert isinstance(result, str), f"Expected string result, got {type(result)}"
        assert result.startswith("Error:"), f"Expected error, got: {result}"
        assert "execution failed" in result.lower() or "simulated tool failure" in result.lower(), \
            f"Error should mention execution failure: {result}"

    finally:
        # Cleanup
        if original is None:
            tools._REGISTRY.pop("test-failing-tool", None)
        else:
            tools._REGISTRY["test-failing-tool"] = original


def test_context_forwarding_with_malformed_args():
    """Tool dispatch with context forwarding handles malformed args correctly."""
    from husks.oracle import tools
    from pathlib import Path
    import tempfile

    tmpdir = tempfile.mkdtemp(prefix="tool-context-")
    try:
        site_root = Path(tmpdir).resolve()

        # write-file with missing required argument, but with context
        context = {"site_root": site_root, "readonly_roots": set()}
        result = tools.dispatch("write-file", {"content": "test"}, context=context)

        # Should get error about missing 'path', not crash
        assert isinstance(result, str), f"Expected string result, got {type(result)}"
        assert result.startswith("Error:"), f"Expected error, got: {result}"
        assert "argument" in result.lower(), f"Error should mention argument: {result}"

    finally:
        import shutil
        shutil.rmtree(tmpdir, ignore_errors=True)
