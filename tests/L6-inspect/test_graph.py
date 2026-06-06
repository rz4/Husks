"""test_graph.py -- Dependency graph extraction and rendering."""

import json
from husks.report import extract_edges, render_graph


# ── Edge extraction ─────────────────────────────────────────────

class TestExtractEdges:
    def test_no_rules(self):
        nodes, edges = extract_edges({"rules": []})
        assert nodes == [] and edges == []

    def test_input_output_edge(self):
        design = {"rules": [
            {"name": "a", "kind": "action", "outputs": ["dep.txt"]},
            {"name": "b", "kind": "oracle", "outputs": ["out.txt"],
             "inputs": ["dep.txt"]},
        ]}
        nodes, edges = extract_edges(design)
        assert len(nodes) == 2
        assert ("a", "b") in edges

    def test_cond_edges(self):
        design = {"rules": [
            {"name": "ok", "kind": "commit"},
            {"name": "fail", "kind": "halt"},
            {"name": "gate", "kind": "cond", "then": "ok", "else": "fail"},
        ]}
        _, edges = extract_edges(design)
        assert ("gate", "ok") in edges
        assert ("gate", "fail") in edges

    def test_let_edge(self):
        design = {"rules": [
            {"name": "base", "kind": "oracle", "outputs": ["out.txt"]},
            {"name": "alias", "kind": "let", "bind": "base"},
        ]}
        _, edges = extract_edges(design)
        assert ("base", "alias") in edges

    def test_no_edge_without_overlap(self):
        design = {"rules": [
            {"name": "a", "kind": "action", "outputs": ["x.txt"]},
            {"name": "b", "kind": "oracle", "outputs": ["y.txt"],
             "inputs": ["z.txt"]},
        ]}
        _, edges = extract_edges(design)
        assert edges == []

    def test_trial_edges(self):
        design = {"rules": [
            {"name": "dep", "kind": "action", "outputs": ["dep.txt"]},
            {"name": "t", "kind": "trial", "outputs": ["out.txt"],
             "inputs": ["dep.txt"]},
        ]}
        _, edges = extract_edges(design)
        assert ("dep", "t") in edges


# ── Rendering formats ───────────────────────────────────────────

def _sample_design():
    return {
        "name": "demo", "fuel": 10, "target": "w",
        "rules": [
            {"name": "dep", "kind": "action", "outputs": ["dep.txt"]},
            {"name": "w", "kind": "oracle", "outputs": ["out.txt"],
             "inputs": ["dep.txt"], "fuel": 4},
        ],
    }


class TestRenderText:
    def test_basic(self):
        text = render_graph(_sample_design(), fmt="text")
        assert "demo" in text
        assert "w" in text
        assert "dep" in text
        assert "\u2500" in text  # horizontal rule

    def test_root_hash(self):
        text = render_graph(_sample_design(), fmt="text",
                            root_hash="abcdef123456789")
        assert "husk:abcdef123456" in text

    def test_no_root_hash(self):
        text = render_graph(_sample_design(), fmt="text")
        assert "husk:none" in text


class TestRenderMermaid:
    def test_basic(self):
        text = render_graph(_sample_design(), fmt="mermaid")
        assert "flowchart TD" in text
        assert "dep" in text
        assert "-->" in text


class TestRenderDot:
    def test_basic(self):
        text = render_graph(_sample_design(), fmt="dot")
        assert "digraph husks" in text
        assert "rankdir=TB" in text
        assert "->" in text


class TestRenderJson:
    def test_basic(self):
        text = render_graph(_sample_design(), fmt="json")
        data = json.loads(text)
        assert "nodes" in data and "edges" in data
        assert len(data["nodes"]) == 2
        assert any(e["from"] == "dep" and e["to"] == "w" for e in data["edges"])

    def test_node_fields(self):
        text = render_graph(_sample_design(), fmt="json")
        data = json.loads(text)
        node = next(n for n in data["nodes"] if n["name"] == "w")
        assert node["kind"] == "oracle"


class TestRenderWithSite:
    def test_overlays_states(self, tmp_site, write_manifest, write_seal):
        """When site is provided, freshness states overlay on nodes."""
        (tmp_site / "out.txt").write_text("data")
        from husks.report import file_hash
        h = file_hash(str(tmp_site / "out.txt"))
        rules = [
            {"name": "dep", "kind": "action", "outputs": ["dep.txt"]},
            {"name": "w", "kind": "oracle", "outputs": ["out.txt"]},
        ]
        write_manifest(tmp_site, rules=rules)
        write_seal(tmp_site, "w", outputs={"out.txt": h})
        # dep has no seal -> stale; w has matching seal -> fresh
        text = render_graph(
            {"name": "demo", "fuel": 10, "target": "w", "rules": rules},
            fmt="json", site=str(tmp_site),
        )
        data = json.loads(text)
        states = {n["name"]: n.get("state") for n in data["nodes"]}
        assert states["w"] == "fresh"
        assert states["dep"] in ("stale", "missing")
