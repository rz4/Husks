"""
test_5_build_verify.py -- Engine root == reader root.

The gate passes when the engine's CSE seal computation matches
the independent reader's recomputation from the serialized husk
and site files.
"""

import os
import shutil
import tempfile

import pytest

from husks.core import recompute_root


def _make_site(tmpdir):
    """Create a site directory and an inputs directory with known input files."""
    site = os.path.join(tmpdir, "site")
    os.makedirs(site, exist_ok=True)
    inputs_dir = os.path.join(tmpdir, "inputs")
    os.makedirs(inputs_dir, exist_ok=True)
    with open(os.path.join(inputs_dir, "greeting.txt"), "wb") as f:
        f.write(b"Hello, world!\n")
    with open(os.path.join(inputs_dir, "config.txt"), "wb") as f:
        f.write(b"mode=test\n")
    return site


def _make_design(site):
    """Build a design with two rules: action (greet) -> oracle (combine)."""
    inputs_dir = os.path.join(os.path.dirname(site), "inputs")
    return {
        "name": "phase1-test",
        "fuel": 20,
        "target": "combine",
        "site": site,
        "site_inputs": {
            "greeting.txt": os.path.join(inputs_dir, "greeting.txt"),
            "config.txt": os.path.join(inputs_dir, "config.txt"),
        },
        "rules": [
            {
                "name": "greet",
                "kind": "action",
                "inputs": ["config.txt", "greeting.txt"],
                "outputs": ["hello.txt"],
            },
            {
                "name": "combine",
                "kind": "oracle",
                "inputs": ["hello.txt"],
                "outputs": ["result.txt"],
                "prompt": "Combine the files.",
                "tools": ["read-file", "write-file"],
                "fuel": 3,
            },
        ],
    }


def _run_build(design):
    """Run a build via design.run() and return the store."""
    from husks.designs.ir import run
    return run(design)


@pytest.mark.alpha


def test_engine_root_equals_reader_root():
    """Engine-computed build-root == core-reader build-root on a live build."""
    tmpdir = tempfile.mkdtemp(prefix="phase1-gate-")
    try:
        site = _make_site(tmpdir)
        design = _make_design(site)
        S = _run_build(design)

        assert S["status"] == "committed", f"build failed: {S.get('value')}"
        assert "build-root" in S and S["build-root"] is not None, (
            "build-root not computed"
        )

        engine_root = S["build-root"]

        # Read the .husk file the engine wrote
        husk_path = os.path.join(site, "phase1-test.husk")
        assert os.path.isfile(husk_path), f".husk file not found at {husk_path}"

        with open(husk_path, "rb") as f:
            husk_bytes = f.read()

        # Recompute root via independent reader
        reader_root = recompute_root(husk_bytes, site)

        assert engine_root == reader_root, (
            f"build-root mismatch:\n"
            f"  engine: {engine_root}\n"
            f"  reader: {reader_root}"
        )
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


@pytest.mark.alpha


def test_seal_determinism():
    """Running the same build twice produces the same root."""
    tmpdir = tempfile.mkdtemp(prefix="phase1-determ-")
    try:
        site = _make_site(tmpdir)
        design = _make_design(site)
        S1 = _run_build(design)
        assert S1["status"] == "committed"
        root1 = S1["build-root"]

        # Wipe .traces to force a fresh rebuild
        traces_dir = os.path.join(site, ".traces")
        if os.path.isdir(traces_dir):
            shutil.rmtree(traces_dir)

        S2 = _run_build(design)
        assert S2["status"] == "committed"
        root2 = S2["build-root"]

        assert root1 == root2, (
            f"non-deterministic roots:\n"
            f"  run 1: {root1}\n"
            f"  run 2: {root2}"
        )
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


@pytest.mark.alpha


def test_freshness_skip():
    """Second run skips execution (seals fresh), same root."""
    tmpdir = tempfile.mkdtemp(prefix="phase1-fresh-")
    try:
        site = _make_site(tmpdir)
        design = _make_design(site)
        S1 = _run_build(design)
        assert S1["status"] == "committed"
        root1 = S1["build-root"]

        # Second run -- seals should be fresh, no re-execution
        S2 = _run_build(design)
        assert S2["status"] == "committed"
        root2 = S2["build-root"]

        assert root1 == root2, (
            f"freshness skip root mismatch:\n"
            f"  run 1: {root1}\n"
            f"  run 2: {root2}"
        )

        # Verify some rules were sealed (skipped) in second run
        sealed_events = [e for e in S2["trace"] if e.get("event") == "sealed"]
        assert len(sealed_events) > 0, "expected some rules to be sealed on second run"
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


@pytest.mark.alpha


def test_cond_file_nonempty_branching():
    """cond with file-nonempty predicate branches correctly from JSON IR."""
    tmpdir = tempfile.mkdtemp(prefix="phase1-cond-")
    try:
        site = os.path.join(tmpdir, "site")
        os.makedirs(site, exist_ok=True)
        inputs_dir = os.path.join(tmpdir, "inputs")
        os.makedirs(inputs_dir, exist_ok=True)

        # ── true branch: file exists and is non-empty ──
        with open(os.path.join(inputs_dir, "data.txt"), "w") as f:
            f.write("content\n")

        design = {
            "name": "cond-test",
            "fuel": 10,
            "target": "decide",
            "site": site,
            "site_inputs": {"data.txt": os.path.join(inputs_dir, "data.txt")},
            "rules": [
                {"name": "yes", "kind": "commit", "value": "present"},
                {"name": "no", "kind": "halt", "reason": "missing"},
                {"name": "decide", "kind": "cond",
                 "predicate": "file-nonempty:data.txt",
                 "then": "yes", "else": "no"},
            ],
        }

        from husks.designs.ir import check, run
        errs = check(design)
        assert errs == [], f"check errors: {errs}"

        S = run(design)
        assert S["status"] == "committed", f"expected commit, got {S['status']}"
        assert S["value"] == "present"

        # ── false branch: file exists but is empty ──
        with open(os.path.join(inputs_dir, "data.txt"), "w") as f:
            pass  # empty file

        # Wipe traces to force re-evaluation
        traces = os.path.join(site, ".traces")
        if os.path.isdir(traces):
            shutil.rmtree(traces)
        husk = os.path.join(site, "cond-test.husk")
        if os.path.exists(husk):
            os.remove(husk)

        S2 = run(design)
        assert S2["status"] == "halted", f"expected halt, got {S2['status']}"

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


@pytest.mark.alpha


def test_staleness_changes_root():
    """Modifying an input file changes the root."""
    tmpdir = tempfile.mkdtemp(prefix="phase1-stale-")
    try:
        site = _make_site(tmpdir)
        design = _make_design(site)
        S1 = _run_build(design)
        assert S1["status"] == "committed"
        root1 = S1["build-root"]

        # Modify an input file (in the inputs dir, which is symlinked into site)
        inputs_dir = os.path.join(tmpdir, "inputs")
        with open(os.path.join(inputs_dir, "config.txt"), "wb") as f:
            f.write(b"mode=changed\n")

        S2 = _run_build(design)
        assert S2["status"] == "committed"
        root2 = S2["build-root"]

        assert root1 != root2, (
            f"root should change when input changes, but both are: {root1}"
        )
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


# ── Import tests ──────────────────────────────────────────────


@pytest.mark.alpha


def test_imports_readable():
    """An oracle/action can read files from a read-only import."""
    tmpdir = tempfile.mkdtemp(prefix="import-read-")
    try:
        # External directory with a file
        ext_dir = os.path.join(tmpdir, "external")
        os.makedirs(ext_dir)
        with open(os.path.join(ext_dir, "data.csv"), "w") as f:
            f.write("a,b,c\n1,2,3\n")

        site = os.path.join(tmpdir, "site")
        os.makedirs(site)

        design = {
            "name": "import-read-test",
            "fuel": 10,
            "target": "use-ref",
            "site": site,
            "imports": {
                "ref": ext_dir,
            },
            "rules": [
                {
                    "name": "use-ref",
                    "kind": "action",
                    "inputs": ["ref/data.csv"],
                    "outputs": ["result.txt"],
                    "action_fn": _read_import_action,
                },
            ],
        }

        from husks.designs.ir import run
        S = run(design)
        assert S["status"] == "committed", f"build failed: {S.get('value')}"

        # Verify the action actually read the imported file
        result_path = os.path.join(site, "result.txt")
        assert os.path.isfile(result_path)
        content = open(result_path).read()
        assert "a,b,c" in content

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def _read_import_action(S):
    """Action that reads from an imported path and writes a result."""
    from husks.build import read_path, write_path, write_text
    data = open(read_path(S, "ref/data.csv")).read()
    write_text(write_path(S, "result.txt"), f"read: {data}")


@pytest.mark.alpha


def test_imports_write_blocked():
    """Writing to an imported (read-only) path is rejected by the sandbox."""
    tmpdir = tempfile.mkdtemp(prefix="import-write-")
    try:
        ext_dir = os.path.join(tmpdir, "external")
        os.makedirs(ext_dir)
        with open(os.path.join(ext_dir, "data.csv"), "w") as f:
            f.write("a,b,c\n")

        site = os.path.join(tmpdir, "site")
        os.makedirs(site)

        from husks.oracle.tools import set_site_root, sandbox

        # Simulate: site root with an import symlink
        link = os.path.join(site, "ref")
        os.symlink(ext_dir, link)

        resolved_ext = str(os.path.realpath(ext_dir))
        set_site_root(site, readonly=[resolved_ext])

        target = os.path.join(site, "ref", "data.csv")

        # Read should succeed
        p = sandbox(target, write=False)
        assert p.exists()

        # Write should fail
        import pytest
        with pytest.raises(ValueError, match="write denied"):
            sandbox(target, write=True)

        # Clean up sandbox state
        set_site_root(None)

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


@pytest.mark.alpha


def test_imports_build_succeeds():
    """End-to-end: imports declared, build commits, symlink exists."""
    tmpdir = tempfile.mkdtemp(prefix="import-e2e-")
    try:
        ext_dir = os.path.join(tmpdir, "external")
        os.makedirs(ext_dir)
        with open(os.path.join(ext_dir, "info.txt"), "w") as f:
            f.write("external info\n")

        site = os.path.join(tmpdir, "site")
        os.makedirs(site)

        design = {
            "name": "import-e2e",
            "fuel": 10,
            "target": "done",
            "site": site,
            "imports": {
                "ext": ext_dir,
            },
            "rules": [
                {"name": "done", "kind": "commit", "value": "ok"},
            ],
        }

        from husks.designs.ir import run
        S = run(design)
        assert S["status"] == "committed"

        # Symlink was created
        link = os.path.join(site, "ext")
        assert os.path.islink(link)
        assert os.path.isfile(os.path.join(link, "info.txt"))

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


# ── Multi-target tests ─────────────────────────────────────────


@pytest.mark.alpha


def test_multi_target_build():
    """Multi-target design with two independent commit rules builds successfully."""
    tmpdir = tempfile.mkdtemp(prefix="multi-target-")
    try:
        site = os.path.join(tmpdir, "site")
        os.makedirs(site)

        design = {
            "name": "multi-out",
            "fuel": 10,
            "targets": ["report", "archive"],
            "site": site,
            "rules": [
                {"name": "report", "kind": "commit", "value": "done-report"},
                {"name": "archive", "kind": "commit", "value": "done-archive"},
            ],
        }

        from husks.designs.ir import check, run
        errs = check(design)
        assert errs == [], f"check errors: {errs}"

        S = run(design)
        assert S["status"] == "committed", f"build failed: {S.get('value')}"
        assert S["build-root"] is not None, "build-root not computed"
        assert "target-roots" in S, "target-roots not set for multi-target build"
        assert len(S["target-roots"]) == 2

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


@pytest.mark.alpha


def test_multi_target_engine_equals_reader_root():
    """Engine root == reader root for multi-target builds."""
    tmpdir = tempfile.mkdtemp(prefix="multi-target-verify-")
    try:
        site = os.path.join(tmpdir, "site")
        os.makedirs(site)
        inputs_dir = os.path.join(tmpdir, "inputs")
        os.makedirs(inputs_dir)
        with open(os.path.join(inputs_dir, "input.txt"), "w") as f:
            f.write("data\n")

        design = {
            "name": "multi-verify",
            "fuel": 10,
            "targets": ["done-a", "done-b"],
            "site": site,
            "site_inputs": {"input.txt": os.path.join(inputs_dir, "input.txt")},
            "rules": [
                {
                    "name": "step",
                    "kind": "action",
                    "inputs": ["input.txt"],
                    "outputs": ["out.txt"],
                },
                {"name": "done-a", "kind": "commit", "value": "a-ok"},
                {"name": "done-b", "kind": "commit", "value": "b-ok"},
            ],
        }

        from husks.designs.ir import run
        S = run(design)
        assert S["status"] == "committed"
        engine_root = S["build-root"]
        assert engine_root is not None

        husk_path = os.path.join(site, "multi-verify.husk")
        assert os.path.isfile(husk_path)

        with open(husk_path, "rb") as f:
            husk_bytes = f.read()

        reader_root = recompute_root(husk_bytes, site)
        assert engine_root == reader_root, (
            f"multi-target root mismatch:\n"
            f"  engine: {engine_root}\n"
            f"  reader: {reader_root}"
        )

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


@pytest.mark.alpha


def test_single_target_string_backward_compat():
    """Single 'target' (string) still works after multi-target changes."""
    tmpdir = tempfile.mkdtemp(prefix="compat-target-")
    try:
        site = os.path.join(tmpdir, "site")
        os.makedirs(site)

        design = {
            "name": "compat-test",
            "fuel": 10,
            "target": "done",
            "site": site,
            "rules": [
                {"name": "done", "kind": "commit", "value": "ok"},
            ],
        }

        from husks.designs.ir import check, run
        errs = check(design)
        assert errs == [], f"check errors: {errs}"

        S = run(design)
        assert S["status"] == "committed"
        assert S["build-root"] is not None

        # Verify engine == reader
        husk_path = os.path.join(site, "compat-test.husk")
        assert os.path.isfile(husk_path)
        with open(husk_path, "rb") as f:
            husk_bytes = f.read()
        reader_root = recompute_root(husk_bytes, site)
        assert S["build-root"] == reader_root

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


@pytest.mark.alpha


def test_different_shell_commands_different_seal():
    """Two shell actions with different commands must produce different seals."""
    tmpdir = tempfile.mkdtemp(prefix="shell-seal-")
    try:
        from husks.designs.ir import run

        # Build A: shell command "echo alpha"
        site_a = os.path.join(tmpdir, "site-a")
        os.makedirs(site_a)
        design_a = {
            "name": "cmd-a",
            "fuel": 10,
            "target": "step",
            "site": site_a,
            "rules": [
                {
                    "name": "step",
                    "kind": "action",
                    "inputs": [],
                    "outputs": ["out.txt"],
                    "run": "echo alpha > out.txt",
                },
            ],
        }
        S_a = run(design_a)
        assert S_a["status"] == "committed"
        root_a = S_a["build-root"]

        # Build B: shell command "echo beta"
        site_b = os.path.join(tmpdir, "site-b")
        os.makedirs(site_b)
        design_b = {
            "name": "cmd-b",
            "fuel": 10,
            "target": "step",
            "site": site_b,
            "rules": [
                {
                    "name": "step",
                    "kind": "action",
                    "inputs": [],
                    "outputs": ["out.txt"],
                    "run": "echo beta > out.txt",
                },
            ],
        }
        S_b = run(design_b)
        assert S_b["status"] == "committed"
        root_b = S_b["build-root"]

        assert root_a != root_b, (
            f"different shell commands produced identical build roots: {root_a}"
        )
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


@pytest.mark.alpha


def test_imports_check_validation():
    """check() catches bad imports: relative paths, collisions."""
    from husks.designs.ir import check

    # Relative path
    d = {
        "name": "bad-import",
        "fuel": 10,
        "target": "ok",
        "imports": {"ref": "relative/path"},
        "rules": [
            {"name": "ok", "kind": "commit", "value": "done"},
        ],
    }
    errs = check(d)
    assert any("absolute" in e for e in errs), f"expected absolute-path error, got: {errs}"

    # Collision with rule output
    d2 = {
        "name": "collision-import",
        "fuel": 10,
        "target": "gen",
        "imports": {"out.txt": "/tmp/something"},
        "rules": [
            {
                "name": "gen",
                "kind": "action",
                "inputs": [],
                "outputs": ["out.txt"],
            },
        ],
    }
    errs2 = check(d2)
    assert any("collides" in e for e in errs2), f"expected collision error, got: {errs2}"
