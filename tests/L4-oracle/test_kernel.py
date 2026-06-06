"""test_kernel.py -- Fuel-bounded agentic loop tests."""

import json
from husks.oracle import (
    parse_response, _build_messages, _truncate, _rebind, _allowed,
    _dispatch_context, step, agent, MAX_TOOL_OUTPUT,
)


# ── Mock LLM response ───────────────────────────────────────────

class _Function:
    def __init__(self, name, arguments):
        self.name = name
        self.arguments = arguments

class _ToolCall:
    def __init__(self, id, function):
        self.id = id
        self.function = function

class _Message:
    def __init__(self, content=None, tool_calls=None):
        self.content = content
        self.tool_calls = tool_calls

class _Choice:
    def __init__(self, message, finish_reason="stop"):
        self.message = message
        self.finish_reason = finish_reason

class _Response:
    def __init__(self, choices):
        self.choices = choices


def _stop_response(text="done"):
    return _Response([_Choice(_Message(content=text), "stop")])

def _say_response(text="hello"):
    return _Response([_Choice(_Message(content=text), "length")])

def _act_response(tool_name, args, call_id="c1"):
    fn = _Function(tool_name, json.dumps(args))
    tc = _ToolCall(call_id, fn)
    return _Response([_Choice(_Message(content=None, tool_calls=[tc]), "tool_calls")])

def _acts_response(calls):
    """calls: list of (tool_name, args, call_id)"""
    tcs = [_ToolCall(cid, _Function(name, json.dumps(args))) for name, args, cid in calls]
    return _Response([_Choice(_Message(content=None, tool_calls=tcs), "tool_calls")])


# ── parse_response ───────────────────────────────────────────────

class TestParseResponse:
    def test_stop(self):
        r = parse_response(_stop_response("bye"))
        assert r["type"] == "stop"
        assert r["value"] == "bye"

    def test_say(self):
        r = parse_response(_say_response("hi"))
        assert r["type"] == "say"
        assert r["text"] == "hi"

    def test_single_act(self):
        r = parse_response(_act_response("read_file", {"path": "x.txt"}))
        assert r["type"] == "act"
        assert r["tool"] == "read-file"
        assert r["args"]["path"] == "x.txt"
        assert r["tool_call_id"] == "c1"

    def test_parallel_acts(self):
        r = parse_response(_acts_response([
            ("read_file", {"path": "a.txt"}, "c1"),
            ("write_file", {"path": "b.txt", "content": "x"}, "c2"),
        ]))
        assert r["type"] == "acts"
        assert len(r["calls"]) == 2
        assert r["calls"][0]["tool"] == "read-file"
        assert r["calls"][1]["tool"] == "write-file"

    def test_malformed_args(self):
        fn = _Function("read_file", "not-json{{{")
        tc = _ToolCall("c1", fn)
        r = parse_response(_Response([_Choice(_Message(tool_calls=[tc]), "tool_calls")]))
        assert r["type"] == "act"
        assert r["args"] == {}


# ── _truncate ────────────────────────────────────────────────────

class TestTruncate:
    def test_short_string_unchanged(self):
        assert _truncate("hello") == "hello"

    def test_long_string_truncated(self):
        s = "x" * (MAX_TOOL_OUTPUT + 100)
        t = _truncate(s)
        assert len(t) < len(s)
        assert "[... truncated ...]" in t


# ── _rebind / _allowed / _dispatch_context ───────────────────────

class TestContextHelpers:
    def test_rebind_appends_event(self):
        C = {"trace": [{"a": 1}]}
        C2 = _rebind(C, {"b": 2})
        assert len(C2["trace"]) == 2
        assert C2["trace"][1] == {"b": 2}
        assert len(C["trace"]) == 1  # original unchanged

    def test_rebind_initializes_trace(self):
        C2 = _rebind({}, {"a": 1})
        assert C2["trace"] == [{"a": 1}]

    def test_allowed_true(self):
        assert _allowed({"tools": ["read-file", "write-file"]}, "read-file")

    def test_allowed_false(self):
        assert not _allowed({"tools": ["read-file"]}, "write-file")

    def test_dispatch_context_empty(self):
        assert _dispatch_context({}) == {}

    def test_dispatch_context_with_roots(self):
        from pathlib import Path
        C = {"site_root": Path("/site"), "readonly_roots": {Path("/ro")}}
        ctx = _dispatch_context(C)
        assert ctx["context"]["site_root"] == Path("/site")


# ── _build_messages ──────────────────────────────────────────────

class TestBuildMessages:
    def test_initial_prompt(self):
        msgs = _build_messages({"prompt": "Do it.", "trace": []})
        assert len(msgs) == 1
        assert msgs[0]["role"] == "user"
        assert msgs[0]["content"] == "Do it."

    def test_act_trace(self):
        C = {"prompt": "Go.", "trace": [
            {"form": {"type": "act", "tool_call_id": "t1", "args": {"path": "x"}},
             "tool": "read-file", "out": "contents"},
        ]}
        msgs = _build_messages(C)
        assert len(msgs) == 3  # user, assistant, tool
        assert msgs[1]["role"] == "assistant"
        assert msgs[1]["tool_calls"][0]["function"]["name"] == "read_file"
        assert msgs[2]["role"] == "tool"
        assert msgs[2]["content"] == "contents"

    def test_acts_trace(self):
        C = {"prompt": "Go.", "trace": [
            {"form": {"type": "acts"},
             "calls": [
                 {"tool": "read-file", "args": {"path": "a"}, "tool_call_id": "t1"},
                 {"tool": "read-file", "args": {"path": "b"}, "tool_call_id": "t2"},
             ],
             "results": ["aaa", "bbb"]},
        ]}
        msgs = _build_messages(C)
        assert len(msgs) == 4  # user, assistant, tool, tool


# ── step (agentic loop) ─────────────────────────────────────────

class TestStep:
    def test_immediate_stop(self):
        def M(C): return {"type": "stop", "value": "done"}
        r = step(M, {"tools": []}, fuel=5)
        assert r["type"] == "stop"
        assert r["fuel_steps"] == 0

    def test_say_returns(self):
        def M(C): return {"type": "say", "text": "hello"}
        r = step(M, {"tools": []}, fuel=5)
        assert r["type"] == "say"

    def test_fuel_exhaustion(self):
        r = step(lambda C: {"type": "act", "tool": "x"}, {"tools": []}, fuel=0)
        assert r["type"] == "halt"

    def test_disallowed_tool_error(self):
        def M(C): return {"type": "act", "tool": "bad-tool", "args": {}}
        r = step(M, {"tools": ["read-file"], "trace": []}, fuel=5)
        assert r["type"] == "error"
        assert "not in scope" in r["error"]

    def test_act_burns_fuel(self, tmp_site):
        call_count = [0]
        def M(C):
            call_count[0] += 1
            if call_count[0] <= 2:
                return {"type": "act", "tool": "read-file", "args": {"path": "."}, "tool_call_id": f"t{call_count[0]}"}
            return {"type": "stop", "value": "done"}
        C = {"tools": ["read-file"], "trace": [], "site_root": tmp_site}
        (tmp_site / "test.txt").write_text("x")
        r = step(M, C, fuel=5)
        assert r["type"] == "stop"
        assert r["fuel_steps"] == 2

    def test_parallel_acts_burn_fuel(self, tmp_site):
        call_count = [0]
        def M(C):
            call_count[0] += 1
            if call_count[0] == 1:
                return {"type": "acts", "calls": [
                    {"tool": "read-file", "args": {"path": "."}, "tool_call_id": "t1"},
                    {"tool": "read-file", "args": {"path": "."}, "tool_call_id": "t2"},
                ]}
            return {"type": "stop", "value": "done"}
        C = {"tools": ["read-file"], "trace": [], "site_root": tmp_site}
        r = step(M, C, fuel=5)
        assert r["type"] == "stop"
        assert r["fuel_steps"] == 2

    def test_parallel_acts_partial_fuel(self, tmp_site):
        """Parallel batch with only 1 fuel left should halt after first call."""
        def M(C):
            return {"type": "acts", "calls": [
                {"tool": "read-file", "args": {"path": "."}, "tool_call_id": "t1"},
                {"tool": "read-file", "args": {"path": "."}, "tool_call_id": "t2"},
            ]}
        C = {"tools": ["read-file"], "trace": [], "site_root": tmp_site}
        r = step(M, C, fuel=1)
        assert r["type"] == "halt"
        assert r["fuel_steps"] == 1

    def test_bad_form_error(self):
        def M(C): return {"type": "unknown-thing"}
        r = step(M, {"tools": [], "trace": []}, fuel=5)
        assert r["type"] == "error"
        assert "bad form" in r["error"]


# ── agent ────────────────────────────────────────────────────────

class TestAgent:
    def test_agent_with_mock_m(self):
        def M(C): return {"type": "stop", "value": "ok"}
        r = agent({"prompt": "test", "tools": []}, fuel=3, M=M)
        assert r["type"] == "stop"

    def test_agent_sets_up_tool_defs(self):
        captured = {}
        def M(C):
            captured["tool-defs"] = C.get("tool-defs", [])
            return {"type": "stop", "value": "ok"}
        agent({"prompt": "test", "tools": ["read-file"]}, fuel=3, M=M)
        assert len(captured["tool-defs"]) == 1
        assert captured["tool-defs"][0]["function"]["name"] == "read-file"
