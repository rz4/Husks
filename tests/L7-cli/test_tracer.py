"""test_tracer.py -- Tests for the Tracer tool-stream observer.

Tests cover:
T.a  Basic tracing + multi-step pipeline
T.b  Proposal validated by condense (honest case passes, bad case fails)
T.c  Hostile tracer soundness (corrupted events → condense rejects)
T.d  Trace event data never enters sealed artifacts
+    Empty draft edge case
"""

import json
import pytest
from pathlib import Path


# ── T.a: basic tracing ──────────────────────────────────────────

class TestBasicTracing:
    """Record reads, writes, bash → draft produces valid design."""

    def test_single_action_draft(self):
        from husks.tracer import Tracer

        t = Tracer(name="simple")
        t.record({"type": "read", "path": "input.txt"})
        t.record({"type": "bash", "cmd": "cp input.txt output.txt",
                  "reads": ["input.txt"], "writes": ["output.txt"]})

        d = t.draft()

        assert d["name"] == "simple"
        assert d["fuel"] > 0
        assert d["target"] == "step1"
        assert len(d["rules"]) == 1

        rule = d["rules"][0]
        assert rule["kind"] == "action"
        assert rule["run"] == "cp input.txt output.txt"
        assert "input.txt" in rule["inputs"]
        assert "output.txt" in rule["outputs"]
        assert d["site_inputs"] == {"input.txt": "input.txt"}

    def test_write_event_tracked_as_produced(self):
        from husks.tracer import Tracer

        t = Tracer()
        t.record({"type": "write", "path": "gen.txt"})
        t.record({"type": "read", "path": "gen.txt"})

        d = t.draft()

        # gen.txt was written before read, so NOT a site_input
        assert "site_inputs" not in d or "gen.txt" not in d.get("site_inputs", {})


# ── T.a: multi-step pipeline ────────────────────────────────────

class TestMultiStepPipeline:
    """Two bash commands chained: A produces intermediate, B consumes it."""

    def test_two_step_pipeline(self):
        from husks.tracer import Tracer

        t = Tracer(name="pipeline")
        t.record({"type": "read", "path": "src.c"})
        t.record({"type": "bash", "cmd": "gcc -c src.c -o src.o",
                  "reads": ["src.c"], "writes": ["src.o"]})
        t.record({"type": "bash", "cmd": "gcc src.o -o prog",
                  "reads": ["src.o"], "writes": ["prog"]})

        d = t.draft()

        assert len(d["rules"]) == 2
        assert d["target"] == "step2"  # last producing rule

        # First rule: src.c → src.o
        r1 = d["rules"][0]
        assert "src.c" in r1["inputs"]
        assert "src.o" in r1["outputs"]

        # Second rule: src.o → prog (src.o produced by prior rule, not site_input)
        r2 = d["rules"][1]
        assert "src.o" in r2["inputs"]
        assert "prog" in r2["outputs"]

        # Only src.c is a site_input
        assert d["site_inputs"] == {"src.c": "src.c"}

    def test_accepted_outputs_filter(self):
        """accepted_outputs prunes rules to only contributing ones."""
        from husks.tracer import Tracer

        t = Tracer(name="filter")
        t.record({"type": "read", "path": "a.txt"})
        t.record({"type": "bash", "cmd": "cp a.txt b.txt",
                  "reads": ["a.txt"], "writes": ["b.txt"]})
        t.record({"type": "read", "path": "x.txt"})
        t.record({"type": "bash", "cmd": "cp x.txt y.txt",
                  "reads": ["x.txt"], "writes": ["y.txt"]})

        d = t.draft(accepted_outputs=["b.txt"])

        # Only the rule producing b.txt should remain
        assert len(d["rules"]) == 1
        assert d["rules"][0]["outputs"] == ["b.txt"]
        assert d["site_inputs"] == {"a.txt": "a.txt"}


# ── T.b: proposal validated by condense ─────────────────────────

class TestProposalValidatedByCondense:
    """Draft a design, run condense: honest passes, bad rejects."""

    def test_honest_draft_condenses(self, tmp_path):
        from husks.tracer import Tracer
        from husks.gamma import condense

        # Create a real site_input file
        src = tmp_path / "src"
        src.mkdir()
        (src / "data.txt").write_text("hello\n")

        t = Tracer(name="honest")
        t.record({"type": "read", "path": "data.txt"})
        t.record({"type": "bash", "cmd": "cat data.txt > out.txt",
                  "reads": ["data.txt"], "writes": ["out.txt"]})

        d = t.draft()

        # Fixup site_inputs to point to real file
        d["site_inputs"] = {"data.txt": str(src / "data.txt")}
        d["_source_path"] = str(src / "fake.json")

        # Create accepted output matching what the action would produce
        accepted = tmp_path / "accepted.txt"
        accepted.write_text("hello\n")

        result = condense(
            d,
            {"out.txt": str(accepted)},
            site=str(tmp_path / "condense"),
            stub=True,
        )

        assert result["verdict"] == "CONDENSE"

    def test_bad_draft_rejects(self, tmp_path):
        """Draft with wrong command → condense rejects (output diverges)."""
        from husks.tracer import Tracer
        from husks.gamma import condense

        t = Tracer(name="bad")
        t.record({"type": "bash", "cmd": "echo wrong > out.txt",
                  "reads": [], "writes": ["out.txt"]})

        d = t.draft()

        # Accepted output has different content than what the action produces
        accepted = tmp_path / "accepted.txt"
        accepted.write_text("correct\n")

        result = condense(
            d,
            {"out.txt": str(accepted)},
            site=str(tmp_path / "condense"),
            stub=True,
        )

        assert result["verdict"] == "REJECT"


# ── T.c: hostile tracer soundness ───────────────────────────────

class TestHostileTracerSoundness:
    """Corrupted/lying events → condense rejects because cold build diverges."""

    def test_phantom_dependency_rejects(self, tmp_path):
        """Tracer claims a read that the recipe doesn't actually use.
        The draft's site_inputs reference a file, but the action doesn't
        read it -- cold build may still pass, but if the action's actual
        behavior diverges from accepted output, condense rejects."""
        from husks.tracer import Tracer
        from husks.gamma import condense

        t = Tracer(name="hostile")
        # Lie: claim we read secret.txt, but the command doesn't use it
        t.record({"type": "read", "path": "secret.txt"})
        t.record({"type": "bash", "cmd": "echo fabricated > out.txt",
                  "reads": ["secret.txt"], "writes": ["out.txt"]})

        d = t.draft()

        # Provide a site_input for the phantom dependency
        src = tmp_path / "src"
        src.mkdir()
        (src / "secret.txt").write_text("irrelevant\n")
        d["site_inputs"] = {"secret.txt": str(src / "secret.txt")}
        d["_source_path"] = str(src / "fake.json")

        # Accepted output doesn't match what the action actually produces
        accepted = tmp_path / "accepted.txt"
        accepted.write_text("the real answer\n")

        result = condense(
            d,
            {"out.txt": str(accepted)},
            site=str(tmp_path / "condense"),
            stub=True,
        )

        # Condense rejects because cold build output ≠ accepted
        assert result["verdict"] == "REJECT"

    def test_omitted_dependency_detected(self, tmp_path):
        """Tracer omits a real dependency. The action tries to read it
        but it doesn't exist in the sandbox → cold build fails → reject."""
        from husks.tracer import Tracer
        from husks.gamma import condense

        t = Tracer(name="hostile-omit")
        # Don't record the read of needed.txt -- omit the dependency
        t.record({"type": "bash", "cmd": "cat needed.txt > out.txt",
                  "reads": [], "writes": ["out.txt"]})

        d = t.draft()

        accepted = tmp_path / "accepted.txt"
        accepted.write_text("some content\n")

        result = condense(
            d,
            {"out.txt": str(accepted)},
            site=str(tmp_path / "condense"),
            stub=True,
        )

        # Cold build fails (needed.txt doesn't exist) → reject
        assert result["verdict"] == "REJECT"


# ── T.d: trace never enters seal ────────────────────────────────

class TestTraceNeverInSeal:
    """No event data (command strings, paths from events) leaks into seal."""

    def test_no_event_data_in_manifest(self, tmp_path):
        from husks.tracer import Tracer
        from husks.gamma import condense

        secret_cmd = "echo __TRACER_SECRET_MARKER__ > out.txt"
        t = Tracer(name="sealed")
        t.record({"type": "bash", "cmd": secret_cmd,
                  "reads": [], "writes": ["out.txt"]})

        d = t.draft()

        accepted = tmp_path / "accepted.txt"
        accepted.write_text("__TRACER_SECRET_MARKER__\n")

        result = condense(
            d,
            {"out.txt": str(accepted)},
            site=str(tmp_path / "condense"),
            stub=True,
        )

        assert result["verdict"] == "CONDENSE"
        site = result["site"]

        # Check that the raw event list / tracer internals don't appear
        # in any .traces metadata files
        traces_dir = Path(site) / ".traces"
        if traces_dir.is_dir():
            for fpath in traces_dir.rglob("*"):
                if fpath.is_file():
                    content = fpath.read_text(errors="replace")
                    # The marker in output content is fine (it's the
                    # actual build output). But no "tracer" or event
                    # metadata should be present.
                    assert "TRACER_SECRET_MARKER" not in content or \
                        fpath.name.endswith(".manifest.json") is False or \
                        "tracer" not in content.lower(), \
                        f"tracer event data leaked into {fpath}"

        # Specifically: the manifest should not contain raw event dicts
        manifest_path = Path(site) / ".traces" / "build.manifest.json"
        if manifest_path.is_file():
            manifest = json.loads(manifest_path.read_text())
            manifest_str = json.dumps(manifest)
            # No trace event type markers in manifest
            assert '"type": "bash"' not in manifest_str
            assert '"type": "read"' not in manifest_str
            assert '"type": "write"' not in manifest_str


# ── Empty draft ─────────────────────────────────────────────────

class TestEmptyDraft:
    """Empty tracer produces a minimal design."""

    def test_no_events_produces_empty_design(self):
        from husks.tracer import Tracer

        t = Tracer(name="empty")
        d = t.draft()

        assert d["name"] == "empty"
        assert d["rules"] == []
        assert d["target"] == ""

    def test_invalid_event_type_raises(self):
        from husks.tracer import Tracer

        t = Tracer()
        with pytest.raises(ValueError, match="unknown event type"):
            t.record({"type": "invalid"})

    def test_missing_type_raises(self):
        from husks.tracer import Tracer

        t = Tracer()
        with pytest.raises(ValueError, match="must have a 'type' field"):
            t.record({"path": "foo.txt"})
