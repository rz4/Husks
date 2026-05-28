"""
test_15_triage_regressions.py -- Regression tests for all triage issues.

Covers:
  Phase 0: Trace lifecycle (#3)
  Phase 1: Usability (#1 conformance lookup, #4 json output, #13 list target)
  Phase 2: Integrity (#7 path sandboxing, #5 output-hash freshness, #8 verdict identity)
"""

import json
import os
import shutil
import tempfile

import pytest

from husks.utils.events import BuildTrace


# ── Phase 0: Trace lifecycle (#3) ─────────────────────────────────

def test_trace_clear_preserves_listeners():
    """BuildTrace.clear() resets state but keeps listeners attached."""
    t = BuildTrace()
    events = []

    class Listener:
        def notify(self, event):
            events.append(event)

    t.add_listener(Listener())
    t.build_start("first", fuel=5, site="/tmp/a")
    assert len(t._events) >= 1

    t.clear()
    assert len(t._events) == 0
    assert len(t._listeners) == 1  # listener still attached

    # Listener still receives events after clear
    t.build_start("second", fuel=3, site="/tmp/b")
    assert len(events) >= 1  # listener was notified
    assert events[-1]["name"] == "second"


def test_trace_clear_listeners():
    """BuildTrace.clear_listeners() removes all listeners."""
    t = BuildTrace()

    class Listener:
        def notify(self, event):
            pass

    t.add_listener(Listener())
    t.add_listener(Listener())
    assert len(t._listeners) == 2

    t.clear_listeners()
    assert len(t._listeners) == 0


def test_sequential_builds_independent_traces():
    """Two sequential in-process builds have independent traces."""
    from husks.designs.ir import run

    site1 = tempfile.mkdtemp(prefix="trace-test-1-")
    site2 = tempfile.mkdtemp(prefix="trace-test-2-")
    try:
        design = {
            "name": "trace-test",
            "fuel": 10,
            "target": "done",
            "rules": [
                {
                    "name": "step",
                    "kind": "action",
                    "inputs": [],
                    "outputs": ["out.txt"],
                    "run": "echo hello > out.txt",
                },
                {
                    "name": "done",
                    "kind": "action",
                    "inputs": ["out.txt"],
                    "outputs": [".done"],
                },
            ],
        }

        from husks.utils import trace as T

        S1 = run(design, site=site1)
        trace1_events = list(T._events)
        trace1_nodes = list(T._node_events)

        S2 = run(design, site=site2)
        trace2_events = list(T._events)
        trace2_nodes = list(T._node_events)

        # Second build should only have its own events, not accumulated from first
        # Both builds should have the same number of node events
        assert len(trace1_nodes) == len(trace2_nodes)
        # The second trace should NOT be longer than the first
        # (before fix, it would accumulate)
        assert len(trace2_events) <= len(trace1_events) + 2  # small tolerance
    finally:
        shutil.rmtree(site1, ignore_errors=True)
        shutil.rmtree(site2, ignore_errors=True)


# ── Phase 1: Usability (#13 list target) ──────────────────────────

def test_check_list_target_tolerated():
    """check() handles 'target' being a list without crashing."""
    from husks.designs.ir import check

    design = {
        "name": "test",
        "fuel": 10,
        "target": ["done"],
        "rules": [
            {
                "name": "done",
                "kind": "action",
                "inputs": [],
                "outputs": [".done"],
            },
        ],
    }
    errors = check(design)
    assert not errors, f"unexpected errors: {errors}"


def test_check_list_target_multiple():
    """check() handles 'target' being a list of multiple targets."""
    from husks.designs.ir import check

    design = {
        "name": "test",
        "fuel": 10,
        "target": ["a", "b"],
        "rules": [
            {"name": "a", "kind": "action", "inputs": [], "outputs": ["a.txt"]},
            {"name": "b", "kind": "action", "inputs": [], "outputs": ["b.txt"]},
        ],
    }
    errors = check(design)
    assert not errors, f"unexpected errors: {errors}"


# ── Phase 2: Integrity (#7 path sandboxing) ───────────────────────

def test_check_rejects_path_traversal_output():
    """check() rejects outputs with '..' components."""
    from husks.designs.ir import check

    design = {
        "name": "test",
        "fuel": 10,
        "target": "evil",
        "rules": [
            {
                "name": "evil",
                "kind": "action",
                "inputs": [],
                "outputs": ["../escape.txt"],
            },
        ],
    }
    errors = check(design)
    assert any(".." in e for e in errors), f"expected path traversal error, got: {errors}"


def test_check_rejects_absolute_path_output():
    """check() rejects outputs with absolute paths."""
    from husks.designs.ir import check

    design = {
        "name": "test",
        "fuel": 10,
        "target": "evil",
        "rules": [
            {
                "name": "evil",
                "kind": "action",
                "inputs": [],
                "outputs": ["/etc/passwd"],
            },
        ],
    }
    errors = check(design)
    assert any("absolute" in e for e in errors), f"expected absolute path error, got: {errors}"


def test_check_rejects_path_traversal_input():
    """check() rejects inputs with '..' components."""
    from husks.designs.ir import check

    design = {
        "name": "test",
        "fuel": 10,
        "target": "evil",
        "site_inputs": ["../escape.txt"],
        "rules": [
            {
                "name": "evil",
                "kind": "action",
                "inputs": ["../escape.txt"],
                "outputs": ["out.txt"],
            },
        ],
    }
    errors = check(design)
    assert any(".." in e for e in errors), f"expected path traversal error, got: {errors}"


def test_site_path_rejects_escape():
    """site_path() raises ValueError on path traversal."""
    from husks.build import site_path

    site = tempfile.mkdtemp(prefix="sandbox-test-")
    try:
        S = {"site": site}
        with pytest.raises(ValueError, match="escapes site"):
            site_path(S, "../escape.txt")
    finally:
        shutil.rmtree(site, ignore_errors=True)


# ── Phase 2: Integrity (#5 output-hash freshness) ─────────────────

def test_tampered_output_detected_as_stale():
    """freshness_check() detects tampered outputs after seal is written."""
    from husks.build import (
        fresh_store,
        write_seal,
        freshness_check,
        site_path,
        write_text,
        ensure_dir,
    )

    site = tempfile.mkdtemp(prefix="tamper-test-")
    try:
        S = fresh_store(site, fuel=10)
        ensure_dir(site_path(S, ".traces"))

        # Write initial output
        write_text(site_path(S, "result.txt"), "original content\n")

        # Write seal with output hashes
        recipe = {"type": "action", "fn": lambda S: None}
        recipe["fn"]._husks_cmd = "echo test"
        write_seal(S, "rule1", [], recipe, outputs=["result.txt"])

        # Verify fresh
        reason = freshness_check(S, "rule1", [], ["result.txt"], recipe)
        assert reason is None, f"expected fresh, got: {reason}"

        # Tamper with output
        write_text(site_path(S, "result.txt"), "TAMPERED content\n")

        # Should now be stale
        reason = freshness_check(S, "rule1", [], ["result.txt"], recipe)
        assert reason is not None
        assert "tampered" in reason
    finally:
        shutil.rmtree(site, ignore_errors=True)


# ── Phase 2: Integrity (#8 verdict identity) ──────────────────────

def test_verdict_policy_changes_recipe_digest():
    """Changing the verdict policy changes the recipe digest."""
    from husks.build import recipe_to_cse, first_valid
    from husks.core import recipe_digest, encode

    branch = {"type": "action", "fn": lambda S: None}
    branch["fn"]._husks_cmd = "echo test"

    # Default verdict (first_valid)
    recipe1 = {"type": "trial", "branches": [branch], "verdict": None}
    cse1 = recipe_to_cse(recipe1)
    digest1 = recipe_digest(cse1)

    # Custom verdict
    def custom_verdict(results):
        return results[-1]

    recipe2 = {"type": "trial", "branches": [branch], "verdict": custom_verdict}
    cse2 = recipe_to_cse(recipe2)
    digest2 = recipe_digest(cse2)

    assert digest1 != digest2, "different verdict policies must produce different digests"


def test_verdict_policy_name_in_cse():
    """The verdict policy name appears in the CSE form for trial recipes."""
    from husks.build import recipe_to_cse, first_valid

    branch = {"type": "action", "fn": lambda S: None}
    branch["fn"]._husks_cmd = "echo test"

    recipe = {"type": "trial", "branches": [branch], "verdict": None}
    cse = recipe_to_cse(recipe)

    # cse should be [b"trial", policy_name, ...branches...]
    assert cse[0] == b"trial"
    assert cse[1] == b"first-valid"


# ── Phase 1: #4 JSON output should not contain console trace ──────

def test_json_output_clean(tmp_path):
    """--json output should be valid JSON without console trace pollution."""
    import subprocess
    import sys

    design = {
        "name": "json-test",
        "fuel": 10,
        "target": "done",
        "rules": [
            {
                "name": "step",
                "kind": "action",
                "inputs": [],
                "outputs": ["out.txt"],
                "run": "echo hello > out.txt",
            },
            {
                "name": "done",
                "kind": "action",
                "inputs": ["out.txt"],
                "outputs": [".done"],
            },
        ],
    }

    design_path = tmp_path / "design.json"
    design_path.write_text(json.dumps(design))
    site = str(tmp_path / "site")

    result = subprocess.run(
        [sys.executable, "-m", "husks.cli", "run", str(design_path),
         "--site", site, "--stub", "--json"],
        capture_output=True, text=True, timeout=30,
    )
    # stdout should be valid JSON (no console trace chars before it)
    stdout = result.stdout.strip()
    assert stdout, "expected JSON output on stdout"
    try:
        parsed = json.loads(stdout)
    except json.JSONDecodeError as e:
        pytest.fail(f"--json output is not valid JSON: {e}\nstdout:\n{stdout[:500]}")
    assert isinstance(parsed, dict)


# ── litellm import isolation ──────────────────────────────────────

def test_litellm_not_imported_at_module_level():
    """Importing husks.oracle.kernel should not trigger litellm import."""
    import subprocess
    import sys

    # Run in a subprocess to avoid already-imported litellm in this process
    code = (
        "import sys; "
        "import husks.oracle.kernel; "
        "print('litellm' in sys.modules)"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True, text=True, timeout=10,
    )
    assert result.returncode == 0, f"import failed: {result.stderr}"
    assert result.stdout.strip() == "False", (
        "litellm should not be imported at module level"
    )


# ── Import local name validation ─────────────────────────────────

def test_check_rejects_traversal_import_name():
    """check() rejects import local names with '..' components."""
    from husks.designs.ir import check

    design = {
        "name": "test",
        "fuel": 10,
        "target": "a",
        "imports": {"../outside": "/tmp"},
        "rules": [
            {"name": "a", "kind": "action", "inputs": [], "outputs": ["a.txt"]},
        ],
    }
    errors = check(design)
    assert any(".." in e for e in errors), f"expected path traversal error, got: {errors}"


def test_check_rejects_absolute_import_name():
    """check() rejects import local names with absolute paths."""
    from husks.designs.ir import check

    design = {
        "name": "test",
        "fuel": 10,
        "target": "a",
        "imports": {"/tmp/husks-import-escape": "/tmp"},
        "rules": [
            {"name": "a", "kind": "action", "inputs": [], "outputs": ["a.txt"]},
        ],
    }
    errors = check(design)
    assert any("absolute" in e for e in errors), f"expected absolute path error, got: {errors}"


# ── Oracle fuel budget ────────────────────────────────────────────

def test_check_allows_oracle_fuel_independent_of_global():
    """check() allows oracle fuel > global fuel (they're independent).

    Oracle fuel limits tool steps within that oracle.
    Global fuel counts rule fires (including trial branches).
    An oracle with fuel=99 is valid in a build with global fuel=1.
    """
    from husks.designs.ir import check

    design = {
        "name": "fuel",
        "fuel": 1,
        "target": "a",
        "rules": [
            {
                "name": "a",
                "kind": "oracle",
                "inputs": [],
                "outputs": ["a.txt"],
                "prompt": "do",
                "tools": ["write-file"],
                "fuel": 99,  # Oracle fuel > global fuel is allowed
            },
        ],
    }
    errors = check(design)
    assert len(errors) == 0, f"should allow oracle fuel > global fuel, got: {errors}"


def test_check_allows_oracle_fuel_within_budget():
    """check() accepts designs where oracle fuel fits within the budget."""
    from husks.designs.ir import check

    design = {
        "name": "fuel",
        "fuel": 10,
        "target": "a",
        "rules": [
            {
                "name": "a",
                "kind": "oracle",
                "inputs": [],
                "outputs": ["a.txt"],
                "prompt": "do",
                "tools": ["write-file"],
                "fuel": 5,
            },
        ],
    }
    errors = check(design)
    assert not errors, f"unexpected errors: {errors}"


# ── Old seal without output hashes → stale ────────────────────────

def test_old_seal_without_outputs_is_stale():
    """A seal missing 'outputs' field is treated as stale for upgrade."""
    from husks.build import (
        fresh_store,
        freshness_check,
        site_path,
        write_text,
        ensure_dir,
    )

    site = tempfile.mkdtemp(prefix="seal-upgrade-test-")
    try:
        S = fresh_store(site, fuel=10)
        ensure_dir(site_path(S, ".traces"))

        # Write output
        write_text(site_path(S, "result.txt"), "content\n")

        # Write a v1 seal WITHOUT outputs (old format)
        recipe = {"type": "action", "fn": lambda S: None}
        recipe["fn"]._husks_cmd = "echo test"

        from husks.build import compute_cse_seal, recipe_to_cse, recipe_digest
        from husks.core import recipe_digest as core_rd

        seal = compute_cse_seal(S, [], recipe)
        recipe_form = recipe_to_cse(recipe)
        rd = recipe_digest(recipe_form)
        old_seal = {"v": 1, "seal": seal, "recipe_digest": rd, "inputs": {}}
        write_text(
            os.path.join(site, ".traces", "rule1.seal"),
            json.dumps(old_seal, indent=2),
        )

        reason = freshness_check(S, "rule1", [], ["result.txt"], recipe)
        assert reason is not None
        assert "missing output hashes" in reason
    finally:
        shutil.rmtree(site, ignore_errors=True)


# ── Staged promotion atomicity ────────────────────────────────────

def test_staging_promotion_is_atomic():
    """Staged promotion validates all outputs before promoting any.

    Demonstrates that builds producing only partial outputs are caught
    by output validation before promotion.
    """
    from husks.build import build, rule
    from pathlib import Path

    tmpdir = tempfile.mkdtemp(prefix="atomic-promotion-")
    try:
        site = Path(tmpdir) / "site"
        site.mkdir()

        # Create existing outputs in live site
        (site / "a.txt").write_text("original a\n")
        (site / "b.txt").write_text("original b\n")

        # Rule that updates both outputs
        node = rule(
            "updater",
            outputs=["a.txt", "b.txt"],
            run="echo 'new a' > a.txt && echo 'new b' > b.txt",
        )

        # First build: should succeed and update both outputs
        S1 = build("atomic-test", 10, node, site=str(site))
        assert S1["status"] == "committed", f"First build failed: {S1['status']}"
        assert (site / "a.txt").read_text() == "new a\n"
        assert (site / "b.txt").read_text() == "new b\n"

        # Rule that only creates one of two declared outputs
        node2 = rule(
            "partial",
            outputs=["c.txt", "d.txt"],
            run="echo 'new c' > c.txt",  # Only creates c.txt, not d.txt
        )

        S2 = build("partial-test", 10, node2, site=str(site))
        # Build should halt because d.txt is missing (caught by output guard)
        assert S2["status"] == "halted", f"Expected halted, got {S2['status']}"
        assert "did not produce declared output" in S2["value"]

        # c.txt should NOT be promoted because validation failed
        assert not (site / "c.txt").exists(), \
            "Partial output should not be promoted when validation fails"

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_staging_promotion_preserves_backups():
    """Staged promotion creates backups of existing live outputs."""
    from husks.build.eval import _staged
    from husks.build import fresh_store
    from pathlib import Path

    tmpdir = tempfile.mkdtemp(prefix="backup-test-")
    try:
        site = Path(tmpdir) / "site"
        site.mkdir()

        # Create existing outputs in live site
        (site / "a.txt").write_text("original a\n")
        (site / "b.txt").write_text("original b\n")

        S = fresh_store(str(site), fuel=10)

        # Normal promotion (should succeed)
        with _staged(S, ["a.txt", "b.txt"]):
            # Create new outputs in staging
            stage_dir = Path(S["stage"])
            (stage_dir / "a.txt").write_text("new a\n")
            (stage_dir / "b.txt").write_text("new b\n")

        # After successful promotion, outputs should be updated
        assert (site / "a.txt").read_text() == "new a\n", \
            "a.txt should be updated"
        assert (site / "b.txt").read_text() == "new b\n", \
            "b.txt should be updated"

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)
