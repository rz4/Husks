"""test_gamma_condense.py -- Python API level tests for gamma.condense().

Tests cover:
1. Honest deterministic declaration condenses
2. Leaky declaration rejects (undeclared input)
3. Divergent acceptance rejects (accepted ≠ cold output)
4. Missing declared output rejects (G.a: recipe doesn't produce output)
5. Manifest has gamma fields on CONDENSE
"""

import json
from pathlib import Path


def _make_design(tmp_path, *, action_cmd="echo ok > out.txt",
                 outputs=None, inputs=None, site_inputs=None,
                 name="test"):
    """Create a minimal deterministic design dict and return it."""
    if outputs is None:
        outputs = ["out.txt"]
    design = {
        "name": name,
        "fuel": 10,
        "target": "w",
        "rules": [
            {
                "name": "w",
                "kind": "action",
                "inputs": inputs or [],
                "outputs": outputs,
                "run": action_cmd,
            },
        ],
    }
    if site_inputs:
        design["site_inputs"] = site_inputs
    return design


def _make_accepted(tmp_path, content="ok\n", filename="accepted_out.txt"):
    """Write an accepted output file and return its path."""
    p = tmp_path / filename
    p.write_text(content)
    return str(p)


class TestCondenseHonest:
    """Honest deterministic declaration condenses (exact digest match)."""

    def test_deterministic_action_condenses(self, tmp_path):
        from husks.gamma import condense

        design = _make_design(tmp_path)
        # The action writes "ok\n" to out.txt.  Create accepted with same content.
        accepted_path = _make_accepted(tmp_path, content="ok\n")
        site_dir = str(tmp_path / "condense-site")

        result = condense(
            design,
            {"out.txt": accepted_path},
            site=site_dir,
            stub=True,
        )

        assert result["verdict"] == "CONDENSE"
        assert result["site"] is not None
        assert result["errors"] == []
        assert len(result["checks"]) > 0

    def test_manifest_has_gamma_fields(self, tmp_path):
        """On CONDENSE, M1 manifest has acceptance_anchor, condensed_in_flight, proposal_source."""
        from husks.gamma import condense

        design = _make_design(tmp_path)
        accepted_path = _make_accepted(tmp_path, content="ok\n")
        site_dir = str(tmp_path / "condense-site")

        result = condense(
            design,
            {"out.txt": accepted_path},
            site=site_dir,
            stub=True,
        )

        assert result["verdict"] == "CONDENSE"

        manifest_path = Path(result["site"]) / ".traces" / "build.manifest.json"
        assert manifest_path.is_file()
        manifest = json.loads(manifest_path.read_text())

        assert "acceptance_anchor" in manifest
        assert manifest["acceptance_anchor"]["out.txt"] == result["acceptance_anchor"]["out.txt"]
        assert manifest["condensed_in_flight"] is True
        assert manifest["proposal_source"] == "manual"


class TestCondenseDivergent:
    """Divergent acceptance rejects (accepted output ≠ cold output)."""

    def test_divergent_accepted_output_rejects(self, tmp_path):
        from husks.gamma import condense

        design = _make_design(tmp_path)
        # Accepted has different content than what the action produces
        accepted_path = _make_accepted(tmp_path, content="DIFFERENT CONTENT\n")
        site_dir = str(tmp_path / "condense-site")

        result = condense(
            design,
            {"out.txt": accepted_path},
            site=site_dir,
            stub=True,
        )

        assert result["verdict"] == "REJECT"
        assert any("acceptance anchor" in e for e in result["errors"])


class TestCondenseLeaky:
    """Leaky declaration rejects: recipe reads undeclared file → cold build fails or diverges."""

    def test_undeclared_input_rejects(self, tmp_path):
        """A design that reads a file not in its inputs list fails in sandbox."""
        from husks.gamma import condense

        # Create a design where the action tries to read an undeclared file.
        # The cat of a non-existent file will fail the action.
        design = _make_design(
            tmp_path,
            action_cmd="cat undeclared.txt > out.txt",
        )
        accepted_path = _make_accepted(tmp_path, content="some content\n")
        site_dir = str(tmp_path / "condense-site")

        result = condense(
            design,
            {"out.txt": accepted_path},
            site=site_dir,
            stub=True,
        )

        # Should reject: the action will fail because undeclared.txt doesn't exist
        assert result["verdict"] == "REJECT"


class TestCondenseMissingOutput:
    """Missing declared output rejects (G.a: recipe doesn't produce output)."""

    def test_missing_output_rejects(self, tmp_path):
        from husks.gamma import condense

        # Design declares out.txt but the action doesn't produce it
        design = _make_design(
            tmp_path,
            action_cmd="echo noop",  # doesn't write out.txt
            outputs=["out.txt"],
        )
        accepted_path = _make_accepted(tmp_path, content="anything\n")
        site_dir = str(tmp_path / "condense-site")

        result = condense(
            design,
            {"out.txt": accepted_path},
            site=site_dir,
            stub=True,
        )

        # Should reject: build will halt because out.txt is never produced
        assert result["verdict"] == "REJECT"


class TestCondenseInvalidDesign:
    """Invalid design is rejected immediately."""

    def test_bad_design_rejects(self, tmp_path):
        from husks.gamma import condense

        bad_design = {"name": "bad"}  # missing fuel, rules, target
        accepted_path = _make_accepted(tmp_path)

        result = condense(
            bad_design,
            {"out.txt": accepted_path},
            site=str(tmp_path / "bad-site"),
            stub=True,
        )

        assert result["verdict"] == "REJECT"
        assert any("design check" in e for e in result["errors"])


class TestCondenseAcceptedFileNotFound:
    """Accepted output file that doesn't exist is rejected."""

    def test_missing_accepted_file_rejects(self, tmp_path):
        from husks.gamma import condense

        design = _make_design(tmp_path)

        result = condense(
            design,
            {"out.txt": "/nonexistent/path/out.txt"},
            site=str(tmp_path / "bad-site"),
            stub=True,
        )

        assert result["verdict"] == "REJECT"
        assert any("not found" in e for e in result["errors"])
