"""Tests for node constructors: rule, action, oracle, trial, cond, commit, halt."""

import pytest

from husks.engine import rule, action, oracle, trial, cond, commit, halt, _ACTION_ARG_TYPES


class TestRule:
    def test_positional_name(self):
        n = rule("myrule", outputs=["out.txt"])
        assert n["type"] == "rule"
        assert n["name"] == "myrule"

    def test_keyword_name(self):
        n = rule(name="myrule")
        assert n["name"] == "myrule"

    def test_missing_name(self):
        with pytest.raises(TypeError, match="missing required"):
            rule()

    def test_duplicate_name(self):
        with pytest.raises(TypeError, match="multiple values"):
            rule("a", name="b")

    def test_children(self):
        child = rule("child")
        n = rule("parent", child)
        assert len(n["children"]) == 1
        assert n["children"][0]["name"] == "child"

    def test_run_creates_action(self):
        n = rule(name="gate", run="echo hi", outputs=["out.txt"])
        assert n["recipe"]["type"] == "action"
        assert n["recipe"]["cmd"] == "echo hi"

    def test_run_and_recipe_conflict(self):
        def noop(S): pass
        with pytest.raises(TypeError, match="cannot have both"):
            rule(name="bad", run="cmd", recipe=action(noop))

    def test_unexpected_arg(self):
        with pytest.raises(TypeError, match="unexpected"):
            rule(42)

    def test_defaults(self):
        n = rule("r")
        assert n["inputs"] == []
        assert n["outputs"] == []
        assert n["children"] == []
        assert n["recipe"] is None


class TestAction:
    def test_basic(self):
        def fn(S): pass
        r = action(fn)
        assert r["type"] == "action"
        assert r["fn"] is fn
        assert r["args"] == ()

    def test_with_args(self):
        def fn(S, x, y): pass
        r = action(fn, "hello", 42)
        assert r["args"] == ("hello", 42)

    def test_rejects_bad_arg_type(self):
        def fn(S, x): pass
        with pytest.raises(TypeError, match="action\\(\\) arg 1"):
            action(fn, [1, 2, 3])

    def test_allowed_arg_types(self):
        def fn(S, *args): pass
        # Should not raise
        r = action(fn, "s", 1, 2.0, True, b"bytes", None)
        assert len(r["args"]) == 6


class TestOracle:
    def test_basic(self):
        r = oracle(name="gen", prompt="write code", tools=["read"], fuel=4)
        assert r["type"] == "oracle"
        assert r["name"] == "gen"
        assert r["prompt"] == "write code"
        assert r["tools"] == ["read"]
        assert r["fuel"] == 4

    def test_defaults(self):
        r = oracle()
        assert r["name"] is None
        assert r["prompt"] == ""
        assert r["tools"] == []
        assert r["fuel"] == 8


class TestTrial:
    def test_basic(self):
        b1 = oracle(name="b1", prompt="p1")
        b2 = oracle(name="b2", prompt="p2")
        r = trial(b1, b2)
        assert r["type"] == "trial"
        assert len(r["branches"]) == 2
        assert r["verdict"] is None

    def test_custom_verdict(self):
        def my_verdict(results): return results[0]
        b1 = oracle(name="b1")
        r = trial(b1, verdict=my_verdict)
        assert r["verdict"] is my_verdict


class TestCond:
    def test_basic(self):
        then = commit("yes")
        else_ = halt("no")
        pred = lambda S: True
        n = cond(pred, then, else_)
        assert n["type"] == "cond"
        assert n["predicate"] is pred
        assert n["then"] is then
        assert n["else"] is else_


class TestCommitHalt:
    def test_commit(self):
        n = commit("ok")
        assert n["type"] == "commit"
        assert n["value"] == "ok"

    def test_halt(self):
        n = halt("fail")
        assert n["type"] == "halt"
        assert n["reason"] == "fail"
