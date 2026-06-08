"""test_acceptance_anchor.py -- G.c: acceptance anchor as a required check.

When an acceptance_anchor dict is provided (condense path), cold outputs
must match the accepted digests.  When absent (plain run), no anchor check
appears in the check list.
"""

from types import SimpleNamespace
from unittest.mock import patch


def _node(name="a", kind="action", state="sealed", cache=False, cost=1.0):
    return SimpleNamespace(name=name, kind=kind, state=state,
                           cache=cache, cost=cost)


def _residue(site, root, oracle_nodes=False, cost=1.0):
    nodes = []
    if oracle_nodes:
        nodes.append(_node(name="w", kind="oracle", state="fired", cost=cost))
    else:
        nodes.append(_node(name="a", kind="action", state="sealed", cost=cost))
    return SimpleNamespace(
        site=site, root=root, husk_hash="h1",
        fuel_budget=10, fuel_used=1, cost=cost, nodes=nodes,
    )


def _comparison(site_a, site_b, roots_match, outputs_a=None, free_skipped=None):
    return {
        "site_a": site_a,
        "site_b": site_b,
        "equivalent": roots_match,
        "details": {
            "roots_match": roots_match,
            "outputs_a": outputs_a or {},
            "free_skipped": free_skipped or [],
        },
    }


_PATCH_MANIFEST = patch("husks.report.read_manifest",
                        return_value={"oracle_backend": "stub"})
_PATCH_RECOMPUTE = patch("husks.kernel.recompute_root",
                         return_value="root-AAA")


class TestAcceptanceAnchor:
    """G.c: acceptance anchor check behavior."""

    @_PATCH_MANIFEST
    @_PATCH_RECOMPUTE
    def test_matching_anchor_passes(self, _mock_rc, _mock_mf):
        """Cold outputs match accepted digests -> check passes, required."""
        from husks.cli import _three_machine_checks

        m1 = _residue("site-a", root="root-AAA")
        m2 = _residue("site-b", root="root-AAA", cost=0.0)
        m3 = _residue("site-c", root="root-AAA")

        anchor = {"out.txt": "abc123"}
        comparisons = [
            _comparison("site-a", "site-b", roots_match=True),
            _comparison("site-a", "site-c", roots_match=True,
                        outputs_a={"out.txt": "abc123"}),
        ]

        checks = _three_machine_checks([m1, m2, m3], comparisons,
                                        acceptance_anchor=anchor)

        ac = next(c for c in checks if "acceptance anchor" in c[0])
        label, passed, required = ac
        assert passed is True
        assert required is True

    @_PATCH_MANIFEST
    @_PATCH_RECOMPUTE
    def test_divergent_anchor_fails_proof(self, _mock_rc, _mock_mf):
        """Cold output differs from accepted -> check fails, proof unsatisfied."""
        from husks.cli import _three_machine_checks

        m1 = _residue("site-a", root="root-AAA")
        m2 = _residue("site-b", root="root-AAA", cost=0.0)
        m3 = _residue("site-c", root="root-AAA")

        anchor = {"out.txt": "abc123"}
        comparisons = [
            _comparison("site-a", "site-b", roots_match=True),
            _comparison("site-a", "site-c", roots_match=True,
                        outputs_a={"out.txt": "DIFFERENT"}),
        ]

        checks = _three_machine_checks([m1, m2, m3], comparisons,
                                        acceptance_anchor=anchor)

        ac = next(c for c in checks if "acceptance anchor" in c[0])
        label, passed, required = ac
        assert passed is False
        assert required is True

        # Proof not satisfied
        proof_satisfied = all(p for _, p, r in checks if r)
        assert not proof_satisfied

    @_PATCH_MANIFEST
    @_PATCH_RECOMPUTE
    def test_no_anchor_check_absent(self, _mock_rc, _mock_mf):
        """When acceptance_anchor=None, no anchor check in list (plain run)."""
        from husks.cli import _three_machine_checks

        m1 = _residue("site-a", root="root-AAA")
        m2 = _residue("site-b", root="root-AAA", cost=0.0)
        m3 = _residue("site-c", root="root-AAA")

        comparisons = [
            _comparison("site-a", "site-b", roots_match=True),
            _comparison("site-a", "site-c", roots_match=True),
        ]

        checks = _three_machine_checks([m1, m2, m3], comparisons)

        anchor_checks = [c for c in checks if "acceptance anchor" in c[0]]
        assert anchor_checks == []

    @_PATCH_MANIFEST
    @_PATCH_RECOMPUTE
    def test_partial_mismatch_fails(self, _mock_rc, _mock_mf):
        """Multiple outputs, one matches one doesn't -> overall check fails."""
        from husks.cli import _three_machine_checks

        m1 = _residue("site-a", root="root-AAA")
        m2 = _residue("site-b", root="root-AAA", cost=0.0)
        m3 = _residue("site-c", root="root-AAA")

        anchor = {"out.txt": "abc123", "data.bin": "def456"}
        comparisons = [
            _comparison("site-a", "site-b", roots_match=True),
            _comparison("site-a", "site-c", roots_match=True,
                        outputs_a={"out.txt": "abc123", "data.bin": "WRONG"}),
        ]

        checks = _three_machine_checks([m1, m2, m3], comparisons,
                                        acceptance_anchor=anchor)

        ac = next(c for c in checks if "acceptance anchor" in c[0])
        label, passed, required = ac
        assert passed is False
        assert required is True
