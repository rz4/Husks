"""Conformance vector tests -- golden vectors pass, malformed rejected, verify predicate."""

import pytest
from kernel import recompute_root, verify, parse, _extract_build, _recompute_node


class TestConformanceVectors:
    def test_valid_vectors_reproduce_root(self, valid_vector):
        husk_bytes, site_dir, expected_root = valid_vector
        assert recompute_root(husk_bytes, site_dir) == expected_root

    def test_demo_vector(self, demo_vector):
        husk_bytes, site_dir, expected_root = demo_vector
        assert recompute_root(husk_bytes, site_dir) == expected_root

    def test_unsorted_vector(self, unsorted_vector):
        husk_bytes, site_dir, expected_root = unsorted_vector
        assert recompute_root(husk_bytes, site_dir) == expected_root

    def test_adversarial_vector(self, adversarial_vector):
        husk_bytes, site_dir, expected_root = adversarial_vector
        assert recompute_root(husk_bytes, site_dir) == expected_root


class TestMalformedVectors:
    def test_malformed_rejected(self, malformed_vector):
        with pytest.raises(ValueError):
            recompute_root(malformed_vector, "/nonexistent")


class TestVerifyPredicate:
    def test_verify_true(self, valid_vector):
        husk_bytes, site_dir, expected_root = valid_vector
        assert verify(husk_bytes, site_dir, expected_root) is True

    def test_verify_false(self, valid_vector):
        husk_bytes, site_dir, _expected_root = valid_vector
        assert verify(husk_bytes, site_dir, "0" * 64) is False

    def test_verify_returns_bool(self, demo_vector):
        husk_bytes, site_dir, expected_root = demo_vector
        result = verify(husk_bytes, site_dir, expected_root)
        assert isinstance(result, bool)


class TestInjectedHasher:
    def test_recompute_node_with_injected_hasher(self):
        """_recompute_node works with a custom hash_file callable."""
        husk_bytes = (
            b"(4:husk1:1(5:build4:test2:10"
            b"(4:rule3:foo(6:action)(7:src.txt)(7:out.txt)"
            b")))"
        )
        fake_hash = b"a" * 64
        hash_file = lambda path: fake_hash

        husk_tree = parse(husk_bytes)
        version, _, _, targets = _extract_build(husk_tree)
        root = _recompute_node(targets[0], hash_file, version)
        assert len(root) == 64

        # Same hasher produces same root
        root2 = _recompute_node(targets[0], hash_file, version)
        assert root == root2

    def test_different_hasher_different_root(self):
        """Different hash_file produces different root."""
        husk_bytes = (
            b"(4:husk1:1(5:build4:test2:10"
            b"(4:rule3:foo(6:action)(7:src.txt)(7:out.txt)"
            b")))"
        )
        husk_tree = parse(husk_bytes)
        version, _, _, targets = _extract_build(husk_tree)

        r1 = _recompute_node(targets[0], lambda p: b"a" * 64, version)
        r2 = _recompute_node(targets[0], lambda p: b"b" * 64, version)
        assert r1 != r2
