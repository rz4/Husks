"""
test_phase1_gate.py — Phase 1 gate: engine root == reader root.

The gate passes when the engine's CSE seal computation matches
the independent reader's recomputation from the serialized husk
and site files.
"""

import os
import sys
import shutil
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from husks.core import recompute_root


def _make_site(tmpdir):
    """Create a site directory with known input files."""
    site = os.path.join(tmpdir, "site")
    os.makedirs(site, exist_ok=True)
    with open(os.path.join(site, "greeting.txt"), "wb") as f:
        f.write(b"Hello, world!\n")
    with open(os.path.join(site, "config.txt"), "wb") as f:
        f.write(b"mode=test\n")
    return site


def _make_plan(site):
    """Build a plan with two rules: action (greet) -> oracle (combine)."""
    return {
        "name": "phase1-test",
        "fuel": 20,
        "target": "combine",
        "site": site,
        "site_inputs": ["greeting.txt", "config.txt"],
        "rules": [
            {
                "name": "greet",
                "kind": "action",
                "inputs": ["config.txt", "greeting.txt"],
                "outputs": ["hello.txt"],
            },
            {
                "name": "combine",
                "kind": "oracle",
                "inputs": ["hello.txt"],
                "outputs": ["result.txt"],
                "prompt": "Combine the files.",
                "tools": ["read-file", "write-file"],
                "fuel": 3,
            },
        ],
    }


def _run_build(plan):
    """Run a build via plan.run() and return the store."""
    from husks.plan import run
    return run(plan)


def test_engine_root_equals_reader_root():
    """Engine-computed build-root == core-reader build-root on a live build."""
    tmpdir = tempfile.mkdtemp(prefix="phase1-gate-")
    try:
        site = _make_site(tmpdir)
        plan = _make_plan(site)
        S = _run_build(plan)

        assert S["status"] == "committed", f"build failed: {S.get('value')}"
        assert "build-root" in S and S["build-root"] is not None, (
            "build-root not computed"
        )

        engine_root = S["build-root"]

        # Read the .husk file the engine wrote
        husk_path = os.path.join(site, "phase1-test.husk")
        assert os.path.isfile(husk_path), f".husk file not found at {husk_path}"

        with open(husk_path, "rb") as f:
            husk_bytes = f.read()

        # Recompute root via independent reader
        reader_root = recompute_root(husk_bytes, site)

        assert engine_root == reader_root, (
            f"build-root mismatch:\n"
            f"  engine: {engine_root}\n"
            f"  reader: {reader_root}"
        )
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_seal_determinism():
    """Running the same build twice produces the same root."""
    tmpdir = tempfile.mkdtemp(prefix="phase1-determ-")
    try:
        site = _make_site(tmpdir)
        plan = _make_plan(site)
        S1 = _run_build(plan)
        assert S1["status"] == "committed"
        root1 = S1["build-root"]

        # Wipe .traces to force a fresh rebuild
        traces_dir = os.path.join(site, ".traces")
        if os.path.isdir(traces_dir):
            shutil.rmtree(traces_dir)

        S2 = _run_build(plan)
        assert S2["status"] == "committed"
        root2 = S2["build-root"]

        assert root1 == root2, (
            f"non-deterministic roots:\n"
            f"  run 1: {root1}\n"
            f"  run 2: {root2}"
        )
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_freshness_skip():
    """Second run skips execution (seals fresh), same root."""
    tmpdir = tempfile.mkdtemp(prefix="phase1-fresh-")
    try:
        site = _make_site(tmpdir)
        plan = _make_plan(site)
        S1 = _run_build(plan)
        assert S1["status"] == "committed"
        root1 = S1["build-root"]

        # Second run — seals should be fresh, no re-execution
        S2 = _run_build(plan)
        assert S2["status"] == "committed"
        root2 = S2["build-root"]

        assert root1 == root2, (
            f"freshness skip root mismatch:\n"
            f"  run 1: {root1}\n"
            f"  run 2: {root2}"
        )

        # Verify some rules were sealed (skipped) in second run
        sealed_events = [e for e in S2["trace"] if e.get("event") == "sealed"]
        assert len(sealed_events) > 0, "expected some rules to be sealed on second run"
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_staleness_changes_root():
    """Modifying an input file changes the root."""
    tmpdir = tempfile.mkdtemp(prefix="phase1-stale-")
    try:
        site = _make_site(tmpdir)
        plan = _make_plan(site)
        S1 = _run_build(plan)
        assert S1["status"] == "committed"
        root1 = S1["build-root"]

        # Modify an input file
        with open(os.path.join(site, "config.txt"), "wb") as f:
            f.write(b"mode=changed\n")

        S2 = _run_build(plan)
        assert S2["status"] == "committed"
        root2 = S2["build-root"]

        assert root1 != root2, (
            f"root should change when input changes, but both are: {root1}"
        )
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


if __name__ == "__main__":
    test_engine_root_equals_reader_root()
    print("PASS: engine root == reader root")
    test_seal_determinism()
    print("PASS: seal determinism")
    test_freshness_skip()
    print("PASS: freshness skip")
    test_staleness_changes_root()
    print("PASS: staleness changes root")
    print("\nAll Phase 1 gate tests PASSED")
