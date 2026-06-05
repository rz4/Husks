"""CSE codec tests -- encode, parse, roundtrip, rejection."""

import pytest
from kernel import encode, parse, NIL


class TestEncode:
    def test_atom_empty(self):
        assert encode(NIL) == b"0:"

    def test_atom_hello(self):
        assert encode(b"hello") == b"5:hello"

    def test_atom_binary(self):
        data = bytes(range(256))
        assert encode(data) == b"256:" + data

    def test_list_empty(self):
        assert encode([]) == b"()"

    def test_list_single(self):
        assert encode([b"a"]) == b"(1:a)"

    def test_list_nested(self):
        assert encode([b"seal", [b"x", b"y"]]) == b"(4:seal(1:x1:y))"

    def test_type_error_string(self):
        with pytest.raises(TypeError):
            encode("string")

    def test_type_error_int(self):
        with pytest.raises(TypeError):
            encode(42)

    def test_type_error_nested(self):
        with pytest.raises(TypeError):
            encode([b"ok", 99])


class TestParse:
    def test_atom_empty(self):
        assert parse(b"0:") == NIL

    def test_atom_hello(self):
        assert parse(b"5:hello") == b"hello"

    def test_list_empty(self):
        assert parse(b"()") == []

    def test_list_nested(self):
        assert parse(b"(4:seal(1:x1:y))") == [b"seal", [b"x", b"y"]]

    def test_leading_zero_rejected(self):
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

    def test_type_error(self):
        with pytest.raises(TypeError):
            parse("not bytes")

    def test_depth_limit(self):
        deep = b"(" * 200 + b"0:" + b")" * 200
        with pytest.raises(ValueError, match="nesting depth"):
            parse(deep)

    def test_oversized_atom_rejected(self):
        huge_len = str(256 * 1024 * 1024 + 1).encode()
        with pytest.raises(ValueError, match="exceeds maximum"):
            parse(huge_len + b":x")

    def test_no_colon(self):
        with pytest.raises(ValueError, match="no colon"):
            parse(b"abc")

    def test_non_digit_in_length(self):
        with pytest.raises(ValueError, match="non-digit"):
            parse(b"1a:xx")


class TestRoundTrip:
    def test_nil(self):
        assert parse(encode(NIL)) == NIL

    def test_complex(self):
        val = [b"husk", b"1", [b"build", b"demo", b"10", [b"rule", b"test"]]]
        assert parse(encode(val)) == val

    def test_binary_atom(self):
        data = b"\x00\xff\x80\x01"
        assert parse(encode(data)) == data

    def test_empty_list_roundtrip(self):
        assert parse(encode([])) == []

    def test_deeply_nested(self):
        val = b"leaf"
        for _ in range(50):
            val = [val]
        assert parse(encode(val)) == val

    def test_multiple_atoms(self):
        val = [b"a", b"b", b"c"]
        assert parse(encode(val)) == val
