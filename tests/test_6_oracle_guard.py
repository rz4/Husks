"""
test_6_oracle_guard.py -- Guard against silent sealing of empty oracle outputs.

An oracle that produces a missing or zero-byte declared output must halt the build.
Action rules are exempt: zero-byte markers (e.g. `touch .complete`) are legitimate.

Also tests kernel hardening: off-by-one, parallel tool calls, truncation marker.
"""

import json
import os
import shutil
import tempfile

from conftest import make_site


def _empty_oracle_backend(S, rule_name, recipe, outputs):
    """Oracle backend that writes zero-byte files for all outputs."""
    from husks.build import site_path, write_text
    from pathlib import Path
    for o in outputs:
        p = Path(site_path(S, o))
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"")  # zero-byte file
    return {"tokens_in": 0, "tokens_out": 0, "cost_usd": 0.0, "fuel_steps": 1}


def _missing_oracle_backend(S, rule_name, recipe, outputs):
    """Oracle backend that writes nothing -- outputs stay missing."""
    return {"tokens_in": 0, "tokens_out": 0, "cost_usd": 0.0, "fuel_steps": 1}


def test_oracle_empty_output_halts():
    """An oracle producing a zero-byte declared output must halt, not seal."""
    from husks.designs.ir import run
    tmpdir = tempfile.mkdtemp(prefix="oracle-empty-")
    try:
        site = make_site(tmpdir)
        design = {
            "name": "empty-oracle-test",
            "fuel": 10,
            "target": "write-thing",
            "site": site,
            "site_inputs": ["input.txt"],
            "oracle_backend": _empty_oracle_backend,
            "rules": [
                {
                    "name": "write-thing",
                    "kind": "oracle",
                    "inputs": ["input.txt"],
                    "outputs": ["output.txt"],
                    "prompt": "Write something.",
                    "tools": ["write-file"],
                    "fuel": 3,
                },
            ],
        }
        S = run(design)
        assert S["status"] == "halted", (
            f"expected halt on empty oracle output, got: {S['status']}"
        )
        # must not have sealed the empty output
        seal_path = os.path.join(site, ".traces", "write-thing.seal")
        assert not os.path.exists(seal_path), "empty oracle output was sealed"
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_oracle_missing_output_halts():
    """An oracle whose declared output is never written must halt."""
    from husks.designs.ir import run
    tmpdir = tempfile.mkdtemp(prefix="oracle-missing-")
    try:
        site = make_site(tmpdir)
        design = {
            "name": "missing-oracle-test",
            "fuel": 10,
            "target": "write-thing",
            "site": site,
            "site_inputs": ["input.txt"],
            "oracle_backend": _missing_oracle_backend,
            "rules": [
                {
                    "name": "write-thing",
                    "kind": "oracle",
                    "inputs": ["input.txt"],
                    "outputs": ["output.txt"],
                    "prompt": "Write something.",
                    "tools": ["write-file"],
                    "fuel": 3,
                },
            ],
        }
        S = run(design)
        assert S["status"] == "halted", (
            f"expected halt on missing oracle output, got: {S['status']}"
        )
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_action_zero_byte_marker_commits():
    """An action producing a zero-byte marker file must still commit."""
    from husks.designs.ir import run
    tmpdir = tempfile.mkdtemp(prefix="action-marker-")
    try:
        site = make_site(tmpdir)
        design = {
            "name": "marker-test",
            "fuel": 10,
            "target": "finish",
            "site": site,
            "site_inputs": ["input.txt"],
            "rules": [
                {
                    "name": "finish",
                    "kind": "action",
                    "inputs": ["input.txt"],
                    "outputs": [".complete"],
                    "run": "touch .complete",
                },
            ],
        }
        S = run(design)
        assert S["status"] == "committed", (
            f"action with zero-byte marker should commit, got: {S['status']}"
        )
        assert os.path.exists(os.path.join(site, ".complete")), (
            ".complete marker not found"
        )
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


# ── Kernel hardening tests ───────────────────────────────────────


def test_step_fuel_off_by_one():
    """step() must not call M() when fuel is already 0 (off-by-one fix)."""
    from husks.oracle.kernel import step

    call_count = 0

    def counting_M(C):
        nonlocal call_count
        call_count += 1
        return {"type": "stop", "value": "done"}

    result = step(counting_M, {"tools": []}, fuel=0)
    assert result["type"] == "halt", f"expected halt at fuel=0, got {result['type']}"
    assert call_count == 0, f"M() called {call_count} times at fuel=0"


def test_step_fuel_exactly_one():
    """With fuel=1, step() should allow exactly one M() call."""
    from husks.oracle.kernel import step

    call_count = 0

    def counting_M(C):
        nonlocal call_count
        call_count += 1
        return {"type": "act", "tool": "t", "args": {}, "tool_call_id": "x"}

    # Register a dummy tool for dispatch
    from husks.oracle import tools
    orig = tools._REGISTRY.get("t")
    tools._REGISTRY["t"] = {"fn": lambda: "ok", "schema": {}}
    try:
        result = step(counting_M, {"tools": ["t"]}, fuel=1)
        # After 1 act the fuel is 0, next iteration halts before calling M
        assert result["type"] == "halt"
        assert call_count == 1, f"expected 1 M() call with fuel=1, got {call_count}"
        assert result["fuel_steps"] == 1
    finally:
        if orig is None:
            tools._REGISTRY.pop("t", None)
        else:
            tools._REGISTRY["t"] = orig


def test_parse_response_parallel_tool_calls():
    """parse_response returns 'acts' form for multiple tool calls."""
    from husks.oracle.kernel import parse_response

    class _Fn:
        def __init__(self, name, args):
            self.name = name
            self.arguments = json.dumps(args)

    class _Call:
        def __init__(self, id_, fn):
            self.id = id_
            self.function = fn

    class _Msg:
        def __init__(self, tool_calls):
            self.tool_calls = tool_calls
            self.content = None

    class _Choice:
        def __init__(self, msg):
            self.message = msg
            self.finish_reason = "tool_calls"

    class _Response:
        def __init__(self, choices):
            self.choices = choices

    calls = [
        _Call("c1", _Fn("read_file", {"path": "/a"})),
        _Call("c2", _Fn("write_file", {"path": "/b", "content": "x"})),
    ]
    r = _Response([_Choice(_Msg(calls))])
    form = parse_response(r)

    assert form["type"] == "acts"
    assert len(form["calls"]) == 2
    assert form["calls"][0]["tool"] == "read-file"
    assert form["calls"][1]["tool"] == "write-file"
    assert form["calls"][0]["tool_call_id"] == "c1"


def test_parse_response_single_tool_call():
    """parse_response returns 'act' form for a single tool call."""
    from husks.oracle.kernel import parse_response

    class _Fn:
        def __init__(self, name, args):
            self.name = name
            self.arguments = json.dumps(args)

    class _Call:
        def __init__(self, id_, fn):
            self.id = id_
            self.function = fn

    class _Msg:
        def __init__(self, tool_calls):
            self.tool_calls = tool_calls
            self.content = None

    class _Choice:
        def __init__(self, msg):
            self.message = msg
            self.finish_reason = "tool_calls"

    class _Response:
        def __init__(self, choices):
            self.choices = choices

    calls = [_Call("c1", _Fn("read_file", {"path": "/a"}))]
    r = _Response([_Choice(_Msg(calls))])
    form = parse_response(r)

    assert form["type"] == "act"
    assert form["tool"] == "read-file"


def test_truncation_marker():
    """_truncate adds a marker when content exceeds MAX_TOOL_OUTPUT."""
    from husks.oracle.kernel import _truncate, MAX_TOOL_OUTPUT

    short = "hello"
    assert _truncate(short) == short

    long_str = "x" * (MAX_TOOL_OUTPUT + 100)
    result = _truncate(long_str)
    assert len(result) > MAX_TOOL_OUTPUT
    assert result.endswith("[... truncated ...]")
    assert result[:MAX_TOOL_OUTPUT] == "x" * MAX_TOOL_OUTPUT


def test_step_parallel_acts_dispatches_all():
    """step() with 'acts' form dispatches all tool calls and charges fuel."""
    from husks.oracle.kernel import step

    iteration = [0]

    def mock_M(C):
        iteration[0] += 1
        if iteration[0] == 1:
            return {
                "type": "acts",
                "calls": [
                    {"tool": "t", "args": {}, "tool_call_id": "a"},
                    {"tool": "t", "args": {}, "tool_call_id": "b"},
                ],
            }
        return {"type": "stop", "value": "done"}

    from husks.oracle import tools
    dispatch_count = [0]
    orig = tools._REGISTRY.get("t")
    def dummy_fn(**kwargs):
        dispatch_count[0] += 1
        return "ok"
    tools._REGISTRY["t"] = {"fn": dummy_fn, "schema": {}}
    try:
        result = step(mock_M, {"tools": ["t"]}, fuel=5)
        assert result["type"] == "stop"
        assert dispatch_count[0] == 2, f"expected 2 dispatches, got {dispatch_count[0]}"
        assert result["fuel_steps"] == 2  # 2 tool calls consumed
    finally:
        if orig is None:
            tools._REGISTRY.pop("t", None)
        else:
            tools._REGISTRY["t"] = orig
