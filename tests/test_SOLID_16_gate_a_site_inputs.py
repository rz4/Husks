"""
test_site_inputs.py -- Site inputs from JSON designs.

Validates that external files referenced in site_inputs are properly
imported (symlinked) into the build site and accessible to rules.

Beta Gate A1: Make site_inputs work from JSON designs.
"""

import json
import os
import tempfile
import shutil
from pathlib import Path

import pytest

from conftest import run_husks_cli
from husks.designs.ir import from_json, run, check


def stub_oracle(S, rule_name, recipe, outputs):
    """Stub oracle backend that writes placeholder outputs."""
    from husks.build import write_path
    for o in outputs:
        output_path = write_path(S, o)
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        Path(output_path).write_text(f"# Stub output from {rule_name}\n")
    return {"tokens_in": 10, "tokens_out": 10, "cost_usd": 0.001, "fuel_steps": 1}


@pytest.mark.beta
@pytest.mark.gate_a
def test_site_inputs_list_form_in_memory():
    """site_inputs as a list imports external files into the site."""
    tmpdir = tempfile.mkdtemp(prefix="site-inputs-list-")
    try:
        # Create external files outside the site
        external_dir = Path(tmpdir) / "external"
        external_dir.mkdir()
        (external_dir / "data.txt").write_text("external data\n")
        (external_dir / "config.json").write_text('{"key": "value"}\n')

        # Create site directory (initially empty)
        site = Path(tmpdir) / "site"
        site.mkdir()

        # Design with site_inputs as a list of absolute paths
        design = {
            "name": "list-inputs",
            "fuel": 10,
            "target": "process",
            "site_inputs": [
                str(external_dir / "data.txt"),
                str(external_dir / "config.json"),
            ],
            "rules": [
                {
                    "name": "process",
                    "kind": "action",
                    "inputs": ["data.txt", "config.json"],
                    "outputs": ["result.txt"],
                    "run": "cat data.txt config.json > result.txt",
                },
            ],
        }

        # Run the build
        S = run(design, site=str(site), oracle_backend=stub_oracle)

        # Verify the build succeeded
        assert S["status"] == "committed", f"Build should succeed, got {S['status']}"

        # Verify the inputs were symlinked into the site
        assert (site / "data.txt").exists(), "data.txt should be symlinked into site"
        assert (site / "config.json").exists(), "config.json should be symlinked into site"
        assert (site / "data.txt").is_symlink(), "data.txt should be a symlink"
        assert (site / "config.json").is_symlink(), "config.json should be a symlink"

        # Verify symlinks point to the external files
        assert (site / "data.txt").resolve() == (external_dir / "data.txt").resolve()
        assert (site / "config.json").resolve() == (external_dir / "config.json").resolve()

        # Verify the rule could read the inputs
        result = (site / "result.txt").read_text()
        assert "external data" in result, "Result should contain content from data.txt"
        assert '"key": "value"' in result, "Result should contain content from config.json"

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


@pytest.mark.beta
@pytest.mark.gate_a
def test_site_inputs_dict_form_in_memory():
    """site_inputs as a dict maps local names to external paths."""
    tmpdir = tempfile.mkdtemp(prefix="site-inputs-dict-")
    try:
        # Create external files with different names
        external_dir = Path(tmpdir) / "external"
        external_dir.mkdir()
        (external_dir / "source_data.txt").write_text("source content\n")

        # Create site directory
        site = Path(tmpdir) / "site"
        site.mkdir()

        # Design with site_inputs as a dict (local_name: external_path)
        design = {
            "name": "dict-inputs",
            "fuel": 10,
            "target": "process",
            "site_inputs": {
                "input.txt": str(external_dir / "source_data.txt"),
            },
            "rules": [
                {
                    "name": "process",
                    "kind": "action",
                    "inputs": ["input.txt"],
                    "outputs": ["output.txt"],
                    "run": "cp input.txt output.txt",
                },
            ],
        }

        # Run the build
        S = run(design, site=str(site), oracle_backend=stub_oracle)

        # Verify the build succeeded
        assert S["status"] == "committed", f"Build should succeed, got {S['status']}"

        # Verify the input was symlinked with the local name
        assert (site / "input.txt").exists(), "input.txt should be symlinked into site"
        assert (site / "input.txt").is_symlink(), "input.txt should be a symlink"

        # Verify symlink points to the external file
        assert (site / "input.txt").resolve() == (external_dir / "source_data.txt").resolve()

        # Verify the rule could read the input
        output = (site / "output.txt").read_text()
        assert "source content" in output, "Output should contain content from source_data.txt"

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


@pytest.mark.beta


@pytest.mark.gate_a


def test_site_inputs_validation():
    """site_inputs are validated as part of the dependency graph."""
    # Design where site_inputs provide initial inputs to the graph
    design = {
        "name": "validated",
        "fuel": 10,
        "target": "r",
        "site_inputs": ["external.txt"],
        "rules": [
            {
                "name": "r",
                "kind": "action",
                "inputs": ["external.txt"],
                "outputs": ["out.txt"],
            },
        ],
    }

    errors = check(design)
    assert len(errors) == 0, f"Design should be valid, got errors: {errors}"


@pytest.mark.beta


@pytest.mark.gate_a


def test_site_inputs_from_json_file():
    """site_inputs work when loading a JSON design from a file."""
    tmpdir = tempfile.mkdtemp(prefix="site-inputs-json-")
    try:
        # Create external files
        external_dir = Path(tmpdir) / "external"
        external_dir.mkdir()
        (external_dir / "spec.md").write_text("# Specification\n")

        # Create design file
        design_path = Path(tmpdir) / "design.json"
        design = {
            "name": "from-json",
            "fuel": 10,
            "target": "process",
            "site_inputs": [str(external_dir / "spec.md")],
            "rules": [
                {
                    "name": "process",
                    "kind": "action",
                    "inputs": ["spec.md"],
                    "outputs": ["report.txt"],
                    "run": "cp spec.md report.txt",
                },
            ],
        }
        design_path.write_text(json.dumps(design, indent=2))

        # Create site
        site = Path(tmpdir) / "site"
        site.mkdir()

        # Load and run the design from JSON
        loaded_design = from_json(design_path)
        S = run(loaded_design, site=str(site), oracle_backend=stub_oracle)

        # Verify success
        assert S["status"] == "committed", f"Build should succeed, got {S['status']}"
        assert (site / "spec.md").is_symlink(), "spec.md should be symlinked"
        assert (site / "report.txt").exists(), "report.txt should be created"

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


@pytest.mark.beta


@pytest.mark.gate_a


def test_site_inputs_cli_list_form():
    """CLI test: site_inputs as a list works from a clean site."""
    tmpdir = tempfile.mkdtemp(prefix="site-inputs-cli-list-")
    try:
        # Create external files
        external_dir = Path(tmpdir) / "external"
        external_dir.mkdir()
        (external_dir / "input1.txt").write_text("input 1\n")
        (external_dir / "input2.txt").write_text("input 2\n")

        # Create clean site directory
        site = Path(tmpdir) / "site"
        site.mkdir()

        # Create design file
        design_path = Path(tmpdir) / "design.json"
        design = {
            "name": "cli-test-list",
            "fuel": 10,
            "target": "combine",
            "site_inputs": [
                str(external_dir / "input1.txt"),
                str(external_dir / "input2.txt"),
            ],
            "rules": [
                {
                    "name": "combine",
                    "kind": "action",
                    "inputs": ["input1.txt", "input2.txt"],
                    "outputs": ["combined.txt"],
                    "run": "cat input1.txt input2.txt > combined.txt",
                },
            ],
        }
        design_path.write_text(json.dumps(design, indent=2))

        # Run via CLI
        result = run_husks_cli("run", str(design_path), "--site", str(site), "--stub")

        # Verify CLI succeeded
        assert result.returncode == 0, (
            f"CLI should exit 0, got {result.returncode}\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )

        # Verify the build artifacts
        assert (site / "input1.txt").is_symlink(), "input1.txt should be symlinked"
        assert (site / "input2.txt").is_symlink(), "input2.txt should be symlinked"
        assert (site / "combined.txt").exists(), "combined.txt should be created"

        combined = (site / "combined.txt").read_text()
        assert "input 1" in combined and "input 2" in combined

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


@pytest.mark.beta


@pytest.mark.gate_a


def test_site_inputs_cli_dict_form():
    """CLI test: site_inputs as a dict works from a clean site."""
    tmpdir = tempfile.mkdtemp(prefix="site-inputs-cli-dict-")
    try:
        # Create external file with different name
        external_dir = Path(tmpdir) / "external"
        external_dir.mkdir()
        (external_dir / "original_name.txt").write_text("original content\n")

        # Create clean site directory
        site = Path(tmpdir) / "site"
        site.mkdir()

        # Create design file with dict-form site_inputs
        design_path = Path(tmpdir) / "design.json"
        design = {
            "name": "cli-test-dict",
            "fuel": 10,
            "target": "process",
            "site_inputs": {
                "renamed.txt": str(external_dir / "original_name.txt"),
            },
            "rules": [
                {
                    "name": "process",
                    "kind": "action",
                    "inputs": ["renamed.txt"],
                    "outputs": ["output.txt"],
                    "run": "cp renamed.txt output.txt",
                },
            ],
        }
        design_path.write_text(json.dumps(design, indent=2))

        # Run via CLI
        result = run_husks_cli("run", str(design_path), "--site", str(site), "--stub")

        # Verify CLI succeeded
        assert result.returncode == 0, (
            f"CLI should exit 0, got {result.returncode}\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )

        # Verify the local name is used
        assert (site / "renamed.txt").is_symlink(), "renamed.txt should be symlinked"
        assert (site / "renamed.txt").resolve() == (external_dir / "original_name.txt").resolve()
        assert (site / "output.txt").exists(), "output.txt should be created"

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


@pytest.mark.beta


@pytest.mark.gate_a


def test_site_inputs_not_children():
    """Inputs from site_inputs don't create child dependencies in the graph."""
    design = {
        "name": "no-deps",
        "fuel": 10,
        "target": "r",
        "site_inputs": ["external.txt"],
        "rules": [
            {
                "name": "r",
                "kind": "action",
                "inputs": ["external.txt"],
                "outputs": ["out.txt"],
            },
        ],
    }

    # Compile the design
    from husks.designs.ir import compile
    _name, _fuel, terminals, _kwargs = compile(design)

    # The terminal node should have no children (external.txt is a site input)
    assert len(terminals) == 1
    node = terminals[0]
    assert node.get("inputs") == ["external.txt"]
    assert node.get("children") == [], "site_inputs should not create child dependencies"


@pytest.mark.beta


@pytest.mark.gate_a


def test_site_inputs_relative_path_resolution():
    """Beta Gate A1/A2: Relative site_inputs resolve against design file directory."""
    tmpdir = tempfile.mkdtemp(prefix="relative-site-inputs-")
    try:
        # Create design directory with design.json and input file together
        design_dir = Path(tmpdir) / "project"
        design_dir.mkdir()

        # Create the input file next to design.json
        (design_dir / "input.txt").write_text("design-local content\n")

        # Create design with relative site_inputs
        design_path = design_dir / "design.json"
        design = {
            "name": "relative-test",
            "fuel": 10,
            "target": "process",
            "site_inputs": ["input.txt"],  # Relative path
            "rules": [
                {
                    "name": "process",
                    "kind": "action",
                    "inputs": ["input.txt"],
                    "outputs": ["output.txt"],
                    "run": "cp input.txt output.txt",
                },
            ],
        }
        design_path.write_text(json.dumps(design, indent=2))

        # Create clean site directory in a different location
        site = Path(tmpdir) / "clean-site"
        site.mkdir()

        # Run via CLI - the relative input should be resolved against design_dir
        result = run_husks_cli("run", str(design_path), "--site", str(site), "--stub")

        # Verify CLI succeeded
        assert result.returncode == 0, (
            f"CLI should exit 0, got {result.returncode}\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )

        # Verify the input was symlinked from the design directory
        assert (site / "input.txt").is_symlink(), "input.txt should be symlinked"
        assert (site / "input.txt").resolve() == (design_dir / "input.txt").resolve(), (
            "input.txt should point to design_dir/input.txt"
        )

        # Verify the rule could read the input
        output = (site / "output.txt").read_text()
        assert "design-local content" in output

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


@pytest.mark.beta


@pytest.mark.gate_a


def test_site_inputs_missing_file_fails():
    """Beta Gate A2: Missing declared site_inputs fail before execution."""
    tmpdir = tempfile.mkdtemp(prefix="missing-site-inputs-")
    try:
        # Create design that references a non-existent file
        design_dir = Path(tmpdir) / "project"
        design_dir.mkdir()

        design_path = design_dir / "design.json"
        design = {
            "name": "missing-test",
            "fuel": 10,
            "target": "process",
            "site_inputs": ["missing.txt"],  # File does not exist
            "rules": [
                {
                    "name": "process",
                    "kind": "action",
                    "inputs": ["missing.txt"],
                    "outputs": ["output.txt"],
                },
            ],
        }
        design_path.write_text(json.dumps(design, indent=2))

        site = Path(tmpdir) / "site"
        site.mkdir()

        # Run via CLI - should fail with clear error
        result = run_husks_cli("run", str(design_path), "--site", str(site), "--stub")

        # Should exit non-zero
        assert result.returncode != 0, (
            f"CLI should fail for missing site_input, got exit {result.returncode}"
        )

        # Error message should mention the missing file
        error_output = result.stdout + result.stderr
        assert "missing.txt" in error_output.lower() or "does not exist" in error_output.lower()

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)
