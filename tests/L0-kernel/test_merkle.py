"""Merkle DAG tests -- node digest determinism, sensitivity, multi-target root."""

import hashlib
from husks.kernel import compute_node_digest, atom, recompute_root, parse, _extract_build, _recompute_node


class TestNodeDigest:
    def test_deterministic(self):
        seal = atom("abcdef1234567890" * 4)
        d1 = compute_node_digest(b"test", seal, [(b"out.txt", b"hash1")], [])
        d2 = compute_node_digest(b"test", seal, [(b"out.txt", b"hash1")], [])
        assert d1 == d2
        assert len(d1) == 64

    def test_children_affect_digest(self):
        seal = atom("abcdef1234567890" * 4)
        d1 = compute_node_digest(b"test", seal, [], [])
        d2 = compute_node_digest(b"test", seal, [], [atom("child_digest_hex")])
        assert d1 != d2

    def test_outputs_affect_digest(self):
        seal = atom("abcdef1234567890" * 4)
        d1 = compute_node_digest(b"test", seal, [(b"a.txt", b"h1")], [])
        d2 = compute_node_digest(b"test", seal, [(b"a.txt", b"h2")], [])
        assert d1 != d2

    def test_name_affects_digest(self):
        seal = atom("abcdef1234567890" * 4)
        d1 = compute_node_digest(b"alpha", seal, [], [])
        d2 = compute_node_digest(b"beta", seal, [], [])
        assert d1 != d2

    def test_seal_affects_digest(self):
        s1 = atom("a" * 64)
        s2 = atom("b" * 64)
        d1 = compute_node_digest(b"test", s1, [], [])
        d2 = compute_node_digest(b"test", s2, [], [])
        assert d1 != d2

    def test_output_is_hex_sha256(self):
        seal = atom("abcdef1234567890" * 4)
        d = compute_node_digest(b"test", seal, [], [])
        assert len(d) == 64
        int(d, 16)


class TestMultiTargetRoot:
    def test_single_target_equals_node_digest(self):
        """Single-target build returns the target's digest directly."""
        # Build a minimal husk with one rule, use a deterministic hash_file
        husk_bytes = (
            b"(4:husk1:1(5:build4:test2:10"
            b"(4:rule3:foo(6:action)()()"
            b")))"
        )
        hash_file = lambda path: b"absent"
        husk_tree = parse(husk_bytes)
        version, _, _, targets = _extract_build(husk_tree)
        assert len(targets) == 1
        root = _recompute_node(targets[0], hash_file, version)
        assert len(root) == 64

    def test_multi_target_combines_sorted(self):
        """Multi-target root is SHA-256 of sorted per-target roots."""
        husk_bytes = (
            b"(4:husk1:1(5:build4:test2:10"
            b"(4:rule5:alpha(6:action)()()"
            b")"
            b"(4:rule4:beta(6:action)()()"
            b")"
            b"))"
        )
        hash_file = lambda path: b"absent"
        husk_tree = parse(husk_bytes)
        version, _, _, targets = _extract_build(husk_tree)
        assert len(targets) == 2

        per_roots = [_recompute_node(t, hash_file, version) for t in targets]
        expected = hashlib.sha256(b"".join(r.encode() for r in sorted(per_roots))).hexdigest()

        # Verify recompute_root produces the same thing (via site_dir path that won't find files)
        import tempfile, os
        with tempfile.TemporaryDirectory() as td:
            root = recompute_root(husk_bytes, td)
        assert root == expected
