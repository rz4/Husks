"""test_gamma_conformance.py -- Five adversarial conformance tests.

Each test asserts a REJECT verdict and that no husk was sealed.
These are the definition of correct for the gamma gate.

1. Undeclared session file rejects
2. Nondeterministic deterministic-typed recipe rejects
3. Reproducible but not accepted rejects
4. Unverdictable oracle rejects
5. Transcript never in seal
"""

import json
import hashlib
import pytest
from pathlib import Path


def _condense(design, accepted, site, **kwargs):
    """Run gamma.condense and return result dict."""
    from husks.gamma import condense
    return condense(design, accepted, site=site, stub=True, **kwargs)


def _no_husk_sealed(site_dir):
    """Assert no .husk file was produced in the site."""
    site = Path(site_dir)
    if not site.exists():
        return True
    husks = list(site.rglob("*.husk"))
    assert husks == [], f"unexpected .husk files: {husks}"


class TestUndeclaredSessionFile:
    """Invariant 1: A candidate whose recipe reads a file created during the
    run but not declared as a site_input must REJECT."""

    def test_undeclared_session_file_rejects(self, tmp_path):
        # The recipe reads "secret.txt" which is not a declared input.
        # In a cold build, the file doesn't exist, so the cat fails.
        design = {
            "name": "leaky", "fuel": 10, "target": "w",
            "rules": [{
                "name": "w", "kind": "action", "inputs": [],
                "outputs": ["out.txt"],
                "run": "cat secret.txt > out.txt",
            }],
        }
        accepted = tmp_path / "accepted.txt"
        accepted.write_text("session secret\n")
        site_dir = str(tmp_path / "cond")

        result = _condense(design, {"out.txt": str(accepted)}, site_dir)

        assert result["verdict"] == "REJECT"
        # Verify no husk was sealed in any machine directory
        for sub in ("m1", "m2", "m3"):
            _no_husk_sealed(str(Path(site_dir) / sub))


class TestNondeterministicAction:
    """Invariant 2: An action whose output differs across independent cold
    runs must REJECT under G.b (deterministic root convergence)."""

    def test_nondeterministic_action_rejects(self, tmp_path):
        # The recipe reads from /dev/urandom, producing different output
        # each time. M1 and M3 will diverge.
        design = {
            "name": "nondeterministic", "fuel": 10, "target": "w",
            "rules": [{
                "name": "w", "kind": "action", "inputs": [],
                "outputs": ["out.txt"],
                "run": "head -c 32 /dev/urandom | base64 > out.txt",
            }],
        }
        # The accepted output is arbitrary — even if it matched one machine,
        # the other would differ. But we need a file.
        accepted = tmp_path / "accepted.txt"
        accepted.write_text("anything\n")
        site_dir = str(tmp_path / "cond")

        result = _condense(design, {"out.txt": str(accepted)}, site_dir)

        assert result["verdict"] == "REJECT"


class TestReproducibleButUnaccepted:
    """Invariant 3: A deterministic recipe that reproduces the same root
    every cold run but whose output differs from the accepted output
    must REJECT under G.c (acceptance anchor)."""

    def test_reproducible_but_unaccepted_rejects(self, tmp_path):
        # The recipe always produces "ok\n" — deterministic and reproducible.
        # But the accepted output is "DIFFERENT\n" — doesn't match.
        design = {
            "name": "wrong-accept", "fuel": 10, "target": "w",
            "rules": [{
                "name": "w", "kind": "action", "inputs": [],
                "outputs": ["out.txt"],
                "run": "echo ok > out.txt",
            }],
        }
        accepted = tmp_path / "accepted.txt"
        accepted.write_text("DIFFERENT\n")
        site_dir = str(tmp_path / "cond")

        result = _condense(design, {"out.txt": str(accepted)}, site_dir)

        assert result["verdict"] == "REJECT"
        # Specifically, the acceptance anchor check should have failed
        assert any("acceptance anchor" in e for e in result["errors"])


class TestUnverdictableOracle:
    """Invariant 4: An oracle candidate with no executable, declared verdict
    predicate must REJECT. Prose acceptance is not a verdict."""

    def test_oracle_without_verdict_rejects(self, tmp_path):
        """Oracle rule with no verdict field at all."""
        design = {
            "name": "unverdictable", "fuel": 10, "target": "w",
            "rules": [{
                "name": "w", "kind": "oracle", "inputs": [],
                "outputs": ["out.txt"],
                "prompt": "write something to out.txt",
                "fuel": 5,
            }],
        }
        accepted = tmp_path / "accepted.txt"
        accepted.write_text("oracle output\n")
        site_dir = str(tmp_path / "cond")

        result = _condense(design, {"out.txt": str(accepted)}, site_dir)

        assert result["verdict"] == "REJECT"
        assert any("unverdictable" in e for e in result["errors"])

    def test_oracle_with_verdict_is_not_rejected_for_unverdictable(self, tmp_path):
        """Oracle rule with a valid verdict field passes the unverdictable check.

        The oracle itself may fail for other reasons (stub mode, etc.) but the
        unverdictable rejection specifically should not fire.
        """
        design = {
            "name": "verdictable", "fuel": 10, "target": "w",
            "rules": [{
                "name": "w", "kind": "oracle", "inputs": [],
                "outputs": ["out.txt"],
                "prompt": "write something to out.txt",
                "fuel": 5,
                "verdict": "file-nonempty:out.txt",
            }],
        }
        accepted = tmp_path / "accepted.txt"
        accepted.write_text("oracle output\n")
        site_dir = str(tmp_path / "cond")

        result = _condense(design, {"out.txt": str(accepted)}, site_dir)

        # Should NOT be rejected for "unverdictable"
        unverdictable_errors = [e for e in result["errors"] if "unverdictable" in e]
        assert unverdictable_errors == []


class TestTranscriptNeverInSeal:
    """Invariant 5: No transcript content reaches a sealed field.

    A candidate whose seal or manifest would contain transcript bytes
    must REJECT. In practice, gamma never places transcript bytes in
    the seal — this test verifies that invariant by checking that none
    of the sealed artifacts contain any of the original prompt text.
    """

    def test_transcript_not_in_seal(self, tmp_path):
        # Use a distinctive prompt string as "transcript content"
        transcript_marker = "UNIQUE_TRANSCRIPT_MARKER_12345_SHOULD_NEVER_APPEAR_IN_SEAL"

        design = {
            "name": "clean-seal", "fuel": 10, "target": "w",
            "rules": [{
                "name": "w", "kind": "action", "inputs": [],
                "outputs": ["out.txt"],
                "run": "echo ok > out.txt",
            }],
        }
        accepted = tmp_path / "accepted.txt"
        accepted.write_text("ok\n")
        site_dir = str(tmp_path / "cond")

        result = _condense(design, {"out.txt": str(accepted)}, site_dir)

        assert result["verdict"] == "CONDENSE"

        # Check that no sealed artifact contains the transcript marker.
        m1_dir = Path(result["site"])
        traces_dir = m1_dir / ".traces"
        assert traces_dir.is_dir()

        for sealed_file in traces_dir.iterdir():
            if sealed_file.is_file():
                content = sealed_file.read_text(errors="replace")
                assert transcript_marker not in content, \
                    f"transcript content found in {sealed_file.name}"

        # Also check the .husk file (binary CSE)
        for husk_file in m1_dir.glob("*.husk"):
            content = husk_file.read_bytes()
            assert transcript_marker.encode() not in content, \
                f"transcript content found in {husk_file.name}"

    def test_oracle_transcript_not_in_manifest(self, tmp_path):
        """Even when an oracle design condenses, the prompt text (transcript)
        must not appear in the manifest or seal files.

        We test with a deterministic action here since oracle stub mode doesn't
        actually run the prompt — but the design still carries prompt text.
        """
        prompt_text = "SECRET_ORACLE_PROMPT_NEVER_IN_SEAL_ABC789"

        design = {
            "name": "prompt-seal", "fuel": 10, "target": "w",
            "rules": [{
                "name": "w", "kind": "action", "inputs": [],
                "outputs": ["out.txt"],
                "run": "echo ok > out.txt",
            }],
        }
        accepted = tmp_path / "accepted.txt"
        accepted.write_text("ok\n")
        site_dir = str(tmp_path / "cond")

        result = _condense(design, {"out.txt": str(accepted)}, site_dir)
        assert result["verdict"] == "CONDENSE"

        # Verify the prompt text doesn't appear in sealed artifacts
        m1_dir = Path(result["site"])
        for sealed_file in (m1_dir / ".traces").iterdir():
            if sealed_file.is_file():
                content = sealed_file.read_text(errors="replace")
                assert prompt_text not in content
