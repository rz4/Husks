"""Tests for eval_node, eval_rule, eval_recipe, eval_cond, BuildTransaction."""

import pytest
from pathlib import Path

from husks.engine import (
    eval_node, eval_recipe, rule, action, cond, commit, halt,
    BuildTransaction, default_oracle_backend,
)
from husks.seal import Stop, site_path, write_text, file_exists
from conftest import _write_action


# ── eval_node dispatch ───────────────────────────────────────────

class TestEvalNode:
    def test_commit_raises_stop(self, tmp_store):
        with pytest.raises(Stop) as exc:
            eval_node(tmp_store, commit("done"))
        assert exc.value.kind == "commit"
        assert exc.value.value == "done"

    def test_halt_raises_stop(self, tmp_store):
        with pytest.raises(Stop) as exc:
            eval_node(tmp_store, halt("reason"))
        assert exc.value.kind == "halt"

    def test_unknown_type_raises(self, tmp_store):
        with pytest.raises(ValueError, match="unknown node type"):
            eval_node(tmp_store, {"type": "bogus"})


class TestEvalCond:
    def test_true_branch(self, tmp_store):
        n = cond(lambda S: True, commit("yes"), halt("no"))
        with pytest.raises(Stop) as exc:
            eval_node(tmp_store, n)
        assert exc.value.kind == "commit"

    def test_false_branch(self, tmp_store):
        n = cond(lambda S: False, commit("yes"), halt("no"))
        with pytest.raises(Stop) as exc:
            eval_node(tmp_store, n)
        assert exc.value.kind == "halt"

    def test_trace_recorded(self, tmp_store):
        n = cond(lambda S: True, commit("yes"), halt("no"))
        try:
            eval_node(tmp_store, n)
        except Stop:
            pass
        cond_events = [e for e in tmp_store["trace"] if e.get("event") == "cond"]
        assert len(cond_events) == 1
        assert cond_events[0]["result"] is True


# ── eval_rule ────────────────────────────────────────────────────

class TestEvalRule:
    def test_action_fires_and_seals(self, tmp_store):
        """First eval fires (stale), second eval is sealed (fresh)."""
        n = rule("writer", recipe=action(_write_action("out.txt", "hello")),
                 outputs=["out.txt"])
        eval_node(tmp_store, n)
        # Output written
        assert file_exists(site_path(tmp_store, "out.txt"))
        assert Path(site_path(tmp_store, "out.txt")).read_text() == "hello"
        # Check fired event
        fired = [e for e in tmp_store["trace"] if e.get("event") == "fired"]
        assert len(fired) == 1
        # Second eval should seal
        eval_node(tmp_store, n)
        sealed = [e for e in tmp_store["trace"] if e.get("event") == "sealed"]
        assert len(sealed) == 1

    def test_prerequisites_evaluated_first(self, tmp_store):
        child = rule("child", recipe=action(_write_action("dep.txt", "dep")),
                      outputs=["dep.txt"])
        parent = rule("parent", child, recipe=action(_write_action("out.txt", "result")),
                       inputs=["dep.txt"], outputs=["out.txt"])
        eval_node(tmp_store, parent)
        assert file_exists(site_path(tmp_store, "dep.txt"))
        assert file_exists(site_path(tmp_store, "out.txt"))

    def test_fuel_consumed(self, tmp_store):
        initial_fuel = tmp_store["fuel"]
        n = rule("r", recipe=action(_write_action("o.txt", "x")), outputs=["o.txt"])
        eval_node(tmp_store, n)
        assert tmp_store["fuel"] < initial_fuel


# ── BuildTransaction ─────────────────────────────────────────────

class TestBuildTransaction:
    def test_staging_and_promotion(self, tmp_store):
        """Transaction creates staging, promotes outputs to live site."""
        outputs = ["result.txt"]
        with BuildTransaction(tmp_store, outputs) as txn:
            # Write to staging
            write_text(site_path(tmp_store, "result.txt", write=True), "staged content")
            txn.validate_outputs("test", action(lambda S: None))
            txn.promote()
        # Should be in live site after promotion
        assert Path(site_path(tmp_store, "result.txt")).read_text() == "staged content"
        # Stage should be cleaned up
        assert "stage" not in tmp_store

    def test_validate_missing_output_raises(self, tmp_store):
        with BuildTransaction(tmp_store, ["missing.txt"]) as txn:
            with pytest.raises(RuntimeError, match="did not produce"):
                txn.validate_outputs("test", None)

    def test_validate_empty_oracle_output_raises(self, tmp_store):
        with BuildTransaction(tmp_store, ["empty.txt"]) as txn:
            write_text(site_path(tmp_store, "empty.txt", write=True), "")
            # Overwrite with empty
            Path(site_path(tmp_store, "empty.txt", write=True)).write_text("")
            with pytest.raises(RuntimeError, match="empty output"):
                txn.validate_outputs("test", {"type": "oracle"})

    def test_cleanup_on_error(self, tmp_store):
        """Stage directory is cleaned up even on exception."""
        try:
            with BuildTransaction(tmp_store, ["x.txt"]) as txn:
                raise ValueError("test error")
        except ValueError:
            pass
        assert "stage" not in tmp_store


# ── eval_recipe ──────────────────────────────────────────────────

class TestEvalRecipe:
    def test_none_recipe(self, tmp_store):
        result = eval_recipe(tmp_store, "r", None, [], [])
        assert result is None

    def test_unknown_recipe_type(self, tmp_store):
        with pytest.raises(ValueError, match="unknown recipe type"):
            eval_recipe(tmp_store, "r", {"type": "bogus"}, [], [])


# ── Default oracle backend ───────────────────────────────────────

class TestDefaultOracleBackend:
    def test_writes_outputs(self, tmp_store):
        recipe = {"type": "oracle", "prompt": "test prompt"}
        # Set up staging
        with BuildTransaction(tmp_store, ["out.txt"]):
            usage = default_oracle_backend(tmp_store, "test_rule", recipe, ["out.txt"])
        assert usage["backend"] == "stub"

    def test_answer_format(self, tmp_store):
        recipe = {"type": "oracle", "prompt": "Respond with ANSWER: format"}
        with BuildTransaction(tmp_store, ["out.txt"]):
            default_oracle_backend(tmp_store, "test_rule", recipe, ["out.txt"])
            content = Path(site_path(tmp_store, "out.txt", write=True)).read_text()
        assert content.startswith("ANSWER:")
