"""
test_11_output_guard.py -- Uniform declared-output guard: existence for all, nonempty for oracle.

An action that declares an output but never writes it must halt (not seal).
An oracle producing a zero-byte output must halt.
An action producing a zero-byte marker must still commit.
"""

import os
import shutil
import tempfile

from conftest import make_site


def _noop_oracle(S, rule_name, recipe, outputs):
    """Oracle backend that does nothing -- outputs stay missing."""
    return {"tokens_in": 0, "tokens_out": 0, "cost_usd": 0.0, "fuel_steps": 1}


def test_action_missing_output_halts():
    """An action that declares an output but never writes it must halt."""
    from husks.designs.ir import run
    from husks.build import build, rule, action as action_recipe
    tmpdir = tempfile.mkdtemp(prefix="guard-action-missing-")
    try:
        site = make_site(tmpdir)

        # Use a raw callable action that does nothing -- bypasses shell stdout capture
        def noop(S):
            pass

        node = rule(
            "writer",
            inputs=["input.txt"],
            outputs=["output.txt"],
            recipe=action_recipe(noop),
        )
        S = build("guard-action-missing", 10, node, site=site)
        assert S["status"] == "halted", (
            f"action missing declared output should halt, got: {S['status']}"
        )
        seal_path = os.path.join(site, ".traces", "writer.seal")
        assert not os.path.exists(seal_path), "missing output was sealed"
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_action_zero_byte_marker_commits():
    """An action producing a zero-byte marker file must commit (existence-only)."""
    from husks.designs.ir import run
    tmpdir = tempfile.mkdtemp(prefix="guard-action-marker-")
    try:
        site = make_site(tmpdir)
        design = {
            "name": "guard-marker",
            "fuel": 10,
            "target": "marker",
            "site": site,
            "site_inputs": ["input.txt"],
            "rules": [
                {
                    "name": "marker",
                    "kind": "action",
                    "inputs": ["input.txt"],
                    "outputs": [".complete"],
                    "run": "touch .complete",
                },
            ],
        }
        S = run(design)
        assert S["status"] == "committed", (
            f"action zero-byte marker should commit, got: {S['status']}"
        )
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_oracle_empty_output_halts():
    """An oracle producing a zero-byte output must halt."""
    from husks.designs.ir import run
    from husks.build import site_path
    from pathlib import Path
    tmpdir = tempfile.mkdtemp(prefix="guard-oracle-empty-")
    try:
        site = make_site(tmpdir)

        def _empty_oracle(S, rule_name, recipe, outputs):
            for o in outputs:
                p = Path(site_path(S, o))
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_bytes(b"")
            return {"tokens_in": 0, "tokens_out": 0, "cost_usd": 0.0, "fuel_steps": 1}

        design = {
            "name": "guard-oracle-empty",
            "fuel": 10,
            "target": "gen",
            "site": site,
            "site_inputs": ["input.txt"],
            "oracle_backend": _empty_oracle,
            "rules": [
                {
                    "name": "gen",
                    "kind": "oracle",
                    "inputs": ["input.txt"],
                    "outputs": ["result.txt"],
                    "prompt": "Write result.",
                    "tools": ["write-file"],
                    "fuel": 3,
                },
            ],
        }
        S = run(design)
        assert S["status"] == "halted"
        seal_path = os.path.join(site, ".traces", "gen.seal")
        assert not os.path.exists(seal_path), "empty oracle output was sealed"
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_oracle_missing_output_halts():
    """An oracle that never writes its declared output must halt."""
    from husks.designs.ir import run
    tmpdir = tempfile.mkdtemp(prefix="guard-oracle-missing-")
    try:
        site = make_site(tmpdir)
        design = {
            "name": "guard-oracle-missing",
            "fuel": 10,
            "target": "gen",
            "site": site,
            "site_inputs": ["input.txt"],
            "oracle_backend": _noop_oracle,
            "rules": [
                {
                    "name": "gen",
                    "kind": "oracle",
                    "inputs": ["input.txt"],
                    "outputs": ["result.txt"],
                    "prompt": "Write result.",
                    "tools": ["write-file"],
                    "fuel": 3,
                },
            ],
        }
        S = run(design)
        assert S["status"] == "halted"
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)
