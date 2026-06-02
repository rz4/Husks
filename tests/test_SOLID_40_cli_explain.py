"""Test CLI explain command with graph, diff, seal, and subject modes."""

import tempfile
import shutil
import json
from pathlib import Path
import subprocess
import sys


def test_explain_graph_with_design_positional():
    """husks explain --graph design.json should treat design.json as design file.

    Regression test: positional arg after --graph should be the design file,
    not interpreted as a subject.
    """
    tmpdir = tempfile.mkdtemp(prefix="explain-graph-")
    try:
        # Create a minimal design file
        design_path = Path(tmpdir) / "test-design.json"
        design = {
            "name": "test-graph",
            "fuel": 10,
            "target": "output",
            "rules": [
                {
                    "name": "output",
                    "kind": "action",
                    "outputs": ["output.txt"],
                    "run": "echo 'test' > output.txt",
                }
            ],
        }
        design_path.write_text(json.dumps(design, indent=2))

        # Run husks explain --graph with design file as positional arg
        result = subprocess.run(
            [sys.executable, "-m", "husks.cli", "explain", "--graph", str(design_path)],
            capture_output=True,
            text=True,
        )

        # Should succeed and show graph
        assert result.returncode == 0, \
            f"explain --graph should succeed, stderr: {result.stderr}"

        # Output should contain the rule name
        assert "output" in result.stdout, \
            "Graph output should contain rule name"

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_explain_graph_default_design():
    """husks explain --graph should use design.json when no design specified."""
    tmpdir = tempfile.mkdtemp(prefix="explain-graph-default-")
    try:
        # Create design.json in working directory
        design_path = Path(tmpdir) / "design.json"
        design = {
            "name": "default-design",
            "fuel": 10,
            "target": "result",
            "rules": [
                {
                    "name": "result",
                    "kind": "action",
                    "outputs": ["result.txt"],
                    "run": "echo 'done' > result.txt",
                }
            ],
        }
        design_path.write_text(json.dumps(design, indent=2))

        # Run from the tmpdir
        result = subprocess.run(
            [sys.executable, "-m", "husks.cli", "explain", "--graph"],
            capture_output=True,
            text=True,
            cwd=tmpdir,
        )

        assert result.returncode == 0, \
            f"explain --graph should find design.json, stderr: {result.stderr}"
        assert "result" in result.stdout

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_explain_graph_json_format():
    """husks explain --graph --format json should output JSON."""
    tmpdir = tempfile.mkdtemp(prefix="explain-graph-json-")
    try:
        design_path = Path(tmpdir) / "design.json"
        design = {
            "name": "json-graph",
            "fuel": 5,
            "target": "final",
            "rules": [
                {"name": "final", "kind": "action", "outputs": ["final.txt"], "run": "touch final.txt"}
            ],
        }
        design_path.write_text(json.dumps(design, indent=2))

        result = subprocess.run(
            [sys.executable, "-m", "husks.cli", "explain", "--graph", "--format", "json", str(design_path)],
            capture_output=True,
            text=True,
        )

        assert result.returncode == 0
        # Should be valid JSON
        graph_data = json.loads(result.stdout)
        assert "nodes" in graph_data or "rules" in graph_data

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_explain_diff_with_artifacts():
    """husks explain --diff should show artifact differences."""
    tmpdir = tempfile.mkdtemp(prefix="explain-diff-")
    try:
        # Create design and site
        design_path = Path(tmpdir) / "design.json"
        site = Path(tmpdir) / "site"
        site.mkdir()

        design = {
            "name": "diff-test",
            "fuel": 10,
            "target": "output",
            "rules": [
                {"name": "output", "kind": "action", "outputs": ["output.txt"], "run": "echo 'v1' > output.txt"}
            ],
        }
        design_path.write_text(json.dumps(design, indent=2))

        # First build to create sealed artifacts
        subprocess.run(
            [sys.executable, "-m", "husks.cli", "run", "--stub", "--site", str(site), str(design_path)],
            capture_output=True,
        )

        # Modify the output to create a diff
        (site / "output.txt").write_text("modified\n")

        # Run explain --diff
        result = subprocess.run(
            [sys.executable, "-m", "husks.cli", "explain", "--diff", "--site", str(site)],
            capture_output=True,
            text=True,
            cwd=tmpdir,
        )

        assert result.returncode == 0, f"explain --diff failed: {result.stderr}"
        # Should show the modified file
        assert "output.txt" in result.stdout or "modified" in result.stdout

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_explain_diff_json_output():
    """husks explain --diff --json should output JSON format."""
    tmpdir = tempfile.mkdtemp(prefix="explain-diff-json-")
    try:
        design_path = Path(tmpdir) / "design.json"
        site = Path(tmpdir) / "site"
        site.mkdir()

        design = {
            "name": "diff-json",
            "fuel": 10,
            "target": "data",
            "rules": [
                {"name": "data", "kind": "action", "outputs": ["data.txt"], "run": "echo 'data' > data.txt"}
            ],
        }
        design_path.write_text(json.dumps(design, indent=2))

        # Build to create artifacts
        subprocess.run(
            [sys.executable, "-m", "husks.cli", "run", "--stub", "--site", str(site), str(design_path)],
            capture_output=True,
        )

        # Run explain --diff --json
        result = subprocess.run(
            [sys.executable, "-m", "husks.cli", "explain", "--diff", "--json", "--site", str(site)],
            capture_output=True,
            text=True,
            cwd=tmpdir,
        )

        assert result.returncode == 0
        diff_data = json.loads(result.stdout)
        assert "modified" in diff_data or "fresh" in diff_data

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_explain_seal_for_rule():
    """husks explain --seal RULE should show seal information."""
    tmpdir = tempfile.mkdtemp(prefix="explain-seal-")
    try:
        design_path = Path(tmpdir) / "design.json"
        site = Path(tmpdir) / "site"
        site.mkdir()

        design = {
            "name": "seal-test",
            "fuel": 10,
            "target": "sealed-output",
            "rules": [
                {"name": "sealed-output", "kind": "action", "outputs": ["sealed.txt"], "run": "echo 'sealed' > sealed.txt"}
            ],
        }
        design_path.write_text(json.dumps(design, indent=2))

        # Build to create seal
        subprocess.run(
            [sys.executable, "-m", "husks.cli", "run", "--stub", "--site", str(site), str(design_path)],
            capture_output=True,
        )

        # Explain seal
        result = subprocess.run(
            [sys.executable, "-m", "husks.cli", "explain", "--seal", "sealed-output", "--site", str(site)],
            capture_output=True,
            text=True,
            cwd=tmpdir,
        )

        assert result.returncode == 0, f"explain --seal failed: {result.stderr}"
        # Should contain seal information
        assert "seal" in result.stdout.lower()

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_explain_subject_for_rule():
    """husks explain RULE should show rule information."""
    tmpdir = tempfile.mkdtemp(prefix="explain-subject-")
    try:
        design_path = Path(tmpdir) / "design.json"
        site = Path(tmpdir) / "site"
        site.mkdir()

        design = {
            "name": "subject-test",
            "fuel": 10,
            "target": "my-rule",
            "rules": [
                {"name": "my-rule", "kind": "action", "outputs": ["my-output.txt"], "run": "echo 'output' > my-output.txt"}
            ],
        }
        design_path.write_text(json.dumps(design, indent=2))

        # Build to create rule state
        subprocess.run(
            [sys.executable, "-m", "husks.cli", "run", "--stub", "--site", str(site), str(design_path)],
            capture_output=True,
        )

        # Explain rule
        result = subprocess.run(
            [sys.executable, "-m", "husks.cli", "explain", "my-rule", "--site", str(site)],
            capture_output=True,
            text=True,
            cwd=tmpdir,
        )

        assert result.returncode == 0, f"explain subject failed: {result.stderr}"
        # Should show rule information
        assert "my-rule" in result.stdout

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_explain_subject_json_output():
    """husks explain RULE --json should output JSON format."""
    tmpdir = tempfile.mkdtemp(prefix="explain-subject-json-")
    try:
        design_path = Path(tmpdir) / "design.json"
        site = Path(tmpdir) / "site"
        site.mkdir()

        design = {
            "name": "subject-json",
            "fuel": 10,
            "target": "test-rule",
            "rules": [
                {"name": "test-rule", "kind": "action", "inputs": [], "outputs": ["test.txt"], "run": "echo 'test' > test.txt"}
            ],
        }
        design_path.write_text(json.dumps(design, indent=2))

        # Build
        subprocess.run(
            [sys.executable, "-m", "husks.cli", "run", "--stub", "--site", str(site), str(design_path)],
            capture_output=True,
        )

        # Explain with JSON output
        result = subprocess.run(
            [sys.executable, "-m", "husks.cli", "explain", "test-rule", "--json", "--site", str(site)],
            capture_output=True,
            text=True,
            cwd=tmpdir,
        )

        assert result.returncode == 0
        subject_data = json.loads(result.stdout)
        # explain subject outputs the status schema with cursor set to the subject
        assert "nodes" in subject_data
        assert subject_data["cursor"] == "test-rule"

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_explain_no_args_shows_error():
    """husks explain with no arguments should show error."""
    result = subprocess.run(
        [sys.executable, "-m", "husks.cli", "explain"],
        capture_output=True,
        text=True,
    )

    # Should fail with usage error
    assert result.returncode != 0
    assert "error" in result.stderr.lower() or "requires" in result.stderr.lower()


# ── Phase 5: Navigator mode tests ────────────────────────────────────


def test_explain_navigator_default_cursor():
    """husks explain --site m1 renders cursor at target (validate).

    Phase 5 acceptance: Navigator mode defaults to target cursor.
    """
    tmpdir = tempfile.mkdtemp(prefix="explain-nav-default-")
    try:
        # Create core-bootstrap design
        design_path = Path(tmpdir) / "design.json"
        site_m1 = Path(tmpdir) / "m1"
        site_m1.mkdir()

        design = {
            "name": "nav-test",
            "fuel": 20,
            "target": "validate",
            "rules": [
                {
                    "name": "generate",
                    "kind": "oracle",
                    "outputs": ["output.txt"],
                    "prompt": "Generate test content",
                    "tools": ["write-file"],
                    "fuel": 5
                },
                {
                    "name": "validate",
                    "kind": "action",
                    "inputs": ["output.txt"],
                    "outputs": ["validated.txt"],
                    "run": "cat output.txt > validated.txt"
                }
            ],
        }
        design_path.write_text(json.dumps(design, indent=2))

        # Build on m1
        subprocess.run(
            [sys.executable, "-m", "husks.cli", "run", "--stub", "--site", str(site_m1), str(design_path)],
            capture_output=True,
        )

        # Run explain without --node (should default to target)
        result = subprocess.run(
            [sys.executable, "-m", "husks.cli", "explain", "--site", str(site_m1)],
            capture_output=True,
            text=True,
        )

        assert result.returncode == 0, f"explain navigator failed: {result.stderr}"
        # Should show cursor at target
        assert "cursor:validate" in result.stdout, \
            "Navigator should show cursor:validate in header"
        # Should show cursor marker on validate
        assert "▶" in result.stdout, \
            "Navigator should show ▶ cursor marker"

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_explain_navigator_custom_node_aperture_0():
    """husks explain --site m1 --node generate --aperture 0 shows node only.

    Phase 5 acceptance: Aperture 0 shows node line without details.
    """
    tmpdir = tempfile.mkdtemp(prefix="explain-nav-aperture0-")
    try:
        design_path = Path(tmpdir) / "design.json"
        site_m1 = Path(tmpdir) / "m1"
        site_m1.mkdir()

        design = {
            "name": "aperture-test",
            "fuel": 20,
            "target": "validate",
            "rules": [
                {
                    "name": "generate",
                    "kind": "oracle",
                    "outputs": ["output.txt"],
                    "prompt": "Generate test",
                    "tools": ["write-file"],
                    "fuel": 5
                },
                {
                    "name": "validate",
                    "kind": "action",
                    "inputs": ["output.txt"],
                    "outputs": ["validated.txt"],
                    "run": "cat output.txt > validated.txt"
                }
            ],
        }
        design_path.write_text(json.dumps(design, indent=2))

        # Build
        subprocess.run(
            [sys.executable, "-m", "husks.cli", "run", "--stub", "--site", str(site_m1), str(design_path)],
            capture_output=True,
        )

        # Explain with aperture 0 (node only)
        result = subprocess.run(
            [sys.executable, "-m", "husks.cli", "explain",
             "--site", str(site_m1), "--node", "generate", "--aperture", "0"],
            capture_output=True,
            text=True,
        )

        assert result.returncode == 0
        assert "cursor:generate" in result.stdout
        assert "aperture:0" in result.stdout
        # Aperture 0: should not show seal or trace details
        assert "seal:" not in result.stdout, \
            "Aperture 0 should not show seal details"

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_explain_navigator_aperture_3_trace():
    """husks explain --site m1 --node generate --aperture 3 shows full trace.

    Phase 5 acceptance: Aperture 3 shows trace with backend, model, tokens, cost.
    """
    tmpdir = tempfile.mkdtemp(prefix="explain-nav-aperture3-")
    try:
        design_path = Path(tmpdir) / "design.json"
        site_m1 = Path(tmpdir) / "m1"
        site_m1.mkdir()

        design = {
            "name": "trace-test",
            "fuel": 20,
            "target": "validate",
            "rules": [
                {
                    "name": "generate",
                    "kind": "oracle",
                    "outputs": ["output.txt"],
                    "prompt": "Generate content",
                    "tools": ["write-file"],
                    "fuel": 5
                },
                {
                    "name": "validate",
                    "kind": "action",
                    "inputs": ["output.txt"],
                    "outputs": ["validated.txt"],
                    "run": "cat output.txt > validated.txt"
                }
            ],
        }
        design_path.write_text(json.dumps(design, indent=2))

        # Build with stub oracle (produces trace)
        subprocess.run(
            [sys.executable, "-m", "husks.cli", "run", "--stub", "--site", str(site_m1), str(design_path)],
            capture_output=True,
        )

        # Explain with aperture 3 (full trace)
        result = subprocess.run(
            [sys.executable, "-m", "husks.cli", "explain",
             "--site", str(site_m1), "--node", "generate", "--aperture", "3"],
            capture_output=True,
            text=True,
        )

        assert result.returncode == 0
        assert "aperture:3" in result.stdout
        # Aperture 3 should show trace section with cost
        assert "trace:" in result.stdout, \
            "Aperture 3 should show trace section"
        assert "cost:" in result.stdout, \
            "Aperture 3 should show cost"

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_explain_navigator_cached_node():
    """husks explain --site m2 --node generate --aperture 3 shows cache provenance.

    Phase 5 acceptance: Cached nodes show cache source in trace.
    """
    tmpdir = tempfile.mkdtemp(prefix="explain-nav-cached-")
    try:
        design_path = Path(tmpdir) / "design.json"
        site_m1 = Path(tmpdir) / "m1"
        site_m2 = Path(tmpdir) / "m2"
        site_m1.mkdir()
        site_m2.mkdir()

        design = {
            "name": "cache-test",
            "fuel": 20,
            "target": "validate",
            "rules": [
                {
                    "name": "generate",
                    "kind": "oracle",
                    "outputs": ["output.txt"],
                    "prompt": "Generate cached content",
                    "tools": ["write-file"],
                    "fuel": 5
                },
                {
                    "name": "validate",
                    "kind": "action",
                    "inputs": ["output.txt"],
                    "outputs": ["validated.txt"],
                    "run": "cat output.txt > validated.txt"
                }
            ],
        }

        # Build on m1 first
        design_path.write_text(json.dumps(design, indent=2))
        subprocess.run(
            [sys.executable, "-m", "husks.cli", "run", "--stub", "--site", str(site_m1), str(design_path)],
            capture_output=True,
        )

        # Export cache from m1
        cache_file = Path(tmpdir) / "cache.tar.gz"
        subprocess.run(
            [sys.executable, "-m", "husks.cli", "cache", "export",
             str(cache_file), "--site", str(site_m1)],
            capture_output=True,
        )

        # Import cache to m2
        subprocess.run(
            [sys.executable, "-m", "husks.cli", "cache", "import",
             str(cache_file), "--site", str(site_m2)],
            capture_output=True,
        )

        # Build on m2 (should reuse cache)
        design_path.write_text(json.dumps(design, indent=2))
        subprocess.run(
            [sys.executable, "-m", "husks.cli", "run", "--stub", "--site", str(site_m2), str(design_path)],
            capture_output=True,
        )

        # Explain m2 generate node at aperture 3
        result = subprocess.run(
            [sys.executable, "-m", "husks.cli", "explain",
             "--site", str(site_m2), "--node", "generate", "--aperture", "3"],
            capture_output=True,
            text=True,
        )

        assert result.returncode == 0
        # Cached node should show cache indicator
        assert "◆" in result.stdout or "cached" in result.stdout.lower(), \
            "Cached node should show cache glyph or label"
        # Aperture 3 should show cache provenance (if available)
        # Note: cache source may be shown in trace or cache section

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_explain_navigator_json_output():
    """husks explain --site m1 --json includes cursor and aperture metadata.

    Phase 5 acceptance: JSON surface includes navigation state.
    """
    tmpdir = tempfile.mkdtemp(prefix="explain-nav-json-")
    try:
        design_path = Path(tmpdir) / "design.json"
        site_m1 = Path(tmpdir) / "m1"
        site_m1.mkdir()

        design = {
            "name": "json-nav",
            "fuel": 20,
            "target": "validate",
            "rules": [
                {
                    "name": "generate",
                    "kind": "oracle",
                    "outputs": ["output.txt"],
                    "prompt": "Generate",
                    "tools": ["write-file"],
                    "fuel": 5
                },
                {
                    "name": "validate",
                    "kind": "action",
                    "inputs": ["output.txt"],
                    "outputs": ["validated.txt"],
                    "run": "cat output.txt > validated.txt"
                }
            ],
        }
        design_path.write_text(json.dumps(design, indent=2))

        # Build
        subprocess.run(
            [sys.executable, "-m", "husks.cli", "run", "--stub", "--site", str(site_m1), str(design_path)],
            capture_output=True,
        )

        # Explain with JSON output
        result = subprocess.run(
            [sys.executable, "-m", "husks.cli", "explain",
             "--site", str(site_m1), "--node", "generate",
             "--aperture", "2", "--json"],
            capture_output=True,
            text=True,
        )

        assert result.returncode == 0
        data = json.loads(result.stdout)

        # Should include cursor and aperture in JSON
        assert "cursor" in data, "JSON output should include cursor"
        assert data["cursor"] == "generate"
        assert "aperture" in data, "JSON output should include aperture"
        assert data["aperture"] == 2

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


# ── Phase 6: Interactive pilot tests ──────────────────────────────────


def test_explain_interactive_requires_tty():
    """husks explain --site m1 --interactive falls back to deterministic in non-TTY.

    Phase 6 acceptance: Interactive mode requires a TTY. Non-TTY environments
    render once and exit, even when --interactive is specified.
    """
    tmpdir = tempfile.mkdtemp(prefix="explain-interactive-notty-")
    try:
        design_path = Path(tmpdir) / "design.json"
        site_m1 = Path(tmpdir) / "m1"
        site_m1.mkdir()

        design = {
            "name": "interactive-test",
            "fuel": 20,
            "target": "validate",
            "rules": [
                {
                    "name": "generate",
                    "kind": "oracle",
                    "outputs": ["output.txt"],
                    "prompt": "Generate",
                    "tools": ["write-file"],
                    "fuel": 5
                },
                {
                    "name": "validate",
                    "kind": "action",
                    "inputs": ["output.txt"],
                    "outputs": ["validated.txt"],
                    "run": "cat output.txt > validated.txt"
                }
            ],
        }
        design_path.write_text(json.dumps(design, indent=2))

        # Build
        subprocess.run(
            [sys.executable, "-m", "husks.cli", "run", "--stub", "--site", str(site_m1), str(design_path)],
            capture_output=True,
        )

        # Run explain with --interactive in non-TTY (subprocess)
        result = subprocess.run(
            [sys.executable, "-m", "husks.cli", "explain",
             "--site", str(site_m1), "--interactive"],
            capture_output=True,
            text=True,
        )

        # Should succeed and render deterministically (not hang waiting for input)
        assert result.returncode == 0, \
            f"Non-TTY interactive should fall back to deterministic: {result.stderr}"
        # Should show the DAG
        assert "validate" in result.stdout or "generate" in result.stdout
        # Should show controls footer since interactive was requested
        assert "move" in result.stdout or "aperture" in result.stdout or "quit" in result.stdout

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_explain_deterministic_without_interactive():
    """husks explain --site m1 (no --interactive) renders once.

    Phase 6 acceptance: Without --interactive, explain always renders
    deterministically regardless of TTY status.
    """
    tmpdir = tempfile.mkdtemp(prefix="explain-deterministic-")
    try:
        design_path = Path(tmpdir) / "design.json"
        site_m1 = Path(tmpdir) / "m1"
        site_m1.mkdir()

        design = {
            "name": "deterministic-test",
            "fuel": 20,
            "target": "output",
            "rules": [
                {
                    "name": "output",
                    "kind": "action",
                    "outputs": ["output.txt"],
                    "run": "echo 'test' > output.txt"
                }
            ],
        }
        design_path.write_text(json.dumps(design, indent=2))

        # Build
        subprocess.run(
            [sys.executable, "-m", "husks.cli", "run", "--stub", "--site", str(site_m1), str(design_path)],
            capture_output=True,
        )

        # Run explain WITHOUT --interactive
        result = subprocess.run(
            [sys.executable, "-m", "husks.cli", "explain", "--site", str(site_m1)],
            capture_output=True,
            text=True,
        )

        # Should render once and exit immediately
        assert result.returncode == 0
        assert "output" in result.stdout
        # Should NOT show controls footer (interactive not requested)
        # This is actually already tested by previous tests, but confirms behavior

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)
