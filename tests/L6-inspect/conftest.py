"""conftest.py -- Fixtures for L6 inspect tests."""

import json

import pytest


@pytest.fixture
def tmp_site(tmp_path):
    """Create a temp site directory with .traces/ subdirectory."""
    traces = tmp_path / ".traces"
    traces.mkdir()
    return tmp_path


def _write_manifest(site, name="test", root="abc123", rules=None):
    """Write a valid manifest to site/.traces/build.manifest.json."""
    if rules is None:
        rules = [{"name": "w", "kind": "oracle", "outputs": ["out.txt"]}]
    manifest = {
        "schema": "husks.build.manifest.v1",
        "name": name,
        "root": root,
        "site": str(site),
        "run_id": "run-1",
        "rules": rules,
    }
    p = site / ".traces" / "build.manifest.json"
    p.write_text(json.dumps(manifest))
    return manifest


def _write_seal(site, rule_name, seal_hash="s1", recipe_digest="rd1",
                inputs=None, outputs=None):
    """Write a valid seal to site/.traces/{rule_name}.seal."""
    seal = {
        "v": 1,
        "seal": seal_hash,
        "recipe_digest": recipe_digest,
        "inputs": inputs or {},
        "outputs": outputs or {},
    }
    p = site / ".traces" / f"{rule_name}.seal"
    p.write_text(json.dumps(seal))
    return seal


def _write_history(site, rule_name, entries):
    """Write JSONL history file."""
    p = site / ".traces" / f"{rule_name}.history.jsonl"
    p.write_text("\n".join(json.dumps(e) for e in entries) + "\n")


@pytest.fixture
def write_manifest():
    return _write_manifest


@pytest.fixture
def write_seal():
    return _write_seal


@pytest.fixture
def write_history():
    return _write_history
