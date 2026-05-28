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
            "site": str(site),
            "target": "output",
            "rules": [
                {"name": "output", "kind": "action", "outputs": ["output.txt"], "run": "echo 'v1' > output.txt"}
            ],
        }
        design_path.write_text(json.dumps(design, indent=2))

        # First build to create sealed artifacts
        subprocess.run(
            [sys.executable, "-m", "husks.cli", "run", "--stub", str(design_path)],
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
            "site": str(site),
            "target": "data",
            "rules": [
                {"name": "data", "kind": "action", "outputs": ["data.txt"], "run": "echo 'data' > data.txt"}
            ],
        }
        design_path.write_text(json.dumps(design, indent=2))

        # Build to create artifacts
        subprocess.run(
            [sys.executable, "-m", "husks.cli", "run", "--stub", str(design_path)],
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
            "site": str(site),
            "target": "sealed-output",
            "rules": [
                {"name": "sealed-output", "kind": "action", "outputs": ["sealed.txt"], "run": "echo 'sealed' > sealed.txt"}
            ],
        }
        design_path.write_text(json.dumps(design, indent=2))

        # Build to create seal
        subprocess.run(
            [sys.executable, "-m", "husks.cli", "run", "--stub", str(design_path)],
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
            "site": str(site),
            "target": "my-rule",
            "rules": [
                {"name": "my-rule", "kind": "action", "outputs": ["my-output.txt"], "run": "echo 'output' > my-output.txt"}
            ],
        }
        design_path.write_text(json.dumps(design, indent=2))

        # Build to create rule state
        subprocess.run(
            [sys.executable, "-m", "husks.cli", "run", "--stub", str(design_path)],
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
            "site": str(site),
            "target": "test-rule",
            "rules": [
                {"name": "test-rule", "kind": "action", "inputs": [], "outputs": ["test.txt"], "run": "echo 'test' > test.txt"}
            ],
        }
        design_path.write_text(json.dumps(design, indent=2))

        # Build
        subprocess.run(
            [sys.executable, "-m", "husks.cli", "run", "--stub", str(design_path)],
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
        assert subject_data["type"] == "rule"
        assert subject_data["name"] == "test-rule"

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
