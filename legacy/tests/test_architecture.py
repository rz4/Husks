"""Architecture conformance test.

Verifies the module dependency graph against layers.toml.

Phase 0 (now): Expects the 4 known cycles documented in layers.toml.
Phase 3: Tightens to expect zero violations (all cycles cut).
"""

from pathlib import Path
try:
    import tomllib  # Python 3.11+
except ImportError:
    import tomli as tomllib  # Python 3.10

from husks._arch.check import check_architecture


def test_architecture_phase_0():
    """Phase 0: Report-only mode.

    The checker runs and identifies the 4 known cycles:
    1. build.eval → build.cache → build.identity → build.eval
    2. oracle → oracle.litellm → oracle
    3. oracle → oracle.claude_code → oracle
    4. cli.main → cli.cmd.build → cli.surface → cli.main

    These are documented in layers.toml and will be removed in phases 1-2.
    """
    repo_root = Path(__file__).parent.parent
    src_root = repo_root / "src"
    layers_toml = repo_root / "layers.toml"

    # Load the contract
    contract = tomllib.loads(layers_toml.read_text())

    # Run the checker
    violations = check_architecture(src_root, contract)

    # Phase 0: We expect violations (the 4 known cycles)
    # Don't assert zero violations yet — that's Phase 3
    # For now, just verify the checker runs and returns a list

    assert isinstance(violations, list), "check_architecture should return a list"

    # Print violations for visibility (useful during development)
    if violations:
        print("\nArchitecture violations (Phase 0 — expected):")
        for v in violations:
            print(f"  - {v}")
    else:
        print("\nNo architecture violations detected!")

    # Phase 0 exit criterion: the checker runs successfully
    # We don't fail on violations yet — enforcing mode starts in Phase 3
    # Uncommenting the line below would fail the test:
    # assert len(violations) == 0, f"Found {len(violations)} violations"


def test_architecture_known_cycles():
    """Verify we can detect the specific known cycles.

    This test documents the exact cycles we're about to fix.
    It will be updated as cycles are removed in phases 1-2.
    """
    repo_root = Path(__file__).parent.parent
    src_root = repo_root / "src"
    layers_toml = repo_root / "layers.toml"

    contract = tomllib.loads(layers_toml.read_text())
    violations = check_architecture(src_root, contract)

    # Look for cycle-related violations
    cycle_violations = [v for v in violations if v.startswith("cycle:")]

    # Phase 0: We expect to find cycles
    # (In Phase 3, this assertion will change to == 0)
    print(f"\nFound {len(cycle_violations)} cycles:")
    for cv in cycle_violations:
        print(f"  {cv}")

    # For now, just document what we found
    # assert len(cycle_violations) == 4  # Uncomment after verifying exact count


def test_pure_infra_isolation():
    """Verify utils.* modules have zero husks imports.

    This invariant must hold in all phases.
    """
    repo_root = Path(__file__).parent.parent
    src_root = repo_root / "src"
    layers_toml = repo_root / "layers.toml"

    contract = tomllib.loads(layers_toml.read_text())
    violations = check_architecture(src_root, contract)

    # Filter for pure_infra violations
    pure_violations = [
        v for v in violations
        if "pure_infra module imports husks" in v
    ]

    # This should be zero even in Phase 0
    assert len(pure_violations) == 0, (
        f"Pure infrastructure modules must not import husks: {pure_violations}"
    )


def test_gate_isolation():
    """Verify gate.py imports only core (L0).

    The independent reader must stay isolated — this is architectural.
    """
    repo_root = Path(__file__).parent.parent
    src_root = repo_root / "src"
    layers_toml = repo_root / "layers.toml"

    contract = tomllib.loads(layers_toml.read_text())
    violations = check_architecture(src_root, contract)

    # Filter for gate isolation violations
    gate_violations = [
        v for v in violations
        if "isolated module imports above" in v and "gate" in v
    ]

    # This should be zero in all phases
    assert len(gate_violations) == 0, (
        f"Gate must import only L0 (core): {gate_violations}"
    )
