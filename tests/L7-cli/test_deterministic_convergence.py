"""test_deterministic_convergence.py -- G.b: deterministic root convergence.

When a design has no oracle rules and no free outputs, root convergence
between M1 and M3 must be REQUIRED (not observational).  A divergence in
roots for a fully deterministic build means the proof is unsatisfied.
"""

from types import SimpleNamespace
from unittest.mock import patch


def _node(name="a", kind="action", state="sealed", cache=False, cost=1.0):
    """Create a mock node (duck-typed to match CliNode interface)."""
    return SimpleNamespace(name=name, kind=kind, state=state,
                           cache=cache, cost=cost)


def _residue(site, root, oracle_nodes=False, cost=1.0):
    """Build a mock residue matching the interface used by _three_machine_checks."""
    nodes = []
    if oracle_nodes:
        nodes.append(_node(name="w", kind="oracle", state="fired", cost=cost))
    else:
        nodes.append(_node(name="a", kind="action", state="sealed", cost=cost))
    return SimpleNamespace(
        site=site, root=root, husk_hash="h1",
        fuel_budget=10, fuel_used=1, cost=cost, nodes=nodes,
    )


def _comparison(site_a, site_b, roots_match, free_skipped=None):
    """Build a comparison dict matching compare_artifacts output shape."""
    return {
        "site_a": site_a,
        "site_b": site_b,
        "equivalent": roots_match,
        "details": {
            "roots_match": roots_match,
            "free_skipped": free_skipped or [],
        },
    }


# Patches target the modules from which _three_machine_checks lazily imports.
_PATCH_MANIFEST = patch("husks.report.read_manifest",
                        return_value={"oracle_backend": "stub"})
_PATCH_RECOMPUTE = patch("husks.kernel.recompute_root",
                         return_value="root-AAA")


class TestDeterministicRootConvergence:
    """G.b: root convergence required when design is fully deterministic."""

    @_PATCH_MANIFEST
    @_PATCH_RECOMPUTE
    def test_divergent_roots_deterministic_fails(self, _mock_rc, _mock_mf):
        """No oracles + no free outputs + different roots => required + failing."""
        from husks.cli import _three_machine_checks

        m1 = _residue("site-a", root="root-AAA", oracle_nodes=False)
        m2 = _residue("site-b", root="root-BBB", oracle_nodes=False, cost=0.0)
        m3 = _residue("site-c", root="root-CCC", oracle_nodes=False)

        comparisons = [
            _comparison("site-a", "site-b", roots_match=True),
            _comparison("site-a", "site-c", roots_match=False),  # diverged
        ]

        checks = _three_machine_checks([m1, m2, m3], comparisons)

        # Find the root convergence check
        conv = next(c for c in checks if "root convergence" in c[0])
        label, passed, required = conv

        assert required is True, "root convergence must be required for deterministic designs"
        assert passed is False, "roots diverged so check must fail"

        # Proof not satisfied: at least one required check fails
        proof_satisfied = all(passed for _, passed, req in checks if req)
        assert not proof_satisfied

    @_PATCH_MANIFEST
    @_PATCH_RECOMPUTE
    def test_matching_roots_deterministic_passes(self, _mock_rc, _mock_mf):
        """No oracles + no free outputs + same roots => required + passing."""
        from husks.cli import _three_machine_checks

        m1 = _residue("site-a", root="root-AAA", oracle_nodes=False)
        m2 = _residue("site-b", root="root-AAA", oracle_nodes=False, cost=0.0)
        m3 = _residue("site-c", root="root-AAA", oracle_nodes=False)

        comparisons = [
            _comparison("site-a", "site-b", roots_match=True),
            _comparison("site-a", "site-c", roots_match=True),
        ]

        checks = _three_machine_checks([m1, m2, m3], comparisons)
        conv = next(c for c in checks if "root convergence" in c[0])
        _, passed, required = conv

        assert required is True
        assert passed is True

    @_PATCH_MANIFEST
    @_PATCH_RECOMPUTE
    def test_with_oracles_stays_observational(self, _mock_rc, _mock_mf):
        """When oracles are present, root convergence remains observational."""
        from husks.cli import _three_machine_checks

        m1 = _residue("site-a", root="root-AAA", oracle_nodes=True)
        m2 = _residue("site-b", root="root-AAA", oracle_nodes=True, cost=0.0)
        m3 = _residue("site-c", root="root-BBB", oracle_nodes=True)

        comparisons = [
            _comparison("site-a", "site-b", roots_match=True),
            _comparison("site-a", "site-c", roots_match=False),
        ]

        checks = _three_machine_checks([m1, m2, m3], comparisons)
        conv = next(c for c in checks if "root convergence" in c[0])
        _, passed, required = conv

        assert required is False, "with oracles, root convergence is observational"
        assert passed is False

    @_PATCH_MANIFEST
    @_PATCH_RECOMPUTE
    def test_with_free_outputs_stays_observational(self, _mock_rc, _mock_mf):
        """When free outputs are present, root convergence is observational."""
        from husks.cli import _three_machine_checks

        m1 = _residue("site-a", root="root-AAA", oracle_nodes=False)
        m2 = _residue("site-b", root="root-AAA", oracle_nodes=False, cost=0.0)
        m3 = _residue("site-c", root="root-BBB", oracle_nodes=False)

        comparisons = [
            _comparison("site-a", "site-b", roots_match=True),
            _comparison("site-a", "site-c", roots_match=False,
                       free_skipped=["out.txt"]),  # free outputs present
        ]

        checks = _three_machine_checks([m1, m2, m3], comparisons)
        conv = next(c for c in checks if "root convergence" in c[0])
        _, passed, required = conv

        assert required is False, "with free outputs, root convergence is observational"
