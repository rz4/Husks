"""test_condense_cli.py -- CLI-level tests for `husks condense`.

Tests cover:
1. condense exits 0 on success
2. condense exits 1 on reject
3. --json output has verdict field
4. --accept parsing with multiple outputs
"""

import json
import subprocess
import sys
import pytest
from pathlib import Path
from io import StringIO


def _write_design(tmp_path, *, action_cmd="echo ok > out.txt",
                  outputs=None, name="test"):
    """Write a design.json and return its path."""
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
                "inputs": [],
                "outputs": outputs,
                "run": action_cmd,
            },
        ],
    }
    p = tmp_path / "design.json"
    p.write_text(json.dumps(design))
    return str(p)


def _run_husks(*args):
    """Run husks CLI via subprocess and return CompletedProcess."""
    return subprocess.run(
        [sys.executable, "-c",
         "from husks.cli import _cli_entry; _cli_entry()"] + list(args),
        capture_output=True, text=True,
        timeout=120,
    )


class TestCondenseExitCodes:
    """condense exits 0 on success, 1 on reject."""

    def test_condense_exits_0_on_success(self, tmp_path):
        design_path = _write_design(tmp_path)
        accepted = tmp_path / "accepted.txt"
        accepted.write_text("ok\n")
        site_dir = str(tmp_path / "cond-site")

        result = _run_husks(
            "condense", design_path,
            "--accept", f"out.txt={accepted}",
            "--site", site_dir,
            "--stub",
        )

        assert result.returncode == 0, f"stderr: {result.stderr}\nstdout: {result.stdout}"

    def test_condense_exits_1_on_reject(self, tmp_path):
        design_path = _write_design(tmp_path)
        accepted = tmp_path / "accepted.txt"
        accepted.write_text("DIFFERENT CONTENT\n")
        site_dir = str(tmp_path / "cond-site")

        result = _run_husks(
            "condense", design_path,
            "--accept", f"out.txt={accepted}",
            "--site", site_dir,
            "--stub",
        )

        assert result.returncode == 1


class TestCondenseJsonOutput:
    """--json output contains verdict field."""

    def test_json_output_has_verdict(self, tmp_path):
        design_path = _write_design(tmp_path)
        accepted = tmp_path / "accepted.txt"
        accepted.write_text("ok\n")
        site_dir = str(tmp_path / "cond-site")

        result = _run_husks(
            "condense", design_path,
            "--accept", f"out.txt={accepted}",
            "--site", site_dir,
            "--stub", "--json",
        )

        assert result.returncode == 0, f"stderr: {result.stderr}\nstdout: {result.stdout}"
        data = json.loads(result.stdout)
        assert data["verdict"] == "CONDENSE"
        assert "checks" in data
        assert "acceptance_anchor" in data

    def test_json_reject_has_errors(self, tmp_path):
        design_path = _write_design(tmp_path)
        accepted = tmp_path / "accepted.txt"
        accepted.write_text("DIFFERENT\n")
        site_dir = str(tmp_path / "cond-site")

        result = _run_husks(
            "condense", design_path,
            "--accept", f"out.txt={accepted}",
            "--site", site_dir,
            "--stub", "--json",
        )

        assert result.returncode == 1
        data = json.loads(result.stdout)
        assert data["verdict"] == "REJECT"
        assert len(data["errors"]) > 0


class TestCondenseMultipleAccept:
    """--accept parsing with multiple outputs."""

    def test_multiple_accept_values(self, tmp_path):
        design = {
            "name": "multi", "fuel": 10, "target": "w",
            "rules": [{
                "name": "w", "kind": "action", "inputs": [],
                "outputs": ["a.txt", "b.txt"],
                "run": "echo ok > a.txt && echo ok > b.txt",
            }],
        }
        design_path = tmp_path / "design.json"
        design_path.write_text(json.dumps(design))

        (tmp_path / "acc_a.txt").write_text("ok\n")
        (tmp_path / "acc_b.txt").write_text("ok\n")
        site_dir = str(tmp_path / "cond-site")

        result = _run_husks(
            "condense", str(design_path),
            "--accept", f"a.txt={tmp_path / 'acc_a.txt'}",
            "--accept", f"b.txt={tmp_path / 'acc_b.txt'}",
            "--site", site_dir,
            "--stub", "--json",
        )

        assert result.returncode == 0, f"stderr: {result.stderr}\nstdout: {result.stdout}"
        data = json.loads(result.stdout)
        assert data["verdict"] == "CONDENSE"
        assert "a.txt" in data["acceptance_anchor"]
        assert "b.txt" in data["acceptance_anchor"]
