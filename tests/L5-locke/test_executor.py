"""test_executor.py -- Executor tests (compile_design, run, predicates)."""

import os
import pytest
from locke import (
    compile_design, _resolve_predicate, _make_touch_action,
    tokenize, parse, resolve, check, run,
)


# ── Helpers ──────────────────────────────────────────────────────

def _design_from_locke(src):
    return resolve(parse(tokenize(src)))


# ── _resolve_predicate ───────────────────────────────────────────

class TestResolvePredicate:
    def test_callable_passthrough(self):
        fn = lambda S: True
        assert _resolve_predicate(fn, {}) is fn

    def test_named_predicate(self):
        pred = lambda S: False
        assert _resolve_predicate("my-pred", {"my-pred": pred}) is pred

    def test_file_exists_builtin(self, tmp_site):
        fn = _resolve_predicate("file-exists:test.txt", {})
        assert hasattr(fn, "_husks_pred_spec")
        S = {"site": str(tmp_site)}
        assert fn(S) is False
        (tmp_site / "test.txt").write_text("hello")
        assert fn(S) is True

    def test_file_nonempty_builtin(self, tmp_site):
        fn = _resolve_predicate("file-nonempty:test.txt", {})
        S = {"site": str(tmp_site)}
        (tmp_site / "test.txt").write_text("")
        assert fn(S) is False
        (tmp_site / "test.txt").write_text("data")
        assert fn(S) is True

    def test_exit_zero_builtin(self, tmp_site):
        fn = _resolve_predicate("exit-zero:true", {})
        S = {"site": str(tmp_site)}
        assert fn(S) is True

    def test_unknown_predicate(self):
        with pytest.raises(ValueError, match="unknown predicate"):
            _resolve_predicate("nonexistent", {})


# ── _make_touch_action ───────────────────────────────────────────

class TestMakeTouchAction:
    def test_touch_creates_files(self, tmp_site):
        from seal import fresh_store
        S = fresh_store(str(tmp_site), fuel=5)
        fn = _make_touch_action(["a.txt", "b.txt"])
        fn(S)
        assert (tmp_site / "a.txt").read_text() == "ok\n"
        assert (tmp_site / "b.txt").read_text() == "ok\n"

    def test_touch_skips_existing(self, tmp_site):
        from seal import fresh_store
        S = fresh_store(str(tmp_site), fuel=5)
        (tmp_site / "a.txt").write_text("original")
        fn = _make_touch_action(["a.txt"])
        fn(S)
        assert (tmp_site / "a.txt").read_text() == "original"


# ── compile_design ───────────────────────────────────────────────

class TestCompileDesign:
    def test_basic_oracle(self):
        d = {
            "name": "test", "fuel": 10, "target": "w",
            "rules": [{"name": "w", "kind": "oracle", "outputs": ["out.txt"],
                        "prompt": "go", "fuel": 4}],
        }
        name, fuel, terminals, kwargs = compile_design(d)
        assert name == "test"
        assert fuel == 10
        assert len(terminals) == 1
        assert terminals[0]["name"] == "w"

    def test_action_with_run(self):
        d = {
            "name": "test", "fuel": 10, "target": "w",
            "rules": [{"name": "w", "kind": "action", "outputs": ["out.txt"],
                        "run": "echo ok > out.txt"}],
        }
        _, _, terminals, _ = compile_design(d)
        assert terminals[0]["name"] == "w"
        assert terminals[0]["recipe"] is not None

    def test_commit_halt(self):
        d = {
            "name": "test", "fuel": 10, "target": "ok",
            "rules": [
                {"name": "ok", "kind": "commit", "value": "done"},
                {"name": "fail", "kind": "halt", "reason": "err"},
            ],
        }
        _, _, terminals, _ = compile_design(d)
        assert terminals[0]["type"] == "commit"

    def test_let_alias(self):
        d = {
            "name": "test", "fuel": 10, "target": "alias",
            "rules": [
                {"name": "base", "kind": "oracle", "outputs": ["out.txt"],
                 "prompt": "go", "fuel": 4},
                {"name": "alias", "kind": "let", "bind": "base"},
            ],
        }
        _, _, terminals, _ = compile_design(d)
        assert terminals[0]["name"] == "base"  # alias points to same node

    def test_cond(self):
        d = {
            "name": "test", "fuel": 10, "target": "gate",
            "rules": [
                {"name": "ok", "kind": "commit", "value": "done"},
                {"name": "fail", "kind": "halt", "reason": "err"},
                {"name": "gate", "kind": "cond", "predicate": "file-exists:x",
                 "then": "ok", "else": "fail"},
            ],
        }
        _, _, terminals, _ = compile_design(d)
        assert terminals[0]["type"] == "cond"

    def test_dependency_resolution(self):
        d = {
            "name": "test", "fuel": 10, "target": "consumer",
            "rules": [
                {"name": "producer", "kind": "action", "outputs": ["dep.txt"],
                 "run": "echo dep"},
                {"name": "consumer", "kind": "oracle", "outputs": ["out.txt"],
                 "inputs": ["dep.txt"], "prompt": "go", "fuel": 4},
            ],
        }
        _, _, terminals, _ = compile_design(d)
        consumer = terminals[0]
        # Consumer should have producer as child (dependency)
        children = consumer.get("children", [])
        assert any(c.get("name") == "producer" for c in children)

    def test_trial(self):
        d = {
            "name": "test", "fuel": 10, "target": "t",
            "rules": [
                {"name": "t", "kind": "trial", "outputs": ["out.txt"],
                 "branches": [
                     {"kind": "oracle", "prompt": "try a", "fuel": 4},
                     {"kind": "oracle", "prompt": "try b", "fuel": 4},
                 ]},
            ],
        }
        _, _, terminals, _ = compile_design(d)
        assert terminals[0]["recipe"]["type"] == "trial"

    def test_kwargs_passthrough(self):
        d = {
            "name": "test", "fuel": 10, "target": "w",
            "site": "/tmp/site",
            "site_inputs": {"x": "/tmp/x"},
            "rules": [{"name": "w", "kind": "oracle", "outputs": ["out.txt"],
                        "prompt": "go", "fuel": 4}],
        }
        _, _, _, kwargs = compile_design(d)
        assert kwargs["site"] == "/tmp/site"
        assert "site_inputs" in kwargs


# ── End-to-end from .locke source ────────────────────────────────

class TestLockeEndToEnd:
    def test_parse_resolve_check(self):
        src = '''
        "e2e-test" := public
        10 := fuel
        worker := oracle [
            "Write hello to out.txt" := prompt
            4 := fuel
            [out.txt] := outputs
        ]
        '''
        d = _design_from_locke(src)
        errs = check(d)
        assert errs == []
        name, fuel, terminals, _ = compile_design(d)
        assert name == "e2e-test"
        assert fuel == 10
        assert len(terminals) == 1

    def test_multi_rule_pipeline(self):
        src = '''
        "pipeline" := public
        20 := fuel
        step1 :- action [
            "echo data > dep.txt" := run
            [dep.txt] := outputs
        ]
        step2 := oracle [
            "Process dep.txt" := prompt
            8 := fuel
            [dep.txt] := inputs
            [out.txt] := outputs
        ]
        '''
        d = _design_from_locke(src)
        errs = check(d)
        assert errs == []
