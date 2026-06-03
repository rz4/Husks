"""
test_version_terminology.py -- Beta Gate C5: CSE version language alignment.

Documents and tests the three independent version schemes used in Husks:
1. CSE wire version (CSE_VERSION, currently b"2")
2. Seal format version (stored in seal JSON as "v": 1)
3. Recipe identity scheme (implicitly "v2" in comments)

These versions are independent and coordinated only when necessary.
"""

import tempfile
import shutil
import json
from pathlib import Path


def test_cse_wire_version_is_two():
    """CSE wire version is currently 2."""
    from husks.core import CSE_VERSION

    assert CSE_VERSION == b"2", "CSE wire version should be 2"


def test_husk_file_contains_cse_version():
    """.husk files embed CSE_VERSION in their structure."""
    from husks.build import build, rule, action
    from husks.core import parse

    tmpdir = tempfile.mkdtemp(prefix="c5-husk-version-")
    try:
        site = Path(tmpdir) / "site"
        site.mkdir()

        def write_output(S):
            from husks.build.site import write_path
            Path(write_path(S, "out.txt")).write_text("test\n")

        node = rule("test", outputs=["out.txt"], recipe=action(write_output))
        S = build("demo", 10, node, site=str(site))

        assert S["status"] == "committed"

        # Read .husk file and parse it
        husk_path = site / "demo.husk"
        husk_bytes = husk_path.read_bytes()
        husk_tree = parse(husk_bytes)

        # Structure: (husk <version> <build-form>)
        assert husk_tree[0] == b"husk", ".husk file should start with 'husk' tag"
        assert husk_tree[1] == b"2", ".husk file should contain CSE version 2"

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_seal_format_version_is_one():
    """Seal files store format version 1 in JSON."""
    from husks.build import build, rule, action
    from husks.manifest import read_seal

    tmpdir = tempfile.mkdtemp(prefix="c5-seal-version-")
    try:
        site = Path(tmpdir) / "site"
        site.mkdir()

        def write_output(S):
            from husks.build.site import write_path
            Path(write_path(S, "out.txt")).write_text("test\n")

        node = rule("worker", outputs=["out.txt"], recipe=action(write_output))
        S = build("demo", 10, node, site=str(site))

        assert S["status"] == "committed"

        # Read seal file
        seal = read_seal(str(site), "worker")
        assert seal is not None, "seal should exist"
        assert "v" in seal, "seal should have version field"
        assert seal["v"] == 1, "seal format version should be 1"

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_seal_format_independent_of_cse_version():
    """Seal format v1 works with CSE wire version 2."""
    from husks.build import build, rule, action
    from husks.manifest import read_seal
    from husks.core import CSE_VERSION, parse

    tmpdir = tempfile.mkdtemp(prefix="c5-independence-")
    try:
        site = Path(tmpdir) / "site"
        site.mkdir()

        def write_output(S):
            from husks.build.site import write_path
            Path(write_path(S, "out.txt")).write_text("data\n")

        node = rule("test", outputs=["out.txt"], recipe=action(write_output))
        S = build("demo", 10, node, site=str(site))

        assert S["status"] == "committed"

        # Check CSE version
        husk_bytes = (site / "demo.husk").read_bytes()
        husk_tree = parse(husk_bytes)
        cse_version = husk_tree[1]

        # Check seal version
        seal = read_seal(str(site), "test")
        seal_version = seal["v"]

        # Versions are independent
        assert cse_version == CSE_VERSION == b"2", "CSE wire version is 2"
        assert seal_version == 1, "seal format version is 1"
        # Both work together without conflict

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_recipe_identity_v2_uses_behavior_digest():
    """Recipe identity v2 uses behavior digest for callable actions."""
    from husks.build.identity import recipe_to_cse, _fn_behavior_digest
    from husks.core import recipe_digest

    def my_action(S):
        """Test action function."""
        pass

    recipe = {
        "type": "action",
        "fn": my_action,
    }

    cse_form = recipe_to_cse(recipe)

    # Should be [b"action", <behavior-digest>]
    assert isinstance(cse_form, list)
    assert cse_form[0] == b"action"

    # Second element should be the behavior digest
    expected_digest = _fn_behavior_digest(my_action)
    assert cse_form[1] == expected_digest.encode()


def test_shell_action_identity_independent_of_outputs():
    """Shell action identity is command string only (recipe identity v2)."""
    from husks.build.identity import recipe_to_cse
    from husks.core import recipe_digest
    from husks.design.locke import _make_shell_action

    # Same command, different output names (outputs don't affect recipe)
    fn_a = _make_shell_action("echo hello", ["out1.txt"])
    fn_b = _make_shell_action("echo hello", ["out2.txt"])

    recipe_a = {"type": "action", "fn": fn_a}
    recipe_b = {"type": "action", "fn": fn_b}

    rd_a = recipe_digest(recipe_to_cse(recipe_a))
    rd_b = recipe_digest(recipe_to_cse(recipe_b))

    # Recipe identity v2: shell command is the sole identity
    assert rd_a == rd_b, "same command should have same recipe digest"


def test_version_constants_documented():
    """Version constants have clear documentation."""
    from husks.core import CSE_VERSION, ABSENT, NIL
    from husks.manifest import SUPPORTED_SEAL_VERSIONS, SUPPORTED_MANIFEST_SCHEMAS

    # Core constants exist
    assert CSE_VERSION is not None
    assert ABSENT is not None
    assert NIL is not None

    # Seal versions defined
    assert SUPPORTED_SEAL_VERSIONS == {1}, "seal format v1 is supported"

    # Manifest schemas defined
    assert "husks.build.manifest.v1" in SUPPORTED_MANIFEST_SCHEMAS


def test_versions_coordinated_in_build():
    """All version schemes work together in a complete build."""
    from husks.build import build, rule, action
    from husks.manifest import read_seal, read_manifest
    from husks.core import parse, recompute_root

    tmpdir = tempfile.mkdtemp(prefix="c5-coordinated-")
    try:
        site = Path(tmpdir) / "site"
        site.mkdir()

        def write_output(S):
            from husks.build.site import write_path
            Path(write_path(S, "output.txt")).write_text("result\n")

        node = rule("worker", outputs=["output.txt"], recipe=action(write_output))
        S = build("demo", 10, node, site=str(site))

        assert S["status"] == "committed"

        # Verify CSE wire version in .husk
        husk_bytes = (site / "demo.husk").read_bytes()
        husk_tree = parse(husk_bytes)
        assert husk_tree[1] == b"2"

        # Verify seal format version
        seal = read_seal(str(site), "worker")
        assert seal["v"] == 1

        # Verify manifest schema version
        manifest = read_manifest(str(site))
        assert manifest["schema"] == "husks.build.manifest.v1"

        # Verify root recomputation works across versions
        original_root = S["build-root"]
        recomputed = recompute_root(husk_bytes, str(site))
        assert recomputed == original_root, "all versions coordinate correctly"

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)
