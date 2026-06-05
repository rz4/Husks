"""test_report.py -- Report assembly, rendering, validation, and data models."""

import json
import pytest
from husks.report import (
    assemble, render_text, render_concise, render_json,
    validate_report_schema,
    CliOutput, CliTrace, CliNode, CliResidue,
    map_manifest_state, map_display_status, map_trace_state,
    compare_artifacts, read_manifest,
)


# ── Minimal report fixture ──────────────────────────────────────

def _minimal_report(**overrides):
    r = {
        "schema_version": "beta-1",
        "status": "committed",
        "root": "abc123",
        "run_id": "run-1",
        "build": "test",
        "site": "/tmp/site",
        "elapsed_s": 1.5,
        "fuel": {"start": 10, "end": 7},
        "cost": {"paid": 0.01, "reused_estimate": 0.0, "projected_estimate": 0.01},
        "delta": {"changed": [], "new": ["w"], "unchanged": []},
        "nodes": [{
            "name": "w", "kind": "oracle", "state": "fired",
            "classification": "no-data",
            "prompt_len": 42, "prompt_trend": None,
            "fuel_consumed": 3, "fuel_trend": None,
            "output_hashes": ["h1"],
            "outputs": [{"path": "out.txt", "hash": "h1"}],
            "output_changed": True,
            "cost": {"this_run": 0.01, "first_paid": None, "per_rerun": None},
            "cached": False,
            "tokens": {"input": 100, "output": 50},
            "seal": None,
            "equivalence": {},
        }],
        "oracle_calls": 1,
        "cache_hits": 0,
        "cached_nodes": [],
        "cost_tolerance": {"ratio": [0.5, 2.0]},
    }
    r.update(overrides)
    return r


# ── Report validation ───────────────────────────────────────────

class TestValidateReportSchema:
    def test_valid(self):
        ok, errs = validate_report_schema(_minimal_report())
        assert ok and errs == []

    def test_missing_field(self):
        r = _minimal_report()
        del r["status"]
        ok, errs = validate_report_schema(r)
        assert not ok
        assert any("status" in e for e in errs)

    def test_wrong_type(self):
        r = _minimal_report(elapsed_s="not a number")
        ok, errs = validate_report_schema(r)
        assert not ok

    def test_bad_schema_version(self):
        r = _minimal_report(schema_version="v99")
        ok, errs = validate_report_schema(r)
        assert not ok
        assert any("schema_version" in e for e in errs)

    def test_committed_no_root(self):
        r = _minimal_report(root=None)
        ok, errs = validate_report_schema(r)
        assert not ok
        assert any("root" in e for e in errs)

    def test_halted_no_diagnosis(self):
        r = _minimal_report(status="halted", root=None)
        ok, errs = validate_report_schema(r)
        assert not ok
        assert any("diagnosis" in e for e in errs)

    def test_halted_with_diagnosis(self):
        r = _minimal_report(
            status="halted", root=None,
            diagnosis={"error": "err", "failed_nodes": ["w"]},
        )
        ok, errs = validate_report_schema(r)
        # root check fails for committed, but status is halted now
        # root type (None) passes since (str, NoneType) is accepted
        assert ok or all("root" not in e for e in errs)

    def test_fuel_validation(self):
        r = _minimal_report(fuel={"start": "bad"})
        ok, errs = validate_report_schema(r)
        assert not ok and any("fuel" in e for e in errs)

    def test_cost_validation(self):
        r = _minimal_report(cost={"paid": "bad"})
        ok, errs = validate_report_schema(r)
        assert not ok

    def test_node_missing_field(self):
        r = _minimal_report()
        del r["nodes"][0]["kind"]
        ok, errs = validate_report_schema(r)
        assert not ok and any("kind" in e for e in errs)


# ── Report rendering ────────────────────────────────────────────

class TestRenderText:
    def test_contains_basics(self):
        text = render_text(_minimal_report())
        assert "beta-1" in text
        assert "committed" in text
        assert "abc123" in text
        assert "w" in text

    def test_diagnosis_section(self):
        r = _minimal_report(
            status="halted", root=None,
            diagnosis={"error": "timeout", "failed_nodes": ["w"]},
        )
        r["nodes"][0]["state"] = "failed"
        r["nodes"][0]["diagnosis"] = {"error": "timeout", "stale_reason": ""}
        text = render_text(r)
        assert "diagnosis" in text
        assert "timeout" in text


class TestRenderConcise:
    def test_fired_symbol(self):
        text = render_concise(_minimal_report())
        assert "\u2713" in text  # checkmark for fired
        assert "w" in text

    def test_sealed_symbol(self):
        r = _minimal_report()
        r["nodes"][0]["state"] = "sealed"
        text = render_concise(r)
        assert "\u25cf" in text  # bullet for sealed


class TestRenderJson:
    def test_valid_json(self):
        text = render_json(_minimal_report())
        data = json.loads(text)
        assert data["build"] == "test"


# ── Report assembly ─────────────────────────────────────────────

class TestAssemble:
    def test_basic(self, tmp_site, write_seal, write_history):
        store = {
            "site": str(tmp_site), "status": "committed",
            "build-root": "abc123", "run-id": "run-1", "fuel": 7,
            "usage": {"total_cost_usd": 0.01, "by_rule": {
                "w": {"cost_usd": 0.01, "input_tokens": 100, "output_tokens": 50},
            }},
        }
        events = [
            {"event": "node_done", "name": "w", "state": "fired", "elapsed": 1.0},
        ]
        design = {
            "name": "test", "fuel": 10, "target": "w",
            "rules": [{"name": "w", "kind": "oracle", "outputs": ["out.txt"],
                        "prompt": "go"}],
        }
        (tmp_site / "out.txt").write_text("result")
        write_history(tmp_site, "w", [
            {"fuel_consumed": 3, "output_hashes": ["h1"]},
        ])
        r = assemble(store, events, design, elapsed_s=1.5)
        assert r["status"] == "committed"
        assert r["build"] == "test"
        assert r["oracle_calls"] == 1
        assert len(r["nodes"]) == 1
        assert r["nodes"][0]["name"] == "w"

    def test_halted(self, tmp_site):
        store = {
            "site": str(tmp_site), "status": "halted",
            "value": "timeout", "fuel": 0,
            "usage": {},
        }
        events = [
            {"event": "node_done", "name": "w", "state": "failed"},
            {"event": "rule_halted", "rule": "w", "reason": "timeout"},
        ]
        design = {
            "name": "test", "fuel": 10, "target": "w",
            "rules": [{"name": "w", "kind": "oracle", "outputs": ["out.txt"],
                        "prompt": "go"}],
        }
        r = assemble(store, events, design)
        assert r["status"] == "halted"
        assert "diagnosis" in r
        assert r["diagnosis"]["error"] == "timeout"
        assert r["nodes"][0]["state"] == "failed"


# ── CLI data models ─────────────────────────────────────────────

class TestCliModels:
    def test_cli_output(self):
        o = CliOutput(path="out.txt", sha256="abc")
        assert o.path == "out.txt"

    def test_cli_trace(self):
        t = CliTrace(backend="litellm", cost_usd=0.01)
        assert t.backend == "litellm"
        assert t.input_tokens == 0

    def test_cli_node_defaults(self):
        n = CliNode(name="w", kind="oracle", state="sealed")
        assert n.children == []
        assert n.cache is False

    def test_cli_residue(self):
        r = CliResidue(command="status", design_name="test", status="sealed")
        assert r.fuel_budget == 0
        assert r.nodes == []


# ── State mapping ───────────────────────────────────────────────

class TestMapManifestState:
    def test_fresh(self):
        assert map_manifest_state("fresh") == "sealed"

    def test_stale(self):
        assert map_manifest_state("stale") == "stale"

    def test_missing(self):
        assert map_manifest_state("missing") == "stale"


class TestMapDisplayStatus:
    def test_committed(self):
        assert map_display_status("committed", "run") == "sealed"

    def test_halted(self):
        assert map_display_status("halted", "run") == "failed"

    def test_check_dry(self):
        assert map_display_status("dry", "check") == "checked"

    def test_passthrough(self):
        assert map_display_status("custom", "run") == "custom"


class TestMapTraceState:
    def test_fired(self):
        assert map_trace_state("fired") == "sealed"

    def test_reused(self):
        assert map_trace_state("reused") == "cached"

    def test_cached(self):
        assert map_trace_state("fired", cached=True) == "cached"

    def test_failed(self):
        assert map_trace_state("fired", failed=True) == "failed"

    def test_unrealized(self):
        assert map_trace_state("") == "unrealized"


# ── Artifact comparison ─────────────────────────────────────────

class TestCompareArtifacts:
    def test_identical(self, tmp_site, write_manifest, write_seal):
        """Same site compared to itself should be equivalent."""
        (tmp_site / "out.txt").write_text("data")
        from husks.report import file_hash
        h = file_hash(str(tmp_site / "out.txt"))
        write_manifest(tmp_site)
        write_seal(tmp_site, "w", outputs={"out.txt": h})
        result = compare_artifacts(str(tmp_site), str(tmp_site))
        assert result["equivalent"] is True

    def test_missing_manifest(self, tmp_path):
        result = compare_artifacts(str(tmp_path), str(tmp_path))
        assert result["equivalent"] is False
        assert any("missing manifest" in d for d in result["differences"])
