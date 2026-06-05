"""test_gate.py -- Claude Code backend gate, usage tracker, provenance tests."""

import pytest
from pathlib import Path
from husks.oracle import (
    _Gate, CC_TOOL_MAP, UsageTracker,
    compute_config_hash, compute_prompt_hash, DEFAULT_MODEL,
)


# ── _Gate (Claude Code interceptor) ─────────────────────────────

class TestGate:
    def _make_gate(self, tmp_path, fuel=5, tools=None):
        site = tmp_path / "site"
        site.mkdir(exist_ok=True)
        allowed = tools or {"Read", "Write"}
        return _Gate(allowed, fuel, site.resolve(), set())

    def test_allowed_tool(self, tmp_path):
        g = self._make_gate(tmp_path)
        ok, reason = g.decide("Read", {"file_path": "x.txt"})
        assert ok
        assert g.steps == 1

    def test_disallowed_tool(self, tmp_path):
        g = self._make_gate(tmp_path)
        ok, reason = g.decide("Bash", {})
        assert not ok
        assert "not in scope" in reason

    def test_path_escape_denied(self, tmp_path):
        g = self._make_gate(tmp_path)
        ok, reason = g.decide("Read", {"file_path": "/etc/passwd"})
        assert not ok
        assert "path escapes site" in reason

    def test_dotdot_denied(self, tmp_path):
        g = self._make_gate(tmp_path)
        ok, reason = g.decide("Read", {"file_path": "../escape"})
        assert not ok

    def test_fuel_exhaustion(self, tmp_path):
        g = self._make_gate(tmp_path, fuel=1)
        ok1, _ = g.decide("Read", {"file_path": "x.txt"})
        assert ok1
        ok2, reason = g.decide("Read", {"file_path": "y.txt"})
        assert not ok2
        assert "out of fuel" in reason
        assert g.exhausted

    def test_relative_path_ok(self, tmp_path):
        g = self._make_gate(tmp_path)
        ok, _ = g.decide("Read", {"file_path": "sub/file.txt"})
        assert ok

    def test_readonly_root(self, tmp_path):
        site = tmp_path / "site"
        site.mkdir()
        ro = tmp_path / "imports"
        ro.mkdir()
        g = _Gate({"Read"}, 5, site.resolve(), {ro.resolve()})
        ok, _ = g.decide("Read", {"file_path": str(ro / "data.txt")})
        assert ok

    def test_empty_path_ignored(self, tmp_path):
        g = self._make_gate(tmp_path)
        ok, _ = g.decide("Read", {"file_path": ""})
        assert ok  # empty path not checked

    def test_no_path_key_ok(self, tmp_path):
        g = self._make_gate(tmp_path)
        ok, _ = g.decide("Read", {"content": "stuff"})
        assert ok


# ── CC_TOOL_MAP ──────────────────────────────────────────────────

class TestToolMap:
    def test_expected_mappings(self):
        assert CC_TOOL_MAP["read-file"] == "Read"
        assert CC_TOOL_MAP["write-file"] == "Write"
        assert CC_TOOL_MAP["list-dir"] == "Glob"
        assert CC_TOOL_MAP["tree"] == "Glob"

    def test_all_default_tools_mapped(self):
        from husks.oracle import DEFAULT_TOOLS
        for t in DEFAULT_TOOLS:
            assert t in CC_TOOL_MAP


# ── UsageTracker ─────────────────────────────────────────────────

class _MockUsage:
    def __init__(self, inp=10, out=20):
        self.prompt_tokens = inp
        self.completion_tokens = out

class _MockResponse:
    def __init__(self, model="test-model", inp=10, out=20):
        self.usage = _MockUsage(inp, out)
        self.model = model


class TestUsageTracker:
    def test_initial_state(self):
        t = UsageTracker()
        s = t.snapshot()
        assert s["calls"] == 0
        assert s["input_tokens"] == 0

    def test_track_accumulates(self):
        t = UsageTracker()
        t.track(_MockResponse(inp=10, out=20))
        t.track(_MockResponse(inp=5, out=15))
        s = t.snapshot()
        assert s["calls"] == 2
        assert s["input_tokens"] == 15
        assert s["output_tokens"] == 35

    def test_track_by_rule(self):
        t = UsageTracker()
        t.track(_MockResponse(inp=10, out=20), rule="r1")
        t.track(_MockResponse(inp=5, out=15), rule="r2")
        t.track(_MockResponse(inp=3, out=7), rule="r1")
        s = t.snapshot()
        assert s["by_rule"]["r1"]["calls"] == 2
        assert s["by_rule"]["r1"]["input_tokens"] == 13
        assert s["by_rule"]["r2"]["calls"] == 1

    def test_model_captured(self):
        t = UsageTracker()
        t.track(_MockResponse(model="gpt-4"))
        assert t.snapshot()["model"] == "gpt-4"


# ── Provenance hashing ──────────────────────────────────────────

class TestProvenance:
    def test_config_hash_deterministic(self):
        h1 = compute_config_hash("m", 1024)
        h2 = compute_config_hash("m", 1024)
        assert h1 == h2
        assert len(h1) == 64

    def test_config_hash_differs_on_model(self):
        h1 = compute_config_hash("m1", 1024)
        h2 = compute_config_hash("m2", 1024)
        assert h1 != h2

    def test_config_hash_with_temperature(self):
        h1 = compute_config_hash("m", 1024, temperature=0.5)
        h2 = compute_config_hash("m", 1024, temperature=0.7)
        assert h1 != h2

    def test_config_hash_with_tools(self):
        tools = [{"function": {"name": "t1"}}, {"function": {"name": "t2"}}]
        h = compute_config_hash("m", 1024, tools=tools)
        assert len(h) == 64

    def test_prompt_hash_deterministic(self):
        h1 = compute_prompt_hash("hello world")
        h2 = compute_prompt_hash("hello world")
        assert h1 == h2

    def test_prompt_hash_differs(self):
        assert compute_prompt_hash("a") != compute_prompt_hash("b")
