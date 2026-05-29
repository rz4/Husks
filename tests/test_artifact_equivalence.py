"""
test_artifact_equivalence.py -- Beta Gate C6: Artifact equivalence comparison.

Tests the compare_artifacts() function for cross-machine verification.
Used by the three-machine beta smoke test to verify that different
machines produce equivalent artifacts.

Tests cover:
- Equivalent builds produce equivalent comparison
- Different outputs detected
- Different roots detected
- Invalid roots detected
- Missing artifacts handled
"""

import tempfile
import shutil
from pathlib import Path


def test_equivalent_builds_are_equivalent():
    """Two identical builds are detected as equivalent."""
    from husks.build import build, rule, action
    from husks.manifest import compare_artifacts

    tmpdir = tempfile.mkdtemp(prefix="c6-equivalent-")
    try:
        # Build same design in two sites
        site_a = Path(tmpdir) / "site_a"
        site_a.mkdir()

        site_b = Path(tmpdir) / "site_b"
        site_b.mkdir()

        def write_output(S):
            from husks.build.site import write_path
            Path(write_path(S, "out.txt")).write_text("identical output\n")

        # Same node definition
        def make_node():
            return rule("worker", outputs=["out.txt"], recipe=action(write_output))

        S_a = build("demo", 10, make_node(), site=str(site_a))
        S_b = build("demo", 10, make_node(), site=str(site_b))

        assert S_a["status"] == "committed"
        assert S_b["status"] == "committed"

        # Compare artifacts
        result = compare_artifacts(str(site_a), str(site_b))

        assert result["equivalent"] is True, "equivalent builds should be detected"
        assert len(result["differences"]) == 0, "no differences should be found"
        assert result["details"]["root_a"] == result["details"]["root_b"]

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_different_outputs_detected():
    """Different output content is detected."""
    from husks.build import build, rule, action
    from husks.manifest import compare_artifacts

    tmpdir = tempfile.mkdtemp(prefix="c6-different-")
    try:
        site_a = Path(tmpdir) / "site_a"
        site_a.mkdir()

        site_b = Path(tmpdir) / "site_b"
        site_b.mkdir()

        def write_a(S):
            from husks.build.site import write_path
            Path(write_path(S, "out.txt")).write_text("output A\n")

        def write_b(S):
            from husks.build.site import write_path
            Path(write_path(S, "out.txt")).write_text("output B\n")

        node_a = rule("worker", outputs=["out.txt"], recipe=action(write_a))
        node_b = rule("worker", outputs=["out.txt"], recipe=action(write_b))

        S_a = build("demo", 10, node_a, site=str(site_a))
        S_b = build("demo", 10, node_b, site=str(site_b))

        assert S_a["status"] == "committed"
        assert S_b["status"] == "committed"

        # Compare artifacts
        result = compare_artifacts(str(site_a), str(site_b))

        assert result["equivalent"] is False, "different outputs should be detected"
        assert len(result["differences"]) > 0
        # Should report both root and output hash differences
        assert any("differ" in diff for diff in result["differences"])

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_tampered_root_detected():
    """Tampered output causing invalid root is detected."""
    from husks.build import build, rule, action
    from husks.manifest import compare_artifacts

    tmpdir = tempfile.mkdtemp(prefix="c6-tampered-")
    try:
        site_a = Path(tmpdir) / "site_a"
        site_a.mkdir()

        site_b = Path(tmpdir) / "site_b"
        site_b.mkdir()

        def write_output(S):
            from husks.build.site import write_path
            Path(write_path(S, "out.txt")).write_text("original\n")

        node = rule("worker", outputs=["out.txt"], recipe=action(write_output))

        S_a = build("demo", 10, node, site=str(site_a))
        S_b = build("demo", 10, node, site=str(site_b))

        assert S_a["status"] == "committed"
        assert S_b["status"] == "committed"

        # Tamper with site B output
        (site_b / "out.txt").write_text("tampered\n")

        # Compare artifacts
        result = compare_artifacts(str(site_a), str(site_b))

        assert result["equivalent"] is False
        assert "root_b_valid" in result["details"]
        assert result["details"]["root_b_valid"] is False, "tampered root should be invalid"
        assert any("invalid" in diff for diff in result["differences"])

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_missing_manifest_handled():
    """Missing manifest is handled gracefully."""
    from husks.build import build, rule, action
    from husks.manifest import compare_artifacts

    tmpdir = tempfile.mkdtemp(prefix="c6-missing-")
    try:
        site_a = Path(tmpdir) / "site_a"
        site_a.mkdir()

        site_b = Path(tmpdir) / "site_b"
        site_b.mkdir()

        def write_output(S):
            from husks.build.site import write_path
            Path(write_path(S, "out.txt")).write_text("data\n")

        node = rule("worker", outputs=["out.txt"], recipe=action(write_output))
        S_a = build("demo", 10, node, site=str(site_a))

        assert S_a["status"] == "committed"

        # Site B has no build (no manifest)
        result = compare_artifacts(str(site_a), str(site_b))

        assert result["equivalent"] is False
        assert any("missing manifest" in diff for diff in result["differences"])

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_check_roots_only():
    """Can compare roots without checking hashes."""
    from husks.build import build, rule, action
    from husks.manifest import compare_artifacts

    tmpdir = tempfile.mkdtemp(prefix="c6-roots-only-")
    try:
        site_a = Path(tmpdir) / "site_a"
        site_a.mkdir()

        site_b = Path(tmpdir) / "site_b"
        site_b.mkdir()

        def write_output(S):
            from husks.build.site import write_path
            Path(write_path(S, "out.txt")).write_text("same\n")

        def make_node():
            return rule("worker", outputs=["out.txt"], recipe=action(write_output))

        S_a = build("demo", 10, make_node(), site=str(site_a))
        S_b = build("demo", 10, make_node(), site=str(site_b))

        # Compare roots only
        result = compare_artifacts(str(site_a), str(site_b), check_hashes=False)

        assert result["equivalent"] is True
        # Roots compared but not hashes
        assert "root_a" in result["details"]
        assert "root_b" in result["details"]
        # Hashes not in details when check_hashes=False
        assert "outputs_a" not in result["details"] or len(result["details"]["outputs_a"]) == 0

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_check_hashes_only():
    """Can compare hashes without checking roots."""
    from husks.build import build, rule, action
    from husks.manifest import compare_artifacts

    tmpdir = tempfile.mkdtemp(prefix="c6-hashes-only-")
    try:
        site_a = Path(tmpdir) / "site_a"
        site_a.mkdir()

        site_b = Path(tmpdir) / "site_b"
        site_b.mkdir()

        def write_output(S):
            from husks.build.site import write_path
            Path(write_path(S, "out.txt")).write_text("content\n")

        def make_node():
            return rule("worker", outputs=["out.txt"], recipe=action(write_output))

        S_a = build("demo", 10, make_node(), site=str(site_a))
        S_b = build("demo", 10, make_node(), site=str(site_b))

        # Compare hashes only
        result = compare_artifacts(str(site_a), str(site_b), check_roots=False)

        assert result["equivalent"] is True
        # Hashes compared but not roots
        assert "outputs_a" in result["details"]
        assert "outputs_b" in result["details"]
        assert len(result["details"]["outputs_a"]) > 0

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_multiple_outputs_compared():
    """Multiple outputs are compared correctly."""
    from husks.build import build, rule, action
    from husks.manifest import compare_artifacts

    tmpdir = tempfile.mkdtemp(prefix="c6-multiple-")
    try:
        site_a = Path(tmpdir) / "site_a"
        site_a.mkdir()

        site_b = Path(tmpdir) / "site_b"
        site_b.mkdir()

        def write_outputs(S):
            from husks.build.site import write_path
            Path(write_path(S, "out1.txt")).write_text("first\n")
            Path(write_path(S, "out2.txt")).write_text("second\n")
            Path(write_path(S, "out3.txt")).write_text("third\n")

        def make_node():
            return rule(
                "worker",
                outputs=["out1.txt", "out2.txt", "out3.txt"],
                recipe=action(write_outputs),
            )

        S_a = build("demo", 10, make_node(), site=str(site_a))
        S_b = build("demo", 10, make_node(), site=str(site_b))

        result = compare_artifacts(str(site_a), str(site_b))

        assert result["equivalent"] is True
        # All three outputs should be in details
        assert len(result["details"]["outputs_a"]) == 3
        assert len(result["details"]["outputs_b"]) == 3

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_cross_machine_simulation():
    """Simulates cross-machine comparison (three-machine test pattern)."""
    from husks.build import build, rule, action
    from husks.manifest import compare_artifacts

    tmpdir = tempfile.mkdtemp(prefix="c6-cross-machine-")
    try:
        # Simulate Machine 1 and Machine 3 (both build from seed)
        machine1 = Path(tmpdir) / "machine1"
        machine1.mkdir()

        machine3 = Path(tmpdir) / "machine3"
        machine3.mkdir()

        def write_result(S):
            from husks.build.site import write_path
            # Deterministic output for cross-machine equivalence
            Path(write_path(S, "result.txt")).write_text("deterministic result\n")

        def make_seed_design():
            """Seed design that should produce same result on both machines."""
            return rule("process", outputs=["result.txt"], recipe=action(write_result))

        # Machine 1 build
        S1 = build("seed-build", 10, make_seed_design(), site=str(machine1))

        # Machine 3 build (independent, same seed)
        S3 = build("seed-build", 10, make_seed_design(), site=str(machine3))

        assert S1["status"] == "committed"
        assert S3["status"] == "committed"

        # Cross-machine comparison
        result = compare_artifacts(str(machine1), str(machine3))

        # Machines should produce equivalent artifacts
        assert result["equivalent"] is True, \
            "independent machines with same seed should produce equivalent artifacts"
        assert result["details"]["root_a"] == result["details"]["root_b"]
        assert result["details"]["root_a_valid"] is True
        assert result["details"]["root_b_valid"] is True

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)
