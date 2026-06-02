"""Test that freshness checking uses seal comparison as primary check."""

import tempfile
import shutil
from pathlib import Path


def test_seal_comparison_is_primary_check():
    """Verify that seal comparison catches all dependency changes.

    The seal is computed from recipe + input bindings. If we compare seals,
    we catch ALL dependency changes atomically, without needing separate
    checks for recipe changes, input additions, input removals, etc.

    This test verifies that the seal-based approach works correctly.
    """
    from husks.build import build, rule

    tmpdir = tempfile.mkdtemp(prefix="seal-primary-test-")
    try:
        site = Path(tmpdir) / "site"
        site.mkdir()

        # Create input files
        (site / "a.txt").write_text("content A\n")
        (site / "b.txt").write_text("content B\n")

        # First build: rule with specific inputs
        node1 = rule(
            "processor",
            inputs=["a.txt"],
            outputs=["out.txt"],
            run="cat a.txt > out.txt",
        )

        S1 = build("seal-test", 10, node1, site=str(site))
        assert S1["status"] == "committed"

        # Read the seal file to verify it was written
        seal_file = site / ".traces" / "processor.seal"
        assert seal_file.exists()

        import json
        seal_data = json.loads(seal_file.read_text())
        first_seal = seal_data["seal"]
        assert first_seal  # Non-empty seal hash

        # Second build: identical rule (should be sealed/fresh)
        node2 = rule(
            "processor",
            inputs=["a.txt"],
            outputs=["out.txt"],
            run="cat a.txt > out.txt",
        )

        S2 = build("seal-test", 10, node2, site=str(site))
        assert S2["status"] == "committed"

        # Should be sealed (reused)
        sealed = any(e.get("event") == "sealed" and e.get("rule") == "processor"
                     for e in S2["trace"])
        assert sealed, "Identical rule should be sealed"

        # Third build: change inputs (should be stale)
        node3 = rule(
            "processor",
            inputs=["a.txt", "b.txt"],  # Added b.txt
            outputs=["out.txt"],
            run="cat a.txt > out.txt",  # Recipe unchanged
        )

        S3 = build("seal-test", 10, node3, site=str(site))
        assert S3["status"] == "committed"

        # Should be stale (fired) because seal changed
        fired = any(e.get("event") == "fired" and e.get("rule") == "processor"
                    for e in S3["trace"])
        assert fired, "Rule with changed inputs should fire"

        # Verify seal changed
        seal_data3 = json.loads(seal_file.read_text())
        third_seal = seal_data3["seal"]
        assert third_seal != first_seal, "Seal should change when inputs change"

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_seal_catches_all_dependency_changes():
    """Test that seal comparison catches various types of dependency changes.

    This demonstrates that we don't need separate checks for each type of
    change - the seal comparison catches them all.
    """
    from husks.build import build, rule

    tmpdir = tempfile.mkdtemp(prefix="seal-deps-test-")
    try:
        site = Path(tmpdir) / "site"
        site.mkdir()

        (site / "in.txt").write_text("data\n")

        # Baseline build
        node1 = rule("test", inputs=["in.txt"], outputs=["out.txt"], run="cat in.txt > out.txt")
        S1 = build("deps", 10, node1, site=str(site))
        assert S1["status"] == "committed"

        seal_file = site / ".traces" / "test.seal"
        import json
        baseline_seal = json.loads(seal_file.read_text())["seal"]

        # Test 1: Input content change
        (site / "in.txt").write_text("new data\n")
        S2 = build("deps", 10, node1, site=str(site))
        fired = any(e.get("event") == "fired" for e in S2["trace"])
        assert fired, "Input content change should trigger rebuild"
        seal2 = json.loads(seal_file.read_text())["seal"]
        assert seal2 != baseline_seal

        # Reset
        (site / "in.txt").write_text("data\n")
        S3 = build("deps", 10, node1, site=str(site))
        seal3 = json.loads(seal_file.read_text())["seal"]
        assert seal3 == baseline_seal, "Seal should match baseline after reset"

        # Test 2: Recipe change
        node2 = rule("test", inputs=["in.txt"], outputs=["out.txt"], run="echo modified > out.txt")
        S4 = build("deps", 10, node2, site=str(site))
        fired = any(e.get("event") == "fired" for e in S4["trace"])
        assert fired, "Recipe change should trigger rebuild"
        seal4 = json.loads(seal_file.read_text())["seal"]
        assert seal4 != baseline_seal

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)
