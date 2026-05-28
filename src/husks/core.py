"""
core.py -- CSE codec, content-addressed seals, and Merkle DAG verification.

The permanence layer.  Implements the frozen CSE v1 wire format, seal
preimage construction, and node-digest algorithm.  Dependency-free:
imports only stdlib (hashlib, os).  No sibling imports.

See docs/architecture.md for wire format grammar, seal preimage
construction, node digest algorithm, and type discipline.
"""

from __future__ import annotations

import hashlib
import os
from typing import Union

# ── CSE value type ────────────────────────────────────────────────

CseValue = Union[bytes, list["CseValue"]]


# ── Constants ─────────────────────────────────────────────────────

NIL: bytes = b""
CSE_VERSION: bytes = b"2"
ABSENT: bytes = b"absent"

# Maximum nesting depth for the recursive parser.  CSE trees in
# practice are shallow (build > rule > recipe > atoms), but we
# bound recursion defensively to prevent stack overflow on
# adversarial input.
_MAX_PARSE_DEPTH: int = 128

# Maximum atom length the parser will accept (256 MiB).  Prevents
# a malicious length prefix from causing an unbounded allocation.
_MAX_ATOM_LENGTH: int = 256 * 1024 * 1024


# ── CSE Encode ────────────────────────────────────────────────────

def encode(value: CseValue) -> bytes:
    """Serialize a CSE value to canonical wire bytes.

    Atoms become ``<length>:<bytes>``.  Lists become ``(`` + children + ``)``.
    Raises TypeError on any value that is not bytes or list.
    """
    if isinstance(value, bytes):
        return b"%d:%s" % (len(value), value)
    if isinstance(value, list):
        return b"(" + b"".join(encode(child) for child in value) + b")"
    raise TypeError(
        f"CSE encode: expected bytes or list, got {type(value).__name__}"
    )


# ── CSE Parse ─────────────────────────────────────────────────────

def parse(data: bytes | memoryview) -> CseValue:
    """Parse canonical CSE wire bytes into a value tree.

    Consumes exactly the full extent of *data*.  Raises ValueError if
    there is trailing data, if the input is truncated, if a length
    prefix contains leading zeros, or if nesting exceeds the safety
    limit.  Raises TypeError if *data* is not bytes or memoryview.
    """
    if not isinstance(data, (bytes, memoryview)):
        raise TypeError(
            f"CSE parse: expected bytes, got {type(data).__name__}"
        )
    value, rest = _parse(data, 0, 0)
    if rest != len(data):
        raise ValueError(f"CSE parse: trailing data at offset {rest}")
    return value


def _parse(data: bytes | memoryview, offset: int, depth: int) -> tuple[CseValue, int]:
    """Recursive descent parser.  Returns (value, next_offset)."""
    if depth > _MAX_PARSE_DEPTH:
        raise ValueError(
            f"CSE parse: nesting depth exceeds {_MAX_PARSE_DEPTH} at offset {offset}"
        )
    if offset >= len(data):
        raise ValueError("CSE parse: unexpected end of data")

    # ── List ──────────────────────────────────────────────────
    if data[offset : offset + 1] == b"(":
        offset += 1
        items: list[CseValue] = []
        while offset < len(data) and data[offset : offset + 1] != b")":
            item, offset = _parse(data, offset, depth + 1)
            items.append(item)
        if offset >= len(data):
            raise ValueError("CSE parse: unterminated list")
        return items, offset + 1  # skip ')'

    # ── Atom ──────────────────────────────────────────────────
    # Find the colon separating the length prefix from the payload.
    try:
        colon = data.index(
            ord(b":") if isinstance(data[offset], int) else b":",
            offset,
        )
    except ValueError:
        raise ValueError(
            f"CSE parse: no colon found for atom length at offset {offset}"
        ) from None

    length_str = data[offset:colon]

    # Reject non-digit bytes in the length prefix.
    for i, byte in enumerate(length_str):
        b = byte if isinstance(byte, int) else ord(byte)
        if b < 0x30 or b > 0x39:  # '0' .. '9'
            raise ValueError(
                f"CSE parse: non-digit byte 0x{b:02x} in length at offset {offset + i}"
            )

    # Reject leading zeros (except the literal "0" for zero-length atoms).
    if len(length_str) > 1 and length_str[0:1] == b"0":
        raise ValueError(
            f"CSE parse: leading zero in length at offset {offset}"
        )

    length = int(length_str)

    if length > _MAX_ATOM_LENGTH:
        raise ValueError(
            f"CSE parse: atom length {length} exceeds maximum "
            f"{_MAX_ATOM_LENGTH} at offset {offset}"
        )

    start = colon + 1
    end = start + length
    if end > len(data):
        raise ValueError(f"CSE parse: atom truncated at offset {offset}")

    return bytes(data[start:end]), end


# ── Atom helpers ──────────────────────────────────────────────────

def atom_str(b: bytes) -> str:
    """Decode a CSE bytes atom to a Python str (UTF-8).

    Raises UnicodeDecodeError if the atom is not valid UTF-8.
    """
    return b.decode("utf-8")


def atom(s: str | bytes) -> bytes:
    """Coerce a Python str to a CSE bytes atom (UTF-8).

    If *s* is already bytes, it is returned unchanged.
    """
    if isinstance(s, str):
        return s.encode("utf-8")
    return s


# ── Hashing ───────────────────────────────────────────────────────

def sha256_bytes(data: bytes) -> bytes:
    """SHA-256 of *data*, returned as lowercase hex encoded to ASCII bytes.

    The return type is bytes so the result can be embedded directly as
    a CSE atom without an additional encode step.
    """
    return hashlib.sha256(data).hexdigest().encode("ascii")


def content_hash(file_bytes: bytes) -> bytes:
    """SHA-256 of file contents, returned as a lowercase hex bytes atom."""
    return sha256_bytes(file_bytes)


def content_hash_or_absent(path: str) -> bytes:
    """Hash the file at *path*, returning ABSENT if the path does not
    refer to a regular file.

    Directories, symlinks to directories, and missing paths all yield
    ABSENT.  This is intentional: the seal treats anything that is not
    a readable regular file as absent rather than silently hashing a
    directory listing or following an unexpected symlink.
    """
    if os.path.isfile(path):
        with open(path, "rb") as f:
            return content_hash(f.read())
    return ABSENT


# ── Seal computation ──────────────────────────────────────────────

def recipe_digest(recipe_form: CseValue) -> str:
    """SHA-256 hex string of the CSE encoding of a recipe form.

    The recipe form is a CSE value (typically a list such as
    ``[b"oracle", name, prompt, tools, fuel]``).  The digest is
    computed over the canonical wire bytes, ensuring that any two
    recipe forms that encode identically produce the same digest.
    """
    return hashlib.sha256(encode(recipe_form)).hexdigest()


def compute_seal(
    version: bytes,
    recipe_form: CseValue,
    input_bindings: list[tuple[bytes, bytes]],
) -> str:
    """Compute the seal hash for a rule.

    Parameters
    ----------
    version : bytes
        CSE format version (currently ``b"1"``).
    recipe_form : CseValue
        The CSE-serializable recipe (action/oracle/trial form).
    input_bindings : list of (name, hash) byte pairs
        Declared inputs and their content hashes, already sorted by
        name.  Each *hash* is a lowercase hex bytes atom or ABSENT.

    Returns
    -------
    str
        Lowercase hex SHA-256 digest of the seal preimage.
    """
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
    """Compute a node's Merkle digest.

    Parameters
    ----------
    name : bytes
        Rule name as a CSE atom.
    seal : bytes
        Hex seal hash as a CSE atom (from compute_seal).
    output_bindings : list of (name, hash) byte pairs
        Declared outputs and their content hashes.
    child_digests : list of bytes
        Hex digest atoms of child nodes (already computed bottom-up).

    Returns
    -------
    str
        Lowercase hex SHA-256 digest of the node form.
    """
    out_list: list[CseValue] = [[n, h] for n, h in output_bindings]
    child_list: list[CseValue] = list(child_digests)
    node_form: CseValue = [b"node", name, seal, out_list, child_list]
    return hashlib.sha256(encode(node_form)).hexdigest()


# ── Path validation (security) ────────────────────────────────────

def _validate_husk_path(name: str) -> None:
    """Validate a path from a .husk file, rejecting security violations.

    A malicious .husk file could contain absolute paths (e.g., "/etc/passwd")
    or traversal paths (e.g., "../../secret") in its input/output declarations.
    This function rejects such paths to ensure recompute_root() only reads
    files inside the site directory.

    Parameters
    ----------
    name : str
        Path string from the .husk file (from inputs or outputs list).

    Raises
    ------
    ValueError
        If the path is empty, absolute, or contains .. components.
    """
    if not name:
        raise ValueError("empty path in .husk")

    # Reject absolute paths (Unix: /foo, Windows: C:\foo or C:/foo)
    if os.path.isabs(name):
        raise ValueError(f"absolute path in .husk: {name}")

    # Reject path traversal attempts
    # Check each component for ".." to prevent escaping site directory
    parts = name.split(os.sep)
    if os.altsep:  # Windows supports both \ and /
        for part in parts:
            if os.altsep in part:
                parts.extend(part.split(os.altsep))

    for part in parts:
        if part == "..":
            raise ValueError(f"path traversal in .husk: {name}")


# ── Husk structure extraction ─────────────────────────────────────

def _extract_rule_fields(
    rule_node: list[CseValue],
) -> tuple[bytes, CseValue, list[bytes], list[bytes], list[list[CseValue]]]:
    """Destructure a parsed CSE rule node.

    Expected layout::

        (4:rule <name> <recipe> ( inputs... ) ( outputs... ) children... )

    Returns (name, recipe, inputs, outputs, children).

    Raises ValueError if the node does not have the minimum required
    structure (tag + name + recipe + inputs + outputs = 5 elements).
    """
    if not isinstance(rule_node, list) or len(rule_node) < 5:
        raise ValueError(
            f"CSE rule node: expected list of >= 5 elements, "
            f"got {type(rule_node).__name__} of length "
            f"{len(rule_node) if isinstance(rule_node, list) else 'N/A'}"
        )
    if rule_node[0] != b"rule":
        raise ValueError(
            f"CSE rule node: expected tag b'rule', got {rule_node[0]!r}"
        )
    name: bytes = rule_node[1]
    recipe: CseValue = rule_node[2]
    inputs: list[bytes] = rule_node[3]
    outputs: list[bytes] = rule_node[4]
    children: list[list[CseValue]] = rule_node[5:]
    return name, recipe, inputs, outputs, children


def _extract_build(
    husk_tree: list[CseValue],
) -> tuple[bytes, bytes, bytes, list[list[CseValue]]]:
    """Destructure a top-level husk tree.

    Expected layout::

        (4:husk 1:1 (5:build <name> <fuel> <target-node> ...))

    Returns (version, build_name, fuel, target_nodes) where target_nodes
    is a list of one or more target node trees (``build_form[3:]``).

    Raises ValueError if the structure does not match.
    """
    if not isinstance(husk_tree, list) or len(husk_tree) < 3:
        raise ValueError(
            "CSE husk: expected list of >= 3 elements "
            f"(husk version build), got length "
            f"{len(husk_tree) if isinstance(husk_tree, list) else 'N/A'}"
        )
    if husk_tree[0] != b"husk":
        raise ValueError(
            f"CSE husk: expected tag b'husk', got {husk_tree[0]!r}"
        )
    version: bytes = husk_tree[1]
    build_form = husk_tree[2]
    if not isinstance(build_form, list) or len(build_form) < 4:
        raise ValueError(
            "CSE build form: expected list of >= 4 elements "
            f"(build name fuel target...), got length "
            f"{len(build_form) if isinstance(build_form, list) else 'N/A'}"
        )
    if build_form[0] != b"build":
        raise ValueError(
            f"CSE build form: expected tag b'build', got {build_form[0]!r}"
        )
    build_name: bytes = build_form[1]
    fuel: bytes = build_form[2]
    target_nodes: list[list[CseValue]] = build_form[3:]
    return version, build_name, fuel, target_nodes


# ── Recompute root ────────────────────────────────────────────────

def _recompute_node(node: list[CseValue], site_dir: str, version: bytes) -> str:
    """Recursively recompute a node's Merkle digest from the site directory.

    Walks the tree depth-first, bottom-up: child digests are computed
    before the parent.  Returns the hex digest string for this node.

    The *version* atom (extracted from the husk) is threaded through to
    compute_seal so that v1 and v2 husks verify correctly.

    Handles rule, commit, halt, and cond node types.
    """
    tag = node[0] if isinstance(node, list) else None

    # Terminal nodes: digest is the hash of their CSE encoding
    if tag in (b"commit", b"halt"):
        return hashlib.sha256(encode(node)).hexdigest()

    if tag == b"cond":
        then_digest = _recompute_node(node[2], site_dir, version)
        else_digest = _recompute_node(node[3], site_dir, version)
        cse_form: CseValue = [b"cond", node[1], atom(then_digest), atom(else_digest)]
        return hashlib.sha256(encode(cse_form)).hexdigest()

    # Rule node
    name, recipe, inputs, outputs, children = _extract_rule_fields(node)

    # Children first (depth-first)
    child_digests: list[bytes] = []
    for child in children:
        cd = _recompute_node(child, site_dir, version)
        child_digests.append(atom(cd))

    # Input bindings: (name, content_hash)
    input_bindings: list[tuple[bytes, bytes]] = []
    for inp in inputs:
        inp_str = atom_str(inp)
        _validate_husk_path(inp_str)  # Security: reject absolute/traversal paths
        path = os.path.join(site_dir, inp_str)
        h = content_hash_or_absent(path)
        input_bindings.append((inp, h))

    # Seal — use the version from the husk, not the global constant
    seal = compute_seal(version, recipe, input_bindings)

    # Output bindings: (name, content_hash)
    output_bindings: list[tuple[bytes, bytes]] = []
    for out in outputs:
        out_str = atom_str(out)
        _validate_husk_path(out_str)  # Security: reject absolute/traversal paths
        path = os.path.join(site_dir, out_str)
        h = content_hash_or_absent(path)
        output_bindings.append((out, h))

    return compute_node_digest(name, atom(seal), output_bindings, child_digests)


def recompute_root(husk_bytes: bytes, site_dir: str) -> str:
    """Parse a .husk file and recompute the build-root digest.

    This is the primary verification entry point.  Given the raw CSE
    bytes of a husk record and the path to the site directory containing
    the artifacts, it reconstructs the full Merkle DAG and returns the
    root digest.  If this digest matches the expected root, the build
    is verified: every recipe, input, output, and dependency edge is
    covered by the hash.

    For multi-target builds, per-target roots are computed independently
    and combined into a single root by hashing the sorted per-target
    roots together (matching the engine-side algorithm in build.py).

    Parameters
    ----------
    husk_bytes : bytes
        Raw CSE wire bytes of the .husk file.
    site_dir : str
        Path to the site directory containing input/output artifacts.

    Returns
    -------
    str
        Lowercase hex SHA-256 build-root digest.
    """
    husk_tree = parse(husk_bytes)
    version, _build_name, _fuel, target_nodes = _extract_build(husk_tree)
    if len(target_nodes) == 1:
        return _recompute_node(target_nodes[0], site_dir, version)
    per_roots = [_recompute_node(t, site_dir, version) for t in target_nodes]
    return hashlib.sha256(
        b"".join(r.encode() for r in sorted(per_roots))
    ).hexdigest()


def verify(husk_bytes: bytes, site_dir: str, expected_root: str) -> bool:
    """Verify that a husk + site reproduces the expected build-root.

    Equivalent to ``recompute_root(husk_bytes, site_dir) == expected_root``
    but reads as a clear predicate at call sites.
    """
    return recompute_root(husk_bytes, site_dir) == expected_root
