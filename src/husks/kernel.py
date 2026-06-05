"""L0 kernel -- CSE codec, content-addressed seals, Merkle DAG verification.

The permanence layer.  Implements the frozen CSE v1 wire format, seal
preimage construction, and node-digest algorithm.  Zero dependencies
beyond stdlib (hashlib, os).  Pure computation is separated from I/O:
_recompute_node accepts an injected hash_file callable; recompute_root
constructs the filesystem closure at the boundary.
"""

from __future__ import annotations

import hashlib
import os
from typing import Callable, Union

# ── CSE value type ────────────────────────────────────────────────

CseValue = Union[bytes, list["CseValue"]]

# ── Constants ─────────────────────────────────────────────────────

NIL: bytes = b""
CSE_VERSION: bytes = b"2"
ABSENT: bytes = b"absent"

_MAX_PARSE_DEPTH: int = 128
_MAX_ATOM_LENGTH: int = 256 * 1024 * 1024

# ── CSE Encode ────────────────────────────────────────────────────

def encode(value: CseValue) -> bytes:
    """Serialize a CSE value to canonical wire bytes."""
    if isinstance(value, bytes):
        return b"%d:%s" % (len(value), value)
    if isinstance(value, list):
        return b"(" + b"".join(encode(child) for child in value) + b")"
    raise TypeError(f"CSE encode: expected bytes or list, got {type(value).__name__}")

# ── CSE Parse ─────────────────────────────────────────────────────

def parse(data: bytes | memoryview) -> CseValue:
    """Parse canonical CSE wire bytes into a value tree."""
    if not isinstance(data, (bytes, memoryview)):
        raise TypeError(f"CSE parse: expected bytes, got {type(data).__name__}")
    value, rest = _parse(data, 0, 0)
    if rest != len(data):
        raise ValueError(f"CSE parse: trailing data at offset {rest}")
    return value


def _parse(data: bytes | memoryview, offset: int, depth: int) -> tuple[CseValue, int]:
    """Recursive descent parser.  Returns (value, next_offset)."""
    if depth > _MAX_PARSE_DEPTH:
        raise ValueError(f"CSE parse: nesting depth exceeds {_MAX_PARSE_DEPTH} at offset {offset}")
    if offset >= len(data):
        raise ValueError("CSE parse: unexpected end of data")

    # List
    if data[offset : offset + 1] == b"(":
        offset += 1
        items: list[CseValue] = []
        while offset < len(data) and data[offset : offset + 1] != b")":
            item, offset = _parse(data, offset, depth + 1)
            items.append(item)
        if offset >= len(data):
            raise ValueError("CSE parse: unterminated list")
        return items, offset + 1

    # Atom -- find colon
    try:
        colon = data.index(ord(b":") if isinstance(data[offset], int) else b":", offset)
    except ValueError:
        raise ValueError(f"CSE parse: no colon found for atom length at offset {offset}") from None

    length_str = data[offset:colon]
    for i, byte in enumerate(length_str):
        b = byte if isinstance(byte, int) else ord(byte)
        if b < 0x30 or b > 0x39:
            raise ValueError(f"CSE parse: non-digit byte 0x{b:02x} in length at offset {offset + i}")

    if len(length_str) > 1 and length_str[0:1] == b"0":
        raise ValueError(f"CSE parse: leading zero in length at offset {offset}")

    length = int(length_str)
    if length > _MAX_ATOM_LENGTH:
        raise ValueError(f"CSE parse: atom length {length} exceeds maximum {_MAX_ATOM_LENGTH} at offset {offset}")

    start = colon + 1
    end = start + length
    if end > len(data):
        raise ValueError(f"CSE parse: atom truncated at offset {offset}")
    return bytes(data[start:end]), end

# ── Atom helpers ──────────────────────────────────────────────────

def atom_str(b: bytes) -> str:
    """Decode a CSE bytes atom to str (UTF-8)."""
    return b.decode("utf-8")


def atom(s: str | bytes) -> bytes:
    """Coerce str to CSE bytes atom (UTF-8); bytes pass through."""
    return s.encode("utf-8") if isinstance(s, str) else s

# ── Hashing ───────────────────────────────────────────────────────

def sha256_bytes(data: bytes) -> bytes:
    """SHA-256 of data, returned as lowercase hex bytes."""
    return hashlib.sha256(data).hexdigest().encode("ascii")


def content_hash(file_bytes: bytes) -> bytes:
    """SHA-256 of file contents, returned as lowercase hex bytes atom."""
    return sha256_bytes(file_bytes)

# ── Seal computation ──────────────────────────────────────────────

def recipe_digest(recipe_form: CseValue) -> str:
    """SHA-256 hex of the CSE encoding of a recipe form."""
    return hashlib.sha256(encode(recipe_form)).hexdigest()


def compute_seal(
    version: bytes,
    recipe_form: CseValue,
    input_bindings: list[tuple[bytes, bytes]],
) -> str:
    """Compute the seal hash for a rule."""
    rd = atom(recipe_digest(recipe_form))
    binding_list: list[CseValue] = [[name, h] for name, h in input_bindings]
    preimage: CseValue = [b"seal", version, rd, binding_list]
    return hashlib.sha256(encode(preimage)).hexdigest()

# ── Merkle DAG ────────────────────────────────────────────────────

def compute_node_digest(
    name: bytes,
    seal: bytes,
    output_bindings: list[tuple[bytes, bytes]],
    child_digests: list[bytes],
) -> str:
    """Compute a node's Merkle digest."""
    out_list: list[CseValue] = [[n, h] for n, h in output_bindings]
    node_form: CseValue = [b"node", name, seal, out_list, list(child_digests)]
    return hashlib.sha256(encode(node_form)).hexdigest()

# ── Path / name validation (security) ────────────────────────────

def _validate_rule_name(name: str) -> None:
    """Reject rule names that could escape .traces/ via path injection."""
    if not name:
        raise ValueError("empty rule name in .husk")
    if "/" in name or "\\" in name:
        raise ValueError(f"rule name contains path separator in .husk: {name}")
    if name == ".." or name.startswith(".."):
        raise ValueError(f"rule name contains '..' in .husk: {name}")
    for i, c in enumerate(name):
        if ord(c) < 0x20 or ord(c) == 0x7F:
            raise ValueError(f"rule name contains control character at position {i} in .husk: {name}")
    if name in {"build.manifest"}:
        raise ValueError(f"rule name collides with internal file in .husk: {name}")
    if name.endswith(".seal") or name.endswith(".trial") or name.endswith(".history"):
        raise ValueError(f"rule name uses reserved extension in .husk: {name}")


def _validate_husk_path(name: str) -> None:
    """Reject paths that escape the site directory."""
    if not name:
        raise ValueError("empty path in .husk")
    if os.path.isabs(name):
        raise ValueError(f"absolute path in .husk: {name}")
    parts = name.split(os.sep)
    if os.altsep:
        parts = [sub for p in parts for sub in p.split(os.altsep)]
    if any(p == ".." for p in parts):
        raise ValueError(f"path traversal in .husk: {name}")
    first = parts[0]
    if first in (".traces", ".husks"):
        raise ValueError(f"reserved path in .husk: {name}")
    if name.endswith(".husk"):
        raise ValueError(f".husk file in .husk: {name}")

# ── Husk structure extraction ─────────────────────────────────────

def _extract_rule_fields(
    rule_node: list[CseValue],
) -> tuple[bytes, CseValue, list[bytes], list[bytes], list[list[CseValue]]]:
    """Destructure a parsed CSE rule node into (name, recipe, inputs, outputs, children)."""
    if not isinstance(rule_node, list) or len(rule_node) < 5:
        raise ValueError(
            f"CSE rule node: expected list of >= 5 elements, "
            f"got {type(rule_node).__name__} of length "
            f"{len(rule_node) if isinstance(rule_node, list) else 'N/A'}"
        )
    if rule_node[0] != b"rule":
        raise ValueError(f"CSE rule node: expected tag b'rule', got {rule_node[0]!r}")
    return rule_node[1], rule_node[2], rule_node[3], rule_node[4], rule_node[5:]


def _extract_build(
    husk_tree: list[CseValue],
) -> tuple[bytes, bytes, bytes, list[list[CseValue]]]:
    """Destructure a top-level husk tree into (version, build_name, fuel, target_nodes)."""
    if not isinstance(husk_tree, list) or len(husk_tree) < 3:
        raise ValueError(
            f"CSE husk: expected list of >= 3 elements, got length "
            f"{len(husk_tree) if isinstance(husk_tree, list) else 'N/A'}"
        )
    if husk_tree[0] != b"husk":
        raise ValueError(f"CSE husk: expected tag b'husk', got {husk_tree[0]!r}")
    build_form = husk_tree[2]
    if not isinstance(build_form, list) or len(build_form) < 4:
        raise ValueError(
            f"CSE build form: expected list of >= 4 elements, got length "
            f"{len(build_form) if isinstance(build_form, list) else 'N/A'}"
        )
    if build_form[0] != b"build":
        raise ValueError(f"CSE build form: expected tag b'build', got {build_form[0]!r}")
    return husk_tree[1], build_form[1], build_form[2], build_form[3:]

# ── Validated binding helper ──────────────────────────────────────

def _validated_binding(name_atom: bytes, hash_file: Callable[[str], bytes]) -> tuple[bytes, bytes]:
    """Validate a path atom and return (name, hash) binding."""
    name_str = atom_str(name_atom)
    _validate_husk_path(name_str)
    return (name_atom, hash_file(name_str))

# ── Recompute (pure given injected hasher) ────────────────────────

def _recompute_node(
    node: list[CseValue],
    hash_file: Callable[[str], bytes],
    version: bytes,
) -> str:
    """Recursively recompute a node's Merkle digest (pure given injected hasher)."""
    tag = node[0] if isinstance(node, list) else None

    # Terminal nodes
    if tag in (b"commit", b"halt"):
        return hashlib.sha256(encode(node)).hexdigest()

    if tag == b"cond":
        then_digest = _recompute_node(node[2], hash_file, version)
        else_digest = _recompute_node(node[3], hash_file, version)
        cse_form: CseValue = [b"cond", node[1], atom(then_digest), atom(else_digest)]
        return hashlib.sha256(encode(cse_form)).hexdigest()

    # Rule node
    name, recipe, inputs, outputs, children = _extract_rule_fields(node)
    _validate_rule_name(atom_str(name))

    child_digests = [atom(_recompute_node(c, hash_file, version)) for c in children]
    input_bindings = [_validated_binding(inp, hash_file) for inp in inputs]
    seal = compute_seal(version, recipe, input_bindings)
    output_bindings = [_validated_binding(out, hash_file) for out in outputs]

    return compute_node_digest(name, atom(seal), output_bindings, child_digests)

# ── I/O boundary ──────────────────────────────────────────────────

def _make_hash_file(site_dir: str) -> Callable[[str], bytes]:
    """Construct a hash_file closure over site_dir."""
    def hash_file(rel_path: str) -> bytes:
        path = os.path.join(site_dir, rel_path)
        if os.path.isfile(path):
            with open(path, "rb") as f:
                return content_hash(f.read())
        return ABSENT
    return hash_file


def recompute_root(husk_bytes: bytes, site_dir: str) -> str:
    """Parse a .husk file and recompute the build-root digest."""
    husk_tree = parse(husk_bytes)
    version, _build_name, _fuel, target_nodes = _extract_build(husk_tree)
    hash_file = _make_hash_file(site_dir)
    if len(target_nodes) == 1:
        return _recompute_node(target_nodes[0], hash_file, version)
    per_roots = [_recompute_node(t, hash_file, version) for t in target_nodes]
    return hashlib.sha256(b"".join(r.encode() for r in sorted(per_roots))).hexdigest()


def verify(husk_bytes: bytes, site_dir: str, expected_root: str) -> bool:
    """Verify that a husk + site reproduces the expected build-root."""
    return recompute_root(husk_bytes, site_dir) == expected_root
