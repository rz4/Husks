"""Test that recompute_root() rejects malicious paths in .husk files."""

import tempfile
import shutil
from pathlib import Path
import pytest


def test_recompute_root_rejects_absolute_path_in_inputs():
    """recompute_root must reject .husk files with absolute input paths.

    Security: A malicious .husk could specify inputs=["/etc/passwd"] to
    cause verification to read arbitrary files. This must be rejected.
    """
    from husks.core import encode, atom, recompute_root

    tmpdir = tempfile.mkdtemp(prefix="husk-abs-input-")
    try:
        site = Path(tmpdir) / "site"
        site.mkdir()

        # Craft a malicious .husk with absolute path in inputs
        malicious_husk = [
            b"husk",
            b"2",
            [
                b"build",
                atom("evil"),
                atom("10"),
                [
                    b"rule",
                    atom("test"),
                    [b"action", atom("noop")],
                    [atom("/etc/passwd")],  # ABSOLUTE path in inputs!
                    [],  # no outputs
                ]
            ]
        ]

        husk_bytes = encode(malicious_husk)

        # Attempting to verify should raise ValueError
        with pytest.raises(ValueError, match="absolute path in .husk"):
            recompute_root(husk_bytes, str(site))

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_recompute_root_rejects_traversal_path_in_outputs():
    """recompute_root must reject .husk files with traversal output paths.

    Security: A malicious .husk could specify outputs=["../../secret"] to
    cause verification to read outside the site directory.
    """
    from husks.core import encode, atom, recompute_root

    tmpdir = tempfile.mkdtemp(prefix="husk-traversal-output-")
    try:
        site = Path(tmpdir) / "site"
        site.mkdir()

        # Craft a malicious .husk with traversal path in outputs
        # Structure: (husk version (build name fuel (rule name recipe (inputs) (outputs))))
        malicious_husk = [
            b"husk",
            b"2",
            [
                b"build",
                atom("evil"),
                atom("10"),
                [
                    b"rule",
                    atom("test"),
                    [b"action", atom("noop")],
                    [],  # no inputs
                    [atom("../secret.txt")],  # TRAVERSAL in outputs!
                ]
            ]
        ]

        husk_bytes = encode(malicious_husk)

        # Should reject traversal path
        with pytest.raises(ValueError, match="path traversal in .husk"):
            recompute_root(husk_bytes, str(site))

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_recompute_root_accepts_valid_relative_paths():
    """recompute_root should accept normal relative paths."""
    from husks.build import build, rule
    from husks.core import recompute_root

    tmpdir = tempfile.mkdtemp(prefix="husk-valid-paths-")
    try:
        site = Path(tmpdir) / "site"
        site.mkdir()

        # Create simple build with flat paths (no subdirectories)
        (site / "input.txt").write_text("data\n")
        node = rule(
            "test",
            inputs=["input.txt"],
            outputs=["output.txt"],
            run="cp input.txt output.txt",
        )
        S = build("test", 10, node, site=str(site))
        assert S["status"] == "committed"

        # Verify should succeed with valid relative paths
        husk_bytes = (site / "test.husk").read_bytes()
        root = recompute_root(husk_bytes, str(site))

        # Should match the build-root
        assert root == S["build-root"]

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_validate_husk_path_rejects_various_attacks():
    """Test _validate_husk_path helper rejects all attack patterns."""
    from husks.core import _validate_husk_path

    # Valid paths should pass
    _validate_husk_path("input.txt")
    _validate_husk_path("subdir/input.txt")
    _validate_husk_path("a/b/c/file.txt")

    # Absolute paths should fail
    with pytest.raises(ValueError, match="absolute path"):
        _validate_husk_path("/etc/passwd")

    with pytest.raises(ValueError, match="absolute path"):
        _validate_husk_path("/tmp/foo")

    # Traversal paths should fail
    with pytest.raises(ValueError, match="path traversal"):
        _validate_husk_path("../secret")

    with pytest.raises(ValueError, match="path traversal"):
        _validate_husk_path("foo/../../bar")

    with pytest.raises(ValueError, match="path traversal"):
        _validate_husk_path("../../etc/passwd")

    # Empty path should fail
    with pytest.raises(ValueError, match="empty path"):
        _validate_husk_path("")


def test_recompute_root_with_windows_absolute_path():
    """Test that Windows-style absolute paths are also rejected."""
    from husks.core import _validate_husk_path
    import os

    # Only test on actual Windows systems
    if os.name == 'nt':
        with pytest.raises(ValueError, match="absolute path"):
            _validate_husk_path("C:\\Windows\\System32\\config")

        with pytest.raises(ValueError, match="absolute path"):
            _validate_husk_path("C:/Windows/System32/config")
    else:
        # On Unix, Windows paths are not considered absolute, so skip
        pytest.skip("Windows path test only runs on Windows")


def test_json_design_rejects_traces_directory():
    """JSON designs must reject .traces as input or output.

    Security: .traces is a reserved internal directory for seal metadata.
    Rules must not be allowed to write to or depend on .traces.
    """
    from husks.designs.ir import check

    design = {
        "name": "evil-traces",
        "fuel": 10,
        "target": "hack",
        "rules": [
            {
                "name": "hack",
                "kind": "action",
                "outputs": [".traces/fake-seal"],
                "run": "echo evil > .traces/fake-seal",
            }
        ],
    }

    errors = check(design)
    assert any("reserved" in err.lower() for err in errors), \
        f"Expected rejection of .traces path, got: {errors}"


def test_json_design_rejects_husk_files():
    """JSON designs must reject .husk files as outputs.

    Security: .husk files are generated by the build system for
    verification. Rules must not be allowed to overwrite them.
    """
    from husks.designs.ir import check

    design = {
        "name": "evil-husk",
        "fuel": 10,
        "target": "fake",
        "rules": [
            {
                "name": "fake",
                "kind": "action",
                "outputs": ["evil.husk"],
                "run": "echo fake > evil.husk",
            }
        ],
    }

    errors = check(design)
    assert any(".husk" in err.lower() for err in errors), \
        f"Expected rejection of .husk file, got: {errors}"


def test_json_design_rejects_husks_directory():
    """JSON designs must reject .husks as input or output.

    Security: .husks is a reserved internal directory (if used).
    Rules must not be allowed to write to or depend on .husks.
    """
    from husks.designs.ir import check

    design = {
        "name": "evil-husks",
        "fuel": 10,
        "target": "tamper",
        "rules": [
            {
                "name": "tamper",
                "kind": "action",
                "outputs": [".husks/metadata"],
                "run": "echo evil > .husks/metadata",
            }
        ],
    }

    errors = check(design)
    assert any("reserved" in err.lower() for err in errors), \
        f"Expected rejection of .husks path, got: {errors}"


def test_json_design_allows_other_hidden_paths():
    """JSON designs should allow hidden files/dirs except .traces and .husks.

    Only .traces and .husks are reserved. Other hidden paths like .complete,
    .gitignore, data/.cache are legitimate user artifacts.
    """
    from husks.designs.ir import check

    # Test top-level hidden file (.complete is common marker)
    design1 = {
        "name": "hidden-marker",
        "fuel": 10,
        "target": "gen",
        "rules": [
            {
                "name": "gen",
                "kind": "action",
                "outputs": [".complete"],
                "run": "touch .complete",
            }
        ],
    }

    errors = check(design1)
    assert len(errors) == 0, f"Should allow .complete, got: {errors}"

    # Test nested hidden path
    design2 = {
        "name": "nested-hidden",
        "fuel": 10,
        "target": "gen",
        "rules": [
            {
                "name": "gen",
                "kind": "action",
                "outputs": ["data/.cache"],
                "run": "mkdir -p data && touch data/.cache",
            }
        ],
    }

    errors = check(design2)
    assert len(errors) == 0, f"Should allow nested hidden paths, got: {errors}"


def test_husk_verification_rejects_traces_in_outputs():
    """Husk verification must reject .traces in output paths.

    A malicious .husk could claim outputs=[".traces/seal"] to bypass
    verification. This must be rejected during recompute_root.
    """
    from husks.core import encode, atom, recompute_root

    tmpdir = tempfile.mkdtemp(prefix="husk-traces-output-")
    try:
        site = Path(tmpdir) / "site"
        site.mkdir()

        malicious_husk = [
            b"husk",
            b"2",
            [
                b"build",
                atom("evil"),
                atom("10"),
                [
                    b"rule",
                    atom("hack"),
                    [b"action", atom("noop")],
                    [],  # no inputs
                    [atom(".traces/fake.seal")],  # RESERVED path!
                ]
            ]
        ]

        husk_bytes = encode(malicious_husk)

        with pytest.raises(ValueError, match="reserved path in .husk"):
            recompute_root(husk_bytes, str(site))

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_husk_verification_rejects_husk_files():
    """Husk verification must reject .husk files in inputs/outputs.

    A malicious .husk could reference other .husk files to create
    circular dependencies or tamper with verification.
    """
    from husks.core import encode, atom, recompute_root

    tmpdir = tempfile.mkdtemp(prefix="husk-file-ref-")
    try:
        site = Path(tmpdir) / "site"
        site.mkdir()

        malicious_husk = [
            b"husk",
            b"2",
            [
                b"build",
                atom("evil"),
                atom("10"),
                [
                    b"rule",
                    atom("overwrite"),
                    [b"action", atom("noop")],
                    [],
                    [atom("build.husk")],  # HUSK file in outputs!
                ]
            ]
        ]

        husk_bytes = encode(malicious_husk)

        with pytest.raises(ValueError, match=".husk file in .husk"):
            recompute_root(husk_bytes, str(site))

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_json_design_rejects_rule_name_with_slash():
    """JSON designs must reject rule names containing path separators.

    Security: Rule names are used to construct .traces/{name}.seal paths.
    A name like "evil/file" would create subdirectories in .traces/.
    """
    from husks.designs.ir import check

    design = {
        "name": "path-injection",
        "fuel": 10,
        "target": "evil/rule",
        "rules": [
            {
                "name": "evil/rule",
                "kind": "action",
                "outputs": ["output.txt"],
                "run": "echo test > output.txt",
            }
        ],
    }

    errors = check(design)
    assert any("path separator" in err.lower() for err in errors), \
        f"Expected rejection of rule name with /, got: {errors}"


def test_json_design_rejects_rule_name_with_dotdot():
    """JSON designs must reject rule names containing '..'.

    Security: A rule name like "..evil" could attempt path traversal
    when constructing .traces/ paths.
    """
    from husks.designs.ir import check

    design = {
        "name": "dotdot-injection",
        "fuel": 10,
        "target": "..evil",
        "rules": [
            {
                "name": "..evil",
                "kind": "action",
                "outputs": ["output.txt"],
                "run": "echo test > output.txt",
            }
        ],
    }

    errors = check(design)
    assert any(".." in err for err in errors), \
        f"Expected rejection of rule name with .., got: {errors}"


def test_json_design_rejects_reserved_rule_names():
    """JSON designs must reject rule names that collide with internal files.

    Security: A rule named "build.manifest" would overwrite the build
    manifest file in .traces/.
    """
    from husks.designs.ir import check

    design = {
        "name": "reserved-name",
        "fuel": 10,
        "target": "build.manifest",
        "rules": [
            {
                "name": "build.manifest",
                "kind": "action",
                "outputs": ["output.txt"],
                "run": "echo test > output.txt",
            }
        ],
    }

    errors = check(design)
    assert any("collides with internal" in err.lower() for err in errors), \
        f"Expected rejection of reserved rule name, got: {errors}"


def test_json_design_rejects_rule_name_with_control_chars():
    """JSON designs must reject rule names with control characters.

    Security: Control characters in rule names could cause terminal
    injection or file system issues.
    """
    from husks.designs.ir import check

    # Newline in rule name
    design = {
        "name": "control-char",
        "fuel": 10,
        "target": "evil\nrule",
        "rules": [
            {
                "name": "evil\nrule",
                "kind": "action",
                "outputs": ["output.txt"],
                "run": "echo test > output.txt",
            }
        ],
    }

    errors = check(design)
    assert any("control character" in err.lower() for err in errors), \
        f"Expected rejection of control char in rule name, got: {errors}"


def test_husk_verification_rejects_rule_name_with_slash():
    """Husk verification must reject rule names with path separators.

    A malicious .husk could use rule names like "subdir/evil" to
    create arbitrary directory structures in .traces/.
    """
    from husks.core import encode, atom, recompute_root

    tmpdir = tempfile.mkdtemp(prefix="husk-rule-slash-")
    try:
        site = Path(tmpdir) / "site"
        site.mkdir()

        malicious_husk = [
            b"husk",
            b"2",
            [
                b"build",
                atom("evil"),
                atom("10"),
                [
                    b"rule",
                    atom("evil/subdir"),  # Path separator in rule name!
                    [b"action", atom("noop")],
                    [],
                    [atom("output.txt")],
                ]
            ]
        ]

        husk_bytes = encode(malicious_husk)

        with pytest.raises(ValueError, match="path separator in .husk"):
            recompute_root(husk_bytes, str(site))

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_husk_verification_rejects_reserved_rule_names():
    """Husk verification must reject reserved rule names.

    A malicious .husk with rule name "build.manifest" would collide
    with the build manifest file.
    """
    from husks.core import encode, atom, recompute_root

    tmpdir = tempfile.mkdtemp(prefix="husk-reserved-name-")
    try:
        site = Path(tmpdir) / "site"
        site.mkdir()

        malicious_husk = [
            b"husk",
            b"2",
            [
                b"build",
                atom("evil"),
                atom("10"),
                [
                    b"rule",
                    atom("build.manifest"),  # Reserved name!
                    [b"action", atom("noop")],
                    [],
                    [atom("output.txt")],
                ]
            ]
        ]

        husk_bytes = encode(malicious_husk)

        with pytest.raises(ValueError, match="collides with internal file"):
            recompute_root(husk_bytes, str(site))

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_json_design_allows_safe_rule_names():
    """JSON designs should allow safe rule names with hyphens and underscores."""
    from husks.designs.ir import check

    design = {
        "name": "safe-names",
        "fuel": 10,
        "target": "safe-rule_123",
        "rules": [
            {
                "name": "safe-rule_123",
                "kind": "action",
                "outputs": ["output.txt"],
                "run": "echo test > output.txt",
            }
        ],
    }

    errors = check(design)
    assert len(errors) == 0, f"Safe rule names should be allowed, got: {errors}"
