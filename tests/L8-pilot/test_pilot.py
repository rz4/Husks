"""test_pilot.py -- Tests for the Pilot session envelope.

Tests cover:
P.a  Session creation: site dir, tracer attached, status starts vapor
P.b  Explicit condense trigger (recording alone never condenses)
P.c  Multiple condensations per session, droplets accumulate
P.d  Failed condensation returns to vapor, retry works
P.e  Ratchet proposes action rules, filters to accepted outputs
"""

import pytest
from pathlib import Path


def _make_honest_session(pilot, tmp_path, *, content="ok\n",
                         cmd="echo ok > out.txt"):
    """Record events and prepare accepted output for an honest condense."""
    pilot.record({"type": "bash", "cmd": cmd,
                  "reads": [], "writes": ["out.txt"]})

    accepted = tmp_path / "accepted.txt"
    accepted.write_text(content)
    return {"out.txt": str(accepted)}


# ── P.a: session creation ────────────────────────────────────────

class TestSessionCreation:
    """Pilot creates site dir, tracer attached, status starts vapor."""

    def test_creates_site_dir(self, tmp_path):
        from husks.pilot import Pilot

        site = str(tmp_path / "my-site")
        p = Pilot(site=site, name="test")

        assert Path(p.site).is_dir()
        assert p.status == "vapor"
        assert p.droplets == []

    def test_record_forwards_to_tracer(self, tmp_path):
        from husks.pilot import Pilot

        p = Pilot(site=str(tmp_path / "site"))
        # Should not raise
        p.record({"type": "read", "path": "foo.txt"})
        p.record({"type": "bash", "cmd": "echo hi",
                  "reads": [], "writes": ["out.txt"]})

    def test_default_site_created(self):
        from husks.pilot import Pilot

        p = Pilot()
        assert Path(p.site).is_dir()


# ── P.b: explicit condense trigger ───────────────────────────────

class TestExplicitTrigger:
    """Recording events alone does NOT condense; must call condense()."""

    def test_recording_does_not_condense(self, tmp_path):
        from husks.pilot import Pilot

        p = Pilot(site=str(tmp_path / "site"))
        p.record({"type": "bash", "cmd": "echo ok > out.txt",
                  "reads": [], "writes": ["out.txt"]})

        assert p.status == "vapor"
        assert p.droplets == []

    def test_explicit_condense_works(self, tmp_path):
        from husks.pilot import Pilot

        p = Pilot(site=str(tmp_path / "site"))
        accepted = _make_honest_session(p, tmp_path)

        result = p.condense(accepted, stub=True)

        assert result["verdict"] == "CONDENSE"
        assert p.status == "condensed"
        assert len(p.droplets) == 1


# ── P.c: multiple condensations ──────────────────────────────────

class TestMultipleCondensations:
    """Two honest condenses in one session, droplets accumulate."""

    def test_two_condenses_two_droplets(self, tmp_path):
        from husks.pilot import Pilot

        p = Pilot(site=str(tmp_path / "site"))

        # First condensation: produces out1.txt
        p.record({"type": "bash", "cmd": "echo ok > out1.txt",
                  "reads": [], "writes": ["out1.txt"]})
        acc1 = tmp_path / "acc1.txt"
        acc1.write_text("ok\n")
        r1 = p.condense({"out1.txt": str(acc1)}, stub=True)
        assert r1["verdict"] == "CONDENSE"

        # Second condensation: produces out2.txt (distinct output)
        p.record({"type": "bash", "cmd": "echo ok > out2.txt",
                  "reads": [], "writes": ["out2.txt"]})
        acc2 = tmp_path / "acc2.txt"
        acc2.write_text("ok\n")
        r2 = p.condense({"out2.txt": str(acc2)}, stub=True)
        assert r2["verdict"] == "CONDENSE"

        assert len(p.droplets) == 2
        assert p.status == "condensed"

    def test_droplets_have_distinct_sites(self, tmp_path):
        from husks.pilot import Pilot

        p = Pilot(site=str(tmp_path / "site"))

        sites = []
        for i in range(2):
            fname = f"out{i}.txt"
            p.record({"type": "bash", "cmd": f"echo ok > {fname}",
                      "reads": [], "writes": [fname]})
            acc = tmp_path / f"acc{i}.txt"
            acc.write_text("ok\n")
            r = p.condense({fname: str(acc)}, stub=True)
            assert r["verdict"] == "CONDENSE"
            sites.append(r["site"])

        assert sites[0] != sites[1]
        assert "condense-1" in sites[0]
        assert "condense-2" in sites[1]


# ── P.d: failed condensation returns to vapor ────────────────────

class TestFailedCondensation:
    """Bad condense → REJECT, status still vapor, can retry."""

    def test_failed_condense_stays_vapor(self, tmp_path):
        from husks.pilot import Pilot

        p = Pilot(site=str(tmp_path / "site"))
        p.record({"type": "bash", "cmd": "echo ok > out.txt",
                  "reads": [], "writes": ["out.txt"]})

        # Accepted output doesn't match what the action produces
        bad_acc = tmp_path / "bad.txt"
        bad_acc.write_text("WRONG CONTENT\n")

        result = p.condense({"out.txt": str(bad_acc)}, stub=True)

        assert result["verdict"] == "REJECT"
        assert p.status == "vapor"
        assert p.droplets == []

    def test_retry_after_failure(self, tmp_path):
        from husks.pilot import Pilot

        p = Pilot(site=str(tmp_path / "site"))

        # First attempt: bad accepted output → REJECT
        p.record({"type": "bash", "cmd": "echo ok > out1.txt",
                  "reads": [], "writes": ["out1.txt"]})
        bad_acc = tmp_path / "bad.txt"
        bad_acc.write_text("WRONG\n")
        r1 = p.condense({"out1.txt": str(bad_acc)}, stub=True)
        assert r1["verdict"] == "REJECT"
        assert p.status == "vapor"

        # Second attempt: different output, correct content → CONDENSE
        p.record({"type": "bash", "cmd": "echo ok > out2.txt",
                  "reads": [], "writes": ["out2.txt"]})
        good_acc = tmp_path / "good.txt"
        good_acc.write_text("ok\n")
        r2 = p.condense({"out2.txt": str(good_acc)}, stub=True)
        assert r2["verdict"] == "CONDENSE"
        assert p.status == "condensed"
        assert len(p.droplets) == 1


# ── P.e: ratchet proposes actions ─────────────────────────────────

class TestRatchet:
    """Ratchet drafts action-only rules from bash events."""

    def test_ratchet_all_action_rules(self, tmp_path):
        from husks.pilot import Pilot

        p = Pilot(site=str(tmp_path / "site"))
        p.record({"type": "read", "path": "input.txt"})
        p.record({"type": "bash", "cmd": "cp input.txt output.txt",
                  "reads": ["input.txt"], "writes": ["output.txt"]})

        design = p.ratchet({"output.txt": "output.txt"})

        assert len(design["rules"]) >= 1
        for rule in design["rules"]:
            assert rule["kind"] == "action"

    def test_ratchet_filters_to_accepted(self, tmp_path):
        from husks.pilot import Pilot

        p = Pilot(site=str(tmp_path / "site"))
        p.record({"type": "bash", "cmd": "echo a > a.txt",
                  "reads": [], "writes": ["a.txt"]})
        p.record({"type": "bash", "cmd": "echo b > b.txt",
                  "reads": [], "writes": ["b.txt"]})

        # Only accept a.txt
        design = p.ratchet({"a.txt": "a.txt"})

        assert len(design["rules"]) == 1
        assert design["rules"][0]["outputs"] == ["a.txt"]
