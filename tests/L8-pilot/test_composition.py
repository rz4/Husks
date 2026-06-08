"""test_composition.py -- Tests for Tier 4 composition (inter-husk DAG).

Tests cover:
D.a  Inter-husk DAG: upstream parameter on condense()
D.b  Evaporate: discard transcript, persist replayable graph
D.c  Cold topological replay from condensate alone
"""

from pathlib import Path


def _make_action_session(pilot, *, cmd, reads, writes):
    """Record a single bash event for an action rule."""
    pilot.record({"type": "bash", "cmd": cmd,
                  "reads": reads, "writes": writes})


# ── D.a: inter-husk DAG ─────────────────────────────────────────

class TestInterHuskDAG:
    """A produces out_a.txt, B declares it as input via upstream."""

    def test_two_husk_chain(self, tmp_path):
        """A produces out_a.txt, B consumes it via upstream, both CONDENSE."""
        from husks.pilot import Pilot

        p = Pilot(site=str(tmp_path / "site"))

        # Husk A: produces out_a.txt
        _make_action_session(p, cmd="echo hello > out_a.txt",
                             reads=[], writes=["out_a.txt"])
        acc_a = tmp_path / "acc_a.txt"
        acc_a.write_text("hello\n")
        r_a = p.condense({"out_a.txt": str(acc_a)}, stub=True)
        assert r_a["verdict"] == "CONDENSE"

        # Husk B: reads out_a.txt (from A's output), produces out_b.txt
        _make_action_session(p, cmd="cp out_a.txt out_b.txt",
                             reads=["out_a.txt"], writes=["out_b.txt"])
        acc_b = tmp_path / "acc_b.txt"
        acc_b.write_text("hello\n")
        r_b = p.condense(
            {"out_b.txt": str(acc_b)},
            stub=True,
            upstream={"out_a.txt": (0, "out_a.txt")},
        )
        assert r_b["verdict"] == "CONDENSE"
        assert len(p.droplets) == 2

    def test_upstream_resolves_to_correct_file(self, tmp_path):
        """B's design site_inputs points to A's M1 output path."""
        from husks.pilot import Pilot

        p = Pilot(site=str(tmp_path / "site"))

        # Husk A
        _make_action_session(p, cmd="echo hello > out_a.txt",
                             reads=[], writes=["out_a.txt"])
        acc_a = tmp_path / "acc_a.txt"
        acc_a.write_text("hello\n")
        r_a = p.condense({"out_a.txt": str(acc_a)}, stub=True)
        assert r_a["verdict"] == "CONDENSE"

        a_site = r_a["site"]  # M1 dir for husk A

        # Husk B with upstream
        _make_action_session(p, cmd="cp out_a.txt out_b.txt",
                             reads=["out_a.txt"], writes=["out_b.txt"])
        acc_b = tmp_path / "acc_b.txt"
        acc_b.write_text("hello\n")

        # Check the droplet's stored design has the upstream reference
        r_b = p.condense(
            {"out_b.txt": str(acc_b)},
            stub=True,
            upstream={"out_a.txt": (0, "out_a.txt")},
        )
        assert r_b["verdict"] == "CONDENSE"

        # The stored droplet's design should have site_inputs pointing to A's M1
        b_droplet = p.droplets[1]
        b_design = b_droplet["design"]
        assert "out_a.txt" in b_design["site_inputs"]
        assert b_design["site_inputs"]["out_a.txt"] == str(
            Path(a_site) / "out_a.txt"
        )


# ── D.b: evaporate ──────────────────────────────────────────────

class TestEvaporate:
    """Evaporate clears transcript and returns condensate graph."""

    def test_evaporate_clears_transcript(self, tmp_path):
        """After evaporate, tracer has no events."""
        from husks.pilot import Pilot

        p = Pilot(site=str(tmp_path / "site"))

        _make_action_session(p, cmd="echo hello > out.txt",
                             reads=[], writes=["out.txt"])
        acc = tmp_path / "acc.txt"
        acc.write_text("hello\n")
        r = p.condense({"out.txt": str(acc)}, stub=True)
        assert r["verdict"] == "CONDENSE"

        # Tracer has events before evaporate
        assert len(p._tracer._events) > 0

        condensate = p.evaporate()

        # Transcript discarded
        assert p._tracer._events == []
        # Condensate returned
        assert "nodes" in condensate
        assert "edges" in condensate

    def test_condensate_structure(self, tmp_path):
        """Nodes have design/accepted_outputs/site, edges have full fields."""
        from husks.pilot import Pilot

        p = Pilot(site=str(tmp_path / "site"))

        # Two-husk chain
        _make_action_session(p, cmd="echo hello > out_a.txt",
                             reads=[], writes=["out_a.txt"])
        acc_a = tmp_path / "acc_a.txt"
        acc_a.write_text("hello\n")
        p.condense({"out_a.txt": str(acc_a)}, stub=True)

        _make_action_session(p, cmd="cp out_a.txt out_b.txt",
                             reads=["out_a.txt"], writes=["out_b.txt"])
        acc_b = tmp_path / "acc_b.txt"
        acc_b.write_text("hello\n")
        p.condense(
            {"out_b.txt": str(acc_b)},
            stub=True,
            upstream={"out_a.txt": (0, "out_a.txt")},
        )

        condensate = p.evaporate()

        # Nodes
        assert len(condensate["nodes"]) == 2
        for node in condensate["nodes"]:
            assert "design" in node
            assert "accepted_outputs" in node
            assert "site" in node

        # Edges
        assert len(condensate["edges"]) == 1
        edge = condensate["edges"][0]
        assert edge["from_node"] == 0
        assert edge["from_output"] == "out_a.txt"
        assert edge["to_node"] == 1
        assert edge["to_input"] == "out_a.txt"

        # accepted_outputs in condensate point to M1 cold paths
        node_a = condensate["nodes"][0]
        assert node_a["accepted_outputs"]["out_a.txt"] == str(
            Path(node_a["site"]) / "out_a.txt"
        )


# ── D.c: cold replay ────────────────────────────────────────────

class TestColdReplay:
    """Cold topological replay from condensate alone."""

    def _build_two_husk_condensate(self, tmp_path):
        """Helper: build a two-husk chain and evaporate."""
        from husks.pilot import Pilot

        p = Pilot(site=str(tmp_path / "site"))

        _make_action_session(p, cmd="echo hello > out_a.txt",
                             reads=[], writes=["out_a.txt"])
        acc_a = tmp_path / "acc_a.txt"
        acc_a.write_text("hello\n")
        r_a = p.condense({"out_a.txt": str(acc_a)}, stub=True)

        _make_action_session(p, cmd="cp out_a.txt out_b.txt",
                             reads=["out_a.txt"], writes=["out_b.txt"])
        acc_b = tmp_path / "acc_b.txt"
        acc_b.write_text("hello\n")
        r_b = p.condense(
            {"out_b.txt": str(acc_b)},
            stub=True,
            upstream={"out_a.txt": (0, "out_a.txt")},
        )

        condensate = p.evaporate()
        return condensate, [r_a, r_b]

    def test_cold_replay_succeeds(self, tmp_path):
        """Evaporate -> replay from condensate alone, all CONDENSE."""
        from husks.pilot import Pilot

        condensate, _ = self._build_two_husk_condensate(tmp_path)

        replay_site = str(tmp_path / "replay")
        results = Pilot.replay(condensate, site=replay_site, stub=True)

        assert len(results) == 2
        for r in results:
            assert r["verdict"] == "CONDENSE"

    def test_replay_reproduces_every_droplet(self, tmp_path):
        """Each replay result matches the original acceptance anchor."""
        from husks.pilot import Pilot

        condensate, originals = self._build_two_husk_condensate(tmp_path)

        results = Pilot.replay(
            condensate, site=str(tmp_path / "replay"), stub=True,
        )

        assert len(results) == len(originals)
        for replay_r, orig_r in zip(results, originals):
            assert replay_r["verdict"] == "CONDENSE"
            assert replay_r["acceptance_anchor"] == orig_r["acceptance_anchor"]
