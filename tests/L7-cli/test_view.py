"""test_view.py -- View renderers, surface dispatch, navigator."""

import json
import pytest
from cli import (
    render_output, render_preamble, render_motif_tree, render_footer,
    emit_residue, emit_help, _emit_json, _diamond_stage, _footer_left, _footer_right,
    render_history_tree,
    STAGE_MAP,
)
from report import CliResidue, CliNode, CliTrace, CliOutput


# ── Fixtures ──────────────────────────────────────────────────

def _node(name="w", kind="oracle", state="sealed", **kw):
    return CliNode(name=name, kind=kind, state=state, **kw)


def _residue(command="run", status="committed", nodes=None, **kw):
    defaults = dict(design_name="test", site="/tmp/site", root="abc123",
                    fuel_budget=10, fuel_used=3, cost=0.01)
    defaults.update(kw)
    if nodes is None:
        nodes = [_node()]
    return CliResidue(command=command, nodes=nodes, status=status, **defaults)


# ── §3 View renderers ────────────────────────────────────────

class TestRenderOutput:
    def test_preamble_only(self):
        result = render_output(preamble="header")
        assert result == "header"

    def test_all_parts(self):
        result = render_output(preamble="P", trace=["T1", "T2"], footer="F")
        assert "P" in result
        assert "T1" in result
        assert "F" in result

    def test_trace_adds_separator(self):
        result = render_output(trace=["line"])
        lines = result.splitlines()
        assert any("\u2500" in l for l in lines)


class TestRenderPreamble:
    def test_contains_design_name(self):
        text = render_preamble(design_name="mydesign", display_status="sealed",
                               diamond_stage="sealed", stage_label="build")
        assert "mydesign" in text

    def test_contains_status(self):
        text = render_preamble(design_name="d", display_status="sealed",
                               diamond_stage="sealed", stage_label="build")
        assert "sealed" in text

    def test_fuel_budget(self):
        text = render_preamble(design_name="d", display_status="sealed",
                               diamond_stage="sealed", stage_label="build",
                               fuel_budget=10)
        assert "\u26a1" in text or "10" in text


class TestRenderMotifTree:
    def test_empty_nodes(self):
        assert render_motif_tree([]) == []

    def test_single_node(self):
        lines = render_motif_tree([_node()])
        assert len(lines) >= 1
        assert "w" in lines[0]

    def test_tree_with_children(self):
        parent = _node(name="w", children=["dep"])
        child = _node(name="dep", kind="action", state="cached")
        lines = render_motif_tree([parent, child])
        assert len(lines) >= 2
        text = "\n".join(lines)
        assert "w" in text
        assert "dep" in text

    def test_verbose_shows_outputs(self):
        n = _node(outputs=[CliOutput(path="out.txt", sha256="abcdef123456")])
        lines = render_motif_tree([n], verbose=True)
        text = "\n".join(lines)
        assert "out.txt" in text

    def test_verbose_shows_backend(self):
        t = CliTrace(backend="litellm", model="claude-haiku")
        n = _node(trace=t)
        lines = render_motif_tree([n], verbose=True)
        text = "\n".join(lines)
        assert "litellm" in text

    def test_unrealized_shows_fuel(self):
        n = _node(state="unrealized", fuel_budget=5)
        lines = render_motif_tree([n])
        text = "\n".join(lines)
        assert "\u26a1" in text

    def test_node_with_trace_shows_expense(self):
        """Any node with a trace shows tokens/cost, not just oracle."""
        t = CliTrace(input_tokens=500, output_tokens=200, cost_usd=0.005)
        n = _node(kind="action", trace=t, duration=2.3, cost=0.005)
        lines = render_motif_tree([n])
        text = "\n".join(lines)
        assert "500in" in text
        assert "200out" in text
        assert "$0.0050" in text

    def test_tree_dag_with_expense(self):
        """Verbose DAG shows per-node expense on each row."""
        t1 = CliTrace(input_tokens=15000, output_tokens=3000, cost_usd=0.03)
        t2 = CliTrace(input_tokens=0, output_tokens=0, cost_usd=0.0)
        parent = _node(name="validate", kind="action", children=["generate"],
                       trace=t2, duration=0.5, cost=0.0)
        child = _node(name="generate", kind="oracle",
                      trace=t1, duration=24.0, cost=0.03, fuel=3)
        lines = render_motif_tree([parent, child], verbose=True)
        text = "\n".join(lines)
        assert "validate" in text
        assert "generate" in text
        assert "15.0kin" in text
        assert "3.0kout" in text


class TestRenderHistoryTree:
    def test_empty(self):
        assert render_history_tree([], {}) == []

    def test_single_node(self):
        convergence = {"w": {"classification": "stable", "fuel_trend": "flat",
                             "prompt_trend": None, "output_stable": True}}
        lines = render_history_tree([_node()], convergence)
        text = "\n".join(lines)
        assert "w" in text
        assert "stable" in text

    def test_tree_with_trends(self):
        parent = _node(name="w", children=["dep"])
        child = _node(name="dep", kind="action", state="sealed")
        convergence = {
            "w": {"classification": "converging", "fuel_trend": "falling",
                  "prompt_trend": "flat", "output_stable": False},
            "dep": {"classification": "no-data", "fuel_trend": None,
                    "prompt_trend": None, "output_stable": None},
        }
        lines = render_history_tree([parent, child], convergence)
        text = "\n".join(lines)
        assert "w" in text
        assert "dep" in text
        assert "converging" in text
        assert "no-data" in text


class TestRenderFooter:
    def test_basic(self):
        result = render_footer(left_text="committed", right_text="0.01s")
        assert "committed" in result
        assert "0.01s" in result


# ── §4 Surface dispatch ──────────────────────────────────────

class TestStageMap:
    def test_known_commands(self):
        assert STAGE_MAP["check"] == "design"
        assert STAGE_MAP["run"] == "build"
        assert STAGE_MAP["status"] == "status"


class TestDiamondStage:
    def test_dry(self):
        r = _residue(command="check", status="dry")
        assert _diamond_stage(r) == "dry"

    def test_halted(self):
        r = _residue(status="halted")
        assert _diamond_stage(r) == "failed"

    def test_hydrating(self):
        r = _residue(status="hydrating")
        assert _diamond_stage(r) == "hydrating"

    def test_committed(self):
        r = _residue(status="committed")
        assert _diamond_stage(r) == "sealed"


class TestFooterLeft:
    def test_check(self):
        assert _footer_left(_residue(command="check")) == "dry"

    def test_run_committed(self):
        r = _residue(command="run", status="committed", root="abc1234567890")
        result = _footer_left(r)
        assert "committed" in result
        assert "abc1234567" in result

    def test_run_halted(self):
        n = _node(state="failed")
        r = _residue(command="run", status="halted", nodes=[n])
        result = _footer_left(r)
        assert "halt" in result

    def test_status_sealed(self):
        r = _residue(command="status")
        assert _footer_left(r) == "sealed"


class TestFooterRight:
    def test_check_empty(self):
        r = _residue(command="check")
        assert _footer_right(r) == ""

    def test_run_has_tokens(self):
        t = CliTrace(input_tokens=100, output_tokens=50, cost_usd=0.01)
        n = _node(trace=t, duration=1.5)
        r = _residue(command="run", nodes=[n])
        result = _footer_right(r)
        assert "100in" in result
        assert "50out" in result

    def test_status_shows_cost(self):
        t = CliTrace(input_tokens=15420, output_tokens=3143, cost_usd=0.0345)
        n = _node(trace=t, duration=24.0)
        r = _residue(command="status", cost=0.0345, fuel_used=2, nodes=[n])
        result = _footer_right(r)
        assert "$0.0345" in result
        assert "\u26a12" in result
        assert "15.4kin" in result
        assert "3.1kout" in result
        assert "24.0s" in result

    def test_status_zero_cost(self):
        r = _residue(command="status", cost=0.0, fuel_used=0)
        result = _footer_right(r)
        assert "$0.0000" in result
        assert "\u26a10" in result
        assert "0in" in result
        assert "0out" in result

    def test_status_no_fuel_budget(self):
        """Status footer shows ⚡fuel (no budget), unlike run which shows ⚡fuel/budget."""
        t = CliTrace(input_tokens=100, output_tokens=50)
        n = _node(trace=t, duration=1.0)
        r = _residue(command="status", fuel_used=3, nodes=[n])
        result = _footer_right(r)
        assert "\u26a13" in result
        assert "/" not in result.split("\u26a1")[1]  # no budget denominator


class TestEmitResidue:
    def test_quiet(self):
        assert emit_residue(_residue(), quiet=True) == ""

    def test_json_mode(self):
        r = _residue()
        text = emit_residue(r, json_mode=True)
        data = json.loads(text)
        assert data["command"] == "run"
        assert data["name"] == "test"

    def test_visual_mode(self):
        r = _residue()
        text = emit_residue(r)
        assert "test" in text
        assert "w" in text


class TestEmitJson:
    def test_basic(self):
        r = _residue()
        data = json.loads(_emit_json(r))
        assert data["status"] == "sealed"
        assert len(data["nodes"]) == 1

    def test_error_message(self):
        r = _residue(error_message="boom")
        data = json.loads(_emit_json(r))
        assert data["error"] == "boom"

    def test_node_fields(self):
        n = _node(children=["dep"], fuel=3, cost=0.01, cache=True, diagnosis="err")
        r = _residue(nodes=[n])
        data = json.loads(_emit_json(r))
        nd = data["nodes"][0]
        assert nd["children"] == ["dep"]
        assert nd["fuel"] == 3
        assert nd["cached"] is True

    def test_cached_always_present(self):
        """cached field is always emitted, even when False."""
        n = _node(cache=False)
        r = _residue(nodes=[n])
        data = json.loads(_emit_json(r))
        assert data["nodes"][0]["cached"] is False

    def test_trace_metadata(self):
        """Nodes with trace include tokens, backend, model."""
        t = CliTrace(input_tokens=500, output_tokens=200, cost_usd=0.01,
                     backend="litellm", model="claude-haiku")
        n = _node(trace=t, duration=2.5)
        r = _residue(nodes=[n])
        data = json.loads(_emit_json(r))
        nd = data["nodes"][0]
        assert nd["tokens"] == {"input": 500, "output": 200}
        assert nd["backend"] == "litellm"
        assert nd["model"] == "claude-haiku"
        assert nd["duration"] == 2.5

    def test_outputs_in_json(self):
        """Nodes with outputs include them in JSON."""
        n = _node(outputs=[CliOutput(path="out.txt", sha256="abc123")])
        r = _residue(nodes=[n])
        data = json.loads(_emit_json(r))
        nd = data["nodes"][0]
        assert nd["outputs"] == [{"path": "out.txt", "sha256": "abc123"}]


class TestEmitHelp:
    def test_contains_commands(self):
        text = emit_help("1.0")
        assert "check" in text
        assert "run" in text
        assert "status" in text
        assert "doctor" in text

    def test_contains_version(self):
        text = emit_help("1.0")
        assert "1.0" in text

    def test_exit_codes(self):
        text = emit_help("1.0")
        assert "Exit codes" in text

    def test_cache_commands(self):
        text = emit_help("1.0")
        assert "cache export" in text
        assert "cache import" in text


