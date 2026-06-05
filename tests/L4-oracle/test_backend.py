"""test_backend.py -- Backend protocol, registry, scaffolding tests."""

import pytest
from pathlib import Path
from husks.oracle import (
    OracleBackend, RealizedCost, register, get_backend, _BACKENDS,
    build_system_prompt, site_of, readonly_roots_of, DEFAULT_TOOLS,
    run_oracle, _raise_unless_stop, _resolve_config,
)


# ── OracleBackend protocol ───────────────────────────────────────

class _StubBackend:
    name = "stub"
    def run(self, S, rule_name, recipe, outputs, config):
        for o in outputs:
            p = Path(S.get("stage", S["site"])) / o
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(f"stub:{rule_name}")
        return RealizedCost(tokens_in=10, tokens_out=20, cost_usd=0.001, fuel_steps=1)


class TestProtocol:
    def test_stub_is_oracle_backend(self):
        assert isinstance(_StubBackend(), OracleBackend)

    def test_realized_cost_is_dict(self):
        c = RealizedCost(tokens_in=1, tokens_out=2, cost_usd=0.0, fuel_steps=1)
        assert c["tokens_in"] == 1
        assert c["fuel_steps"] == 1


# ── Registry ─────────────────────────────────────────────────────

class TestRegistry:
    def test_register_and_get(self):
        stub = _StubBackend()
        register(stub)
        assert get_backend("stub") is stub
        # cleanup
        _BACKENDS.pop("stub", None)

    def test_unknown_raises(self):
        with pytest.raises(KeyError, match="unknown oracle backend"):
            get_backend("nonexistent-xyz")

    def test_register_idempotent(self):
        stub = _StubBackend()
        register(stub)
        register(stub)
        assert get_backend("stub") is stub
        _BACKENDS.pop("stub", None)


# ── Scaffolding ──────────────────────────────────────────────────

class TestScaffolding:
    def test_build_system_prompt(self):
        prompt = build_system_prompt("/site", ["out.txt", "report.md"])
        assert "oracle" in prompt.lower()
        assert "out.txt" in prompt
        assert "report.md" in prompt

    def test_site_of_uses_stage(self):
        S = {"site": "/a", "stage": "/b"}
        assert site_of(S) == Path("/b").resolve()

    def test_site_of_falls_back_to_site(self):
        S = {"site": "/a"}
        assert site_of(S) == Path("/a").resolve()

    def test_readonly_roots_of(self):
        S = {"readonly-dirs": ["/ro1", "/ro2"]}
        roots = readonly_roots_of(S)
        assert len(roots) == 2

    def test_readonly_roots_empty(self):
        assert readonly_roots_of({"readonly-dirs": []}) == set()

    def test_default_tools(self):
        assert set(DEFAULT_TOOLS) == {"read-file", "write-file", "list-dir", "tree"}


# ── _resolve_config ──────────────────────────────────────────────

class TestResolveConfig:
    def test_no_override(self):
        cfg = {"model": "a"}
        assert _resolve_config(cfg, "r1") == {"model": "a"}

    def test_with_override(self):
        cfg = {"model": "a", "per_rule": {"r1": {"model": "b"}}}
        rc = _resolve_config(cfg, "r1")
        assert rc["model"] == "b"

    def test_other_rule_no_override(self):
        cfg = {"model": "a", "per_rule": {"r1": {"model": "b"}}}
        rc = _resolve_config(cfg, "r2")
        assert rc["model"] == "a"


# ── _raise_unless_stop ───────────────────────────────────────────

class TestRaiseUnlessStop:
    def test_stop_ok(self):
        _raise_unless_stop({"type": "stop"})  # should not raise

    def test_error_raises(self):
        with pytest.raises(RuntimeError, match="oracle agent error"):
            _raise_unless_stop({"type": "error", "error": "bad"})

    def test_halt_raises(self):
        with pytest.raises(RuntimeError, match="ran out of fuel"):
            _raise_unless_stop({"type": "halt"})

    def test_kill_raises(self):
        with pytest.raises(RuntimeError, match="interrupted"):
            _raise_unless_stop({"type": "kill"})

    def test_say_raises(self):
        with pytest.raises(RuntimeError, match="text without stopping"):
            _raise_unless_stop({"type": "say", "text": "oops"})

    def test_unknown_raises(self):
        with pytest.raises(RuntimeError, match="unexpected type"):
            _raise_unless_stop({"type": "wat"})


# ── run_oracle with stub ─────────────────────────────────────────

class TestRunOracle:
    def test_run_with_registered_stub(self, tmp_store, tmp_site):
        stub = _StubBackend()
        register(stub)
        try:
            S = {**tmp_store, "oracle-backend-name": "stub", "oracle-config": {}}
            cost = run_oracle(S, "r1", {"prompt": "go", "tools": [], "fuel": 1}, ["out.txt"])
            assert cost["tokens_in"] == 10
            assert (tmp_site / "out.txt").read_text() == "stub:r1"
        finally:
            _BACKENDS.pop("stub", None)
