"""
test_oracle_empty_output.py — guard against silent sealing of empty oracle outputs.

An oracle that produces a missing or zero-byte declared output must halt the build.
Action rules are exempt: zero-byte markers (e.g. `touch .complete`) are legitimate.
"""

import os
import sys
import shutil
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))


def _make_site(tmpdir):
    site = os.path.join(tmpdir, "site")
    os.makedirs(site, exist_ok=True)
    with open(os.path.join(site, "input.txt"), "wb") as f:
        f.write(b"hello\n")
    return site


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
    """Oracle backend that writes nothing — outputs stay missing."""
    return {"tokens_in": 0, "tokens_out": 0, "cost_usd": 0.0, "fuel_steps": 1}


def test_oracle_empty_output_halts():
    """An oracle producing a zero-byte declared output must halt, not seal."""
    from husks.plan import run
    tmpdir = tempfile.mkdtemp(prefix="oracle-empty-")
    try:
        site = _make_site(tmpdir)
        plan = {
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
        S = run(plan)
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
    from husks.plan import run
    tmpdir = tempfile.mkdtemp(prefix="oracle-missing-")
    try:
        site = _make_site(tmpdir)
        plan = {
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
        S = run(plan)
        assert S["status"] == "halted", (
            f"expected halt on missing oracle output, got: {S['status']}"
        )
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_action_zero_byte_marker_commits():
    """An action producing a zero-byte marker file must still commit."""
    from husks.plan import run
    tmpdir = tempfile.mkdtemp(prefix="action-marker-")
    try:
        site = _make_site(tmpdir)
        plan = {
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
        S = run(plan)
        assert S["status"] == "committed", (
            f"action with zero-byte marker should commit, got: {S['status']}"
        )
        assert os.path.exists(os.path.join(site, ".complete")), (
            ".complete marker not found"
        )
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


if __name__ == "__main__":
    test_oracle_empty_output_halts()
    print("PASS: oracle empty output halts")
    test_oracle_missing_output_halts()
    print("PASS: oracle missing output halts")
    test_action_zero_byte_marker_commits()
    print("PASS: action zero-byte marker commits")
    print("\nAll oracle empty output tests PASSED")
