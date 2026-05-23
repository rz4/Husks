"""
test_core.py — Unit tests for CSE parse/encode/seal/Merkle in husks.core.
"""

import hashlib
import sys
import os
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from husks.core import (
    encode, parse, atom, atom_str, sha256_bytes,
    content_hash, recipe_digest, compute_seal, compute_node_digest,
    NIL, CSE_VERSION, ABSENT,
)


# ── Encode / Parse round-trip ──────────────────────────────────────

class TestEncode:
    def test_atom_empty(self):
        """NIL encodes as b'0:'"""
        assert encode(NIL) == b"0:"

    def test_atom_hello(self):
        assert encode(b"hello") == b"5:hello"

    def test_atom_binary(self):
        data = bytes(range(256))
        encoded = encode(data)
        assert encoded == b"256:" + data

    def test_list_empty(self):
        assert encode([]) == b"()"

    def test_list_single(self):
        assert encode([b"a"]) == b"(1:a)"

    def test_list_nested(self):
        val = [b"seal", [b"x", b"y"]]
        encoded = encode(val)
        assert encoded == b"(4:seal(1:x1:y))"

    def test_type_error(self):
        with pytest.raises(TypeError):
            encode("string")
        with pytest.raises(TypeError):
            encode(42)


class TestParse:
    def test_atom_empty(self):
        assert parse(b"0:") == NIL

    def test_atom_hello(self):
        assert parse(b"5:hello") == b"hello"

    def test_list_empty(self):
        assert parse(b"()") == []

    def test_list_nested(self):
        data = b"(4:seal(1:x1:y))"
        result = parse(data)
        assert result == [b"seal", [b"x", b"y"]]

    def test_leading_zero_rejected(self):
        """Leading zeros in atom lengths are invalid."""
        with pytest.raises(ValueError, match="leading zero"):
            parse(b"05:hello")

    def test_trailing_data_rejected(self):
        with pytest.raises(ValueError, match="trailing data"):
            parse(b"5:hello0:")

    def test_unterminated_list(self):
        with pytest.raises(ValueError, match="unterminated"):
            parse(b"(5:hello")

    def test_truncated_atom(self):
        with pytest.raises(ValueError, match="truncated"):
            parse(b"10:hi")


class TestRoundTrip:
    def test_nil(self):
        assert parse(encode(NIL)) == NIL

    def test_complex(self):
        val = [b"husk", b"1", [b"build", b"demo", b"10", [b"rule", b"test"]]]
        assert parse(encode(val)) == val

    def test_binary_atom(self):
        data = b"\x00\xff\x80\x01"
        assert parse(encode(data)) == data


# ── SHA256 known-answer ────────────────────────────────────────────

class TestSHA256:
    def test_empty(self):
        expected = hashlib.sha256(b"").hexdigest().encode("ascii")
        assert sha256_bytes(b"") == expected

    def test_hello(self):
        expected = hashlib.sha256(b"hello").hexdigest().encode("ascii")
        assert sha256_bytes(b"hello") == expected

    def test_content_hash(self):
        data = b"Hello, world!\n"
        h = content_hash(data)
        assert h == hashlib.sha256(data).hexdigest().encode("ascii")
        assert len(h) == 64  # hex SHA256


# ── Seal determinism ──────────────────────────────────────────────

class TestSealDeterminism:
    def test_same_inputs_same_seal(self):
        recipe = [b"action"]
        bindings = [(b"a.txt", b"abc123"), (b"b.txt", b"def456")]
        s1 = compute_seal(CSE_VERSION, recipe, bindings)
        s2 = compute_seal(CSE_VERSION, recipe, bindings)
        assert s1 == s2

    def test_different_inputs_different_seal(self):
        recipe = [b"action"]
        b1 = [(b"a.txt", b"abc123")]
        b2 = [(b"a.txt", b"xyz789")]
        s1 = compute_seal(CSE_VERSION, recipe, b1)
        s2 = compute_seal(CSE_VERSION, recipe, b2)
        assert s1 != s2

    def test_different_recipe_different_seal(self):
        r1 = [b"action"]
        r2 = [b"oracle", NIL, b"do stuff", [], b"5"]
        bindings = [(b"a.txt", b"abc123")]
        s1 = compute_seal(CSE_VERSION, r1, bindings)
        s2 = compute_seal(CSE_VERSION, r2, bindings)
        assert s1 != s2


class TestNodeDigest:
    def test_deterministic(self):
        seal = atom("abcdef1234567890" * 4)
        d1 = compute_node_digest(b"test", seal, [(b"out.txt", b"hash1")], [])
        d2 = compute_node_digest(b"test", seal, [(b"out.txt", b"hash1")], [])
        assert d1 == d2
        assert len(d1) == 64  # hex SHA256

    def test_children_affect_digest(self):
        seal = atom("abcdef1234567890" * 4)
        d1 = compute_node_digest(b"test", seal, [], [])
        d2 = compute_node_digest(b"test", seal, [], [atom("child_digest_hex")])
        assert d1 != d2


class TestRecipeDigest:
    def test_deterministic(self):
        r = [b"oracle", NIL, b"prompt", [b"tool1"], b"5"]
        d1 = recipe_digest(r)
        d2 = recipe_digest(r)
        assert d1 == d2
        assert len(d1) == 64
