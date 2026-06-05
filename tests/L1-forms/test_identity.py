"""test_identity.py -- recipe_to_cse, behavior digest, verdict identity, pred identity."""

import hashlib
import inspect

import pytest
from kernel import encode, NIL
from forms import (
    recipe_to_cse, _fn_behavior_digest, _pred_identity,
    first_valid, verdict_identity, DEFAULT_VERDICT,
)


# ── recipe_to_cse ───────────────────────────────────────────────

class TestRecipeToCse:
    def test_none_recipe(self):
        assert recipe_to_cse(None) == NIL

    def test_unknown_type_returns_nil(self):
        assert recipe_to_cse({"type": "unknown"}) == NIL

    def test_action_shell(self):
        fn = lambda S: None
        fn._husks_cmd = "echo hello"
        result = recipe_to_cse({"type": "action", "fn": fn})
        assert result == [b"action", b"echo hello"]

    def test_action_callable(self):
        def my_action(S):
            return S
        result = recipe_to_cse({"type": "action", "fn": my_action})
        assert result[0] == b"action"
        assert len(result) == 2  # no args
        assert result[1] == _fn_behavior_digest(my_action).encode()

    def test_action_callable_with_args(self):
        def my_action(S):
            return S
        result = recipe_to_cse({"type": "action", "fn": my_action, "args": (1, "x")})
        assert len(result) == 3
        assert result[2] == repr((1, "x")).encode()

    def test_oracle(self):
        result = recipe_to_cse({
            "type": "oracle", "name": "gpt", "prompt": "go",
            "tools": ["b", "a"], "fuel": 5,
        })
        assert result[0] == b"oracle"
        assert result[1] == b"gpt"
        assert result[2] == b"go"
        assert result[3] == [b"a", b"b"]  # sorted
        assert result[4] == b"5"

    def test_oracle_nil_name(self):
        result = recipe_to_cse({"type": "oracle", "prompt": "p", "tools": [], "fuel": 8})
        assert result[1] == NIL

    def test_trial(self):
        result = recipe_to_cse({
            "type": "trial", "verdict": None,
            "branches": [{"type": "action", "fn": lambda S: None}],
        })
        assert result[0] == b"trial"
        assert result[1] == b"first-valid"
        assert result[2][0] == b"action"

    def test_trial_custom_verdict(self):
        def my_verdict(results):
            return results[-1]
        result = recipe_to_cse({
            "type": "trial", "verdict": my_verdict,
            "branches": [{"type": "action", "fn": lambda S: None}],
        })
        assert result[1] == _fn_behavior_digest(my_verdict).encode()


# ── _fn_behavior_digest ─────────────────────────────────────────

class TestBehaviorDigest:
    def test_deterministic(self):
        def f(x):
            return x + 1
        assert _fn_behavior_digest(f) == _fn_behavior_digest(f)

    def test_different_bodies_different_digest(self):
        def f1(x):
            return x + 1
        def f2(x):
            return x + 2
        assert _fn_behavior_digest(f1) != _fn_behavior_digest(f2)

    def test_is_sha256_hex(self):
        def f(x):
            return x
        d = _fn_behavior_digest(f)
        assert len(d) == 64
        int(d, 16)  # valid hex

    def test_same_body_same_digest(self):
        """Same function object -> same digest."""
        def f(x):
            return x * 2
        d1 = _fn_behavior_digest(f)
        d2 = _fn_behavior_digest(f)
        assert d1 == d2


# ── verdict_identity ─────────────────────────────────────────────

class TestVerdictIdentity:
    def test_none_is_first_valid(self):
        assert verdict_identity(None) == b"first-valid"

    def test_first_valid_fn_is_first_valid(self):
        assert verdict_identity(first_valid) == b"first-valid"

    def test_default_verdict_is_first_valid(self):
        assert verdict_identity(DEFAULT_VERDICT) == b"first-valid"

    def test_string_first_valid(self):
        assert verdict_identity("first-valid") == b"first-valid"
        assert verdict_identity("first_valid") == b"first-valid"

    def test_custom_string(self):
        assert verdict_identity("my-policy") == b"my-policy"

    def test_custom_callable(self):
        def custom(results):
            return results[-1]
        result = verdict_identity(custom)
        assert result == _fn_behavior_digest(custom).encode()
        assert len(result) == 64  # hex digest


# ── _pred_identity ───────────────────────────────────────────────

class TestPredIdentity:
    def test_with_spec_attribute(self):
        def pred(site_dir):
            return True
        pred._husks_pred_spec = "file-exists:config.txt"
        assert _pred_identity(pred) == "file-exists:config.txt"

    def test_custom_callable_uses_digest(self):
        def pred(site_dir):
            return site_dir == "/tmp"
        result = _pred_identity(pred)
        assert result == _fn_behavior_digest(pred)

    def test_different_predicates_different_identity(self):
        def p1(site_dir):
            return True
        def p2(site_dir):
            return False
        assert _pred_identity(p1) != _pred_identity(p2)

    def test_same_spec_same_identity(self):
        def p1(s):
            return True
        def p2(s):
            return False
        p1._husks_pred_spec = "file-exists:x"
        p2._husks_pred_spec = "file-exists:x"
        assert _pred_identity(p1) == _pred_identity(p2)


# ── first_valid policy ──────────────────────────────────────────

class TestFirstValid:
    def test_picks_first_no_error(self):
        results = [{"error": "boom"}, {"output": "ok"}, {"output": "also ok"}]
        assert first_valid(results) == {"output": "ok"}

    def test_all_errors_returns_first(self):
        results = [{"error": "a"}, {"error": "b"}]
        assert first_valid(results) == {"error": "a"}

    def test_first_is_valid(self):
        results = [{"output": "first"}, {"output": "second"}]
        assert first_valid(results) == {"output": "first"}
