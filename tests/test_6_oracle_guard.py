"""
test_6_oracle_guard.py -- Guard against silent sealing of empty oracle outputs.

An oracle that produces a missing or zero-byte declared output must halt the build.
Action rules are exempt: zero-byte markers (e.g. `touch .complete`) are legitimate.
"""

import os
import shutil
import tempfile

from conftest import make_site


def _empty_oracle_backend(S, rule_name, recipe, outputs):
    """Oracle backend that writes zero-byte files for all outputs."""
    from husks.build import site_path, write_text
    from pathlib import Path
    for o in outputs:
        p = Path(site_path(S, o))
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"")  # zero-byte file
    return {"tokens_in": 0, "tokens_out": 0, "cost_usd": 0.0, "fuel_steps": 1}


def _missing_oracle_backend(S, rule_name, recipe, outputs):
    """Oracle backend that writes nothing -- outputs stay missing."""
    return {"tokens_in": 0, "tokens_out": 0, "cost_usd": 0.0, "fuel_steps": 1}


def test_oracle_empty_output_halts():
    """An oracle producing a zero-byte declared output must halt, not seal."""
    from husks.designs.ir import run
    tmpdir = tempfile.mkdtemp(prefix="oracle-empty-")
    try:
        site = make_site(tmpdir)
        design = {
            "name": "empty-oracle-test",
            "fuel": 10,
            "target": "write-thing",
            "site": site,
            "site_inputs": ["input.txt"],
            "oracle_backend": _empty_oracle_backend,
            "rules": [
                {
                    "name": "write-thing",
                    "kind": "oracle",
                    "inputs": ["input.txt"],
                    "outputs": ["output.txt"],
                    "prompt": "Write something.",
                    "tools": ["write-file"],
                    "fuel": 3,
                },
            ],
        }
        S = run(design)
        assert S["status"] == "halted", (
            f"expected halt on empty oracle output, got: {S['status']}"
        )
        # must not have sealed the empty output
        seal_path = os.path.join(site, ".traces", "write-thing.seal")
        assert not os.path.exists(seal_path), "empty oracle output was sealed"
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_oracle_missing_output_halts():
    """An oracle whose declared output is never written must halt."""
    from husks.designs.ir import run
    tmpdir = tempfile.mkdtemp(prefix="oracle-missing-")
    try:
        site = make_site(tmpdir)
        design = {
            "name": "missing-oracle-test",
            "fuel": 10,
            "target": "write-thing",
            "site": site,
            "site_inputs": ["input.txt"],
            "oracle_backend": _missing_oracle_backend,
            "rules": [
                {
                    "name": "write-thing",
                    "kind": "oracle",
                    "inputs": ["input.txt"],
                    "outputs": ["output.txt"],
                    "prompt": "Write something.",
                    "tools": ["write-file"],
                    "fuel": 3,
                },
            ],
        }
        S = run(design)
        assert S["status"] == "halted", (
            f"expected halt on missing oracle output, got: {S['status']}"
        )
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_action_zero_byte_marker_commits():
    """An action producing a zero-byte marker file must still commit."""
    from husks.designs.ir import run
    tmpdir = tempfile.mkdtemp(prefix="action-marker-")
    try:
        site = make_site(tmpdir)
        design = {
            "name": "marker-test",
            "fuel": 10,
            "target": "finish",
            "site": site,
            "site_inputs": ["input.txt"],
            "rules": [
                {
                    "name": "finish",
                    "kind": "action",
                    "inputs": ["input.txt"],
                    "outputs": [".complete"],
                    "run": "touch .complete",
                },
            ],
        }
        S = run(design)
        assert S["status"] == "committed", (
            f"action with zero-byte marker should commit, got: {S['status']}"
        )
        assert os.path.exists(os.path.join(site, ".complete")), (
            ".complete marker not found"
        )
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)
