"""Tests for seal write/read, freshness, history, trial reports, manifests."""

import json
from pathlib import Path

import pytest

from seal import (
    write_seal, read_seal, seal_file, freshness_check,
    clear_fired_seals, output_hashes, compute_cse_seal,
    history_file, append_history,
    write_trial_report, write_build_manifest,
    write_text, site_path,
)


# ── Helpers ──────────────────────────────────────────────────────

def _action_recipe():
    """Minimal action recipe for testing."""
    def noop(S): pass
    noop._husks_cmd = "test-noop"
    return {"type": "action", "fn": noop}


def _setup_rule(S, inputs=("input.txt",), outputs=("output.txt",), recipe=None):
    """Create input/output files and write a seal."""
    recipe = recipe or _action_recipe()
    for name in inputs:
        write_text(site_path(S, name), f"content of {name}")
    for name in outputs:
        write_text(site_path(S, name), f"output of {name}")
    return list(inputs), list(outputs), recipe


# ── Seal round-trip ──────────────────────────────────────────────

class TestSealIO:
    def test_write_read_round_trip(self, tmp_store):
        inputs, outputs, recipe = _setup_rule(tmp_store)
        write_seal(tmp_store, "myrule", inputs, recipe, outputs)
        data = read_seal(tmp_store, "myrule")
        assert data is not None
        assert data["v"] == 1
        assert "seal" in data
        assert "recipe_digest" in data
        assert "inputs" in data
        assert "outputs" in data

    def test_read_seal_missing(self, tmp_store):
        assert read_seal(tmp_store, "nonexistent") is None

    def test_read_seal_corrupt(self, tmp_store):
        """Corrupt seal file returns None."""
        sp = seal_file(tmp_store, "bad")
        write_text(sp, "not json{{{")
        assert read_seal(tmp_store, "bad") is None

    def test_read_seal_missing_version(self, tmp_store):
        """Seal without 'v' field returns None."""
        sp = seal_file(tmp_store, "nov")
        write_text(sp, json.dumps({"seal": "abc"}))
        assert read_seal(tmp_store, "nov") is None

    def test_seal_file_path(self, tmp_store):
        p = seal_file(tmp_store, "myrule")
        assert ".traces/myrule.seal" in p

    def test_compute_cse_seal_deterministic(self, tmp_store):
        inputs, outputs, recipe = _setup_rule(tmp_store)
        s1 = compute_cse_seal(tmp_store, inputs, recipe)
        s2 = compute_cse_seal(tmp_store, inputs, recipe)
        assert s1 == s2
        assert len(s1) == 64  # hex sha256


# ── Freshness ────────────────────────────────────────────────────

class TestFreshness:
    def test_fresh_returns_none(self, tmp_store):
        inputs, outputs, recipe = _setup_rule(tmp_store)
        write_seal(tmp_store, "r", inputs, recipe, outputs)
        assert freshness_check(tmp_store, "r", inputs, outputs, recipe) is None

    def test_missing_output(self, tmp_store):
        inputs, outputs, recipe = _setup_rule(tmp_store)
        write_seal(tmp_store, "r", inputs, recipe, outputs)
        # Remove an output
        Path(site_path(tmp_store, "output.txt")).unlink()
        reason = freshness_check(tmp_store, "r", inputs, outputs, recipe)
        assert reason is not None
        assert "missing" in reason

    def test_no_prior_seal(self, tmp_store):
        inputs, outputs, recipe = _setup_rule(tmp_store)
        reason = freshness_check(tmp_store, "r", inputs, outputs, recipe)
        assert reason == "no prior build"

    def test_recipe_changed(self, tmp_store):
        inputs, outputs, recipe = _setup_rule(tmp_store)
        write_seal(tmp_store, "r", inputs, recipe, outputs)
        # Change recipe
        def other(S): pass
        other._husks_cmd = "different-cmd"
        new_recipe = {"type": "action", "fn": other}
        reason = freshness_check(tmp_store, "r", inputs, outputs, new_recipe)
        assert reason is not None
        assert "recipe changed" in reason

    def test_input_changed(self, tmp_store):
        inputs, outputs, recipe = _setup_rule(tmp_store)
        write_seal(tmp_store, "r", inputs, recipe, outputs)
        # Modify input content
        write_text(site_path(tmp_store, "input.txt"), "modified content")
        reason = freshness_check(tmp_store, "r", inputs, outputs, recipe)
        assert reason is not None
        assert "changed" in reason

    def test_output_tampered(self, tmp_store):
        inputs, outputs, recipe = _setup_rule(tmp_store)
        write_seal(tmp_store, "r", inputs, recipe, outputs)
        # Tamper with output without changing inputs/recipe
        write_text(site_path(tmp_store, "output.txt"), "tampered content")
        reason = freshness_check(tmp_store, "r", inputs, outputs, recipe)
        assert reason is not None
        assert "tampered" in reason


# ── Clear fired seals ────────────────────────────────────────────

class TestClearFiredSeals:
    def test_removes_fired_only(self, tmp_store):
        inputs, outputs, recipe = _setup_rule(tmp_store)
        # Write seals for two rules
        write_seal(tmp_store, "fired_rule", inputs, recipe, outputs)
        write_seal(tmp_store, "kept_rule", inputs, recipe, outputs)
        # Mark one as fired
        tmp_store["trace"].append({"event": "fired", "rule": "fired_rule"})
        removed = clear_fired_seals(tmp_store)
        assert removed == 1
        assert read_seal(tmp_store, "fired_rule") is None
        assert read_seal(tmp_store, "kept_rule") is not None

    def test_no_fired_returns_zero(self, tmp_store):
        assert clear_fired_seals(tmp_store) == 0


# ── Output hashes ────────────────────────────────────────────────

class TestOutputHashes:
    def test_returns_hex_strings(self, tmp_store):
        write_text(site_path(tmp_store, "a.txt"), "aaa")
        write_text(site_path(tmp_store, "b.txt"), "bbb")
        hashes = output_hashes(tmp_store, ["a.txt", "b.txt"])
        assert len(hashes) == 2
        assert all(len(h) == 64 for h in hashes)
        assert hashes[0] != hashes[1]


# ── History ──────────────────────────────────────────────────────

class TestHistory:
    def test_append_creates_jsonl(self, tmp_store):
        inputs, outputs, recipe = _setup_rule(tmp_store)
        append_history(tmp_store, "r", recipe, outputs)
        hp = history_file(tmp_store, "r")
        lines = Path(hp).read_text().strip().split("\n")
        assert len(lines) == 1
        record = json.loads(lines[0])
        assert record["run_id"] == tmp_store["run-id"]
        assert "ts" in record
        assert record["cached"] is False

    def test_append_multiple(self, tmp_store):
        inputs, outputs, recipe = _setup_rule(tmp_store)
        append_history(tmp_store, "r", recipe, outputs)
        append_history(tmp_store, "r", recipe, outputs, cached=True)
        hp = history_file(tmp_store, "r")
        lines = Path(hp).read_text().strip().split("\n")
        assert len(lines) == 2
        assert json.loads(lines[1])["cached"] is True

    def test_traced_reads_explicit(self, tmp_store):
        """traced_reads is passed explicitly, not from global state."""
        inputs, outputs, recipe = _setup_rule(tmp_store)
        append_history(tmp_store, "r", recipe, outputs, traced_reads=["a.txt", "b.txt"])
        hp = history_file(tmp_store, "r")
        record = json.loads(Path(hp).read_text().strip())
        assert record["traced_reads"] == ["a.txt", "b.txt"]

    def test_oracle_prompt_length(self, tmp_store):
        inputs, outputs, _ = _setup_rule(tmp_store)
        oracle_recipe = {"type": "oracle", "prompt": "hello world", "name": "test"}
        append_history(tmp_store, "r", oracle_recipe, outputs)
        hp = history_file(tmp_store, "r")
        record = json.loads(Path(hp).read_text().strip())
        assert record["prompt_length"] == 11

    def test_history_file_path(self, tmp_store):
        p = history_file(tmp_store, "myrule")
        assert ".traces/myrule.history.jsonl" in p


# ── Trial report ─────────────────────────────────────────────────

class TestTrialReport:
    def test_writes_json(self, tmp_store):
        results = [
            {"name": "b1", "elapsed": 1.5, "cost_usd": 0.01, "outputs": {"out.txt": "content1"}},
            {"name": "b2", "elapsed": 2.0, "error": "fail", "outputs": {}},
        ]
        branches_ir = [
            {"name": "b1", "type": "oracle"},
            {"name": "b2", "type": "oracle"},
        ]
        write_trial_report(tmp_store, "trial_rule", "b1", results, {"b1": 0.9}, branches_ir, ["out.txt"])
        p = site_path(tmp_store, ".traces/trial_rule.trial.json")
        report = json.loads(Path(p).read_text())
        assert report["schema"] == "husks.trial.v1"
        assert report["winner"] == "b1"
        assert len(report["branches"]) == 2
        assert report["branches"][0]["selected"] is True
        assert report["branches"][1]["selected"] is False
        assert report["branches"][0]["score"] == 0.9
        assert report["branches"][1].get("error") == "fail"


# ── Build manifest ───────────────────────────────────────────────

class TestBuildManifest:
    def test_writes_manifest(self, tmp_store):
        nodes = (
            {
                "type": "rule",
                "name": "compile",
                "recipe": {"type": "action"},
                "inputs": ["src.txt"],
                "outputs": ["out.txt"],
                "children": [],
            },
        )
        write_build_manifest(tmp_store, "test-build", nodes, design_source="test.json")
        p = site_path(tmp_store, ".traces/build.manifest.json")
        manifest = json.loads(Path(p).read_text())
        assert manifest["schema"] == "husks.build.manifest.v1"
        assert manifest["name"] == "test-build"
        assert manifest["status"] == "running"
        assert len(manifest["rules"]) == 1
        assert manifest["rules"][0]["name"] == "compile"
        assert manifest["design_source"] == "test.json"

    def test_cond_node(self, tmp_store):
        """Manifest handles cond nodes by collecting rules from both branches."""
        nodes = (
            {
                "type": "cond",
                "then": {
                    "type": "rule", "name": "a",
                    "recipe": {"type": "action"}, "inputs": [], "outputs": ["a.txt"], "children": [],
                },
                "else": {
                    "type": "rule", "name": "b",
                    "recipe": {"type": "action"}, "inputs": [], "outputs": ["b.txt"], "children": [],
                },
            },
        )
        write_build_manifest(tmp_store, "cond-build", nodes)
        p = site_path(tmp_store, ".traces/build.manifest.json")
        manifest = json.loads(Path(p).read_text())
        names = [r["name"] for r in manifest["rules"]]
        assert "a" in names
        assert "b" in names
