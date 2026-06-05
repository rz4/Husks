"""Test that check() rejects outputs declared under import prefixes.

Imported paths are read-only; declaring an output under an import prefix
would break the symlink and write into the external directory on promote().
"""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = str(REPO_ROOT / "src")

# Ensure husks is importable
sys.path.insert(0, SRC_DIR)

from husks.locke import check


def _design_with_import_output(output_path: str, import_key: str = "inputdir") -> dict:
    """Build a design that declares an output under an import prefix."""
    return {
        "name": "import-leak-test",
        "fuel": 5,
        "target": "leak",
        "imports": {import_key: "/tmp/external"},
        "rules": [
            {
                "name": "leak",
                "kind": "action",
                "inputs": [],
                "outputs": [output_path],
                "run": "echo leaked > " + output_path,
            }
        ],
    }


class TestImportOutputRejection:
    """check() must reject outputs under import prefixes."""

    def test_output_under_import_prefix(self):
        """Output like 'inputdir/leak.txt' is under import prefix 'inputdir/'."""
        design = _design_with_import_output("inputdir/leak.txt")
        errors = check(design)
        assert any("import prefix" in e and "inputdir/leak.txt" in e for e in errors), (
            f"Expected import-prefix rejection for 'inputdir/leak.txt', got: {errors}"
        )

    def test_output_equals_import_prefix(self):
        """Output 'inputdir' matches the import key itself (bare prefix)."""
        design = _design_with_import_output("inputdir")
        errors = check(design)
        assert any("import prefix" in e and "'inputdir'" in e for e in errors), (
            f"Expected import-prefix rejection for bare 'inputdir', got: {errors}"
        )

    def test_output_nested_under_import(self):
        """Deeply nested output under import prefix is also rejected."""
        design = _design_with_import_output("inputdir/sub/deep/file.txt")
        errors = check(design)
        assert any("import prefix" in e for e in errors), (
            f"Expected import-prefix rejection for nested path, got: {errors}"
        )

    def test_output_not_under_import_passes(self):
        """Output not under any import prefix should not trigger this error."""
        design = {
            "name": "safe-test",
            "fuel": 5,
            "target": "safe",
            "imports": {"inputdir": "/tmp/external"},
            "rules": [
                {
                    "name": "safe",
                    "kind": "action",
                    "inputs": [],
                    "outputs": ["output.txt"],
                    "run": "echo ok > output.txt",
                }
            ],
        }
        errors = check(design)
        assert not any("import prefix" in e for e in errors), (
            f"Unexpected import-prefix error for safe output: {errors}"
        )

    def test_cli_rejects_import_output(self, tmp_path):
        """The CLI check command also rejects outputs under import prefixes."""
        design = _design_with_import_output("inputdir/leak.txt")
        design_file = tmp_path / "leak.json"
        design_file.write_text(json.dumps(design))

        env = {**os.environ, "PYTHONPATH": SRC_DIR}
        cmd = [sys.executable, "-c", "from husks.cli import main; main()",
               "check", str(design_file), "--json"]
        result = subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=30)
        assert result.returncode != 0, (
            f"CLI check should fail for import-prefix output, stdout: {result.stdout}"
        )
