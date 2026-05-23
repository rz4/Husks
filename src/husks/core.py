"""
core.py — Dependency-free CSE reader/verifier (stdlib only).

Canonical S-Expression Encoding (CSE) v1:
  atom  → b"<length>:<bytes>"
  list  → b"(" + children + b")"
  NIL   → b"0:"

This module imports NOTHING from husks.* and uses only the Python
standard library. Any conformant implementation in any language can
reproduce the same hashes from the same inputs.
"""

import hashlib
import os

# ── Constants ──────────────────────────────────────────────────────

NIL = b""
CSE_VERSION = b"1"
ABSENT = b"absent"


# ── CSE Encode ─────────────────────────────────────────────────────

def encode(value):
    """Encode a CSE value (bytes atom or list of CSE values) to canonical bytes."""
    if isinstance(value, bytes):
        return b"%d:%s" % (len(value), value)
    if isinstance(value, list):
        return b"(" + b"".join(encode(child) for child in value) + b")"
    raise TypeError(f"CSE encode: expected bytes or list, got {type(value).__name__}")


# ── CSE Parse ──────────────────────────────────────────────────────

def parse(data):
    """Parse canonical CSE bytes into a value. Returns (value, remaining)."""
    if isinstance(data, (bytes, memoryview)):
        value, rest = _parse(data, 0)
        if rest != len(data):
            raise ValueError(f"CSE parse: trailing data at offset {rest}")
        return value
    raise TypeError(f"CSE parse: expected bytes, got {type(data).__name__}")


def _parse(data, offset):
    """Internal recursive parser. Returns (value, next_offset)."""
    if offset >= len(data):
        raise ValueError("CSE parse: unexpected end of data")

    if data[offset:offset+1] == b"(":
        # List
        offset += 1
        items = []
        while offset < len(data) and data[offset:offset+1] != b")":
            item, offset = _parse(data, offset)
            items.append(item)
        if offset >= len(data):
            raise ValueError("CSE parse: unterminated list")
        offset += 1  # skip ')'
        return items, offset

    # Atom: read length prefix
    colon = data.index(ord(b":") if isinstance(data[offset], int) else b":", offset)
    length_str = data[offset:colon]

    # Reject leading zeros (except "0" itself)
    if len(length_str) > 1 and length_str[0:1] == b"0":
        raise ValueError(f"CSE parse: leading zero in length at offset {offset}")

    length = int(length_str)
    start = colon + 1
    end = start + length
    if end > len(data):
        raise ValueError(f"CSE parse: atom truncated at offset {offset}")
    return bytes(data[start:end]), end


# ── Helpers ────────────────────────────────────────────────────────

def atom_str(b):
    """Decode a bytes atom to a UTF-8 string."""
    return b.decode("utf-8")


def atom(s):
    """Encode a UTF-8 string to a bytes atom."""
    if isinstance(s, str):
        return s.encode("utf-8")
    return s


# ── Hashing ────────────────────────────────────────────────────────

def sha256_bytes(data):
    """SHA-256 of raw bytes, returned as lowercase hex bytes."""
    return hashlib.sha256(data).hexdigest().encode("ascii")


def content_hash(file_bytes):
    """SHA-256 of file contents, returned as bytes atom (lowercase hex)."""
    return sha256_bytes(file_bytes)


def content_hash_or_absent(path):
    """Hash a file path, returning ABSENT if missing."""
    if os.path.isfile(path):
        with open(path, "rb") as f:
            return content_hash(f.read())
    return ABSENT


# ── Seal computation ───────────────────────────────────────────────

def recipe_digest(recipe_form):
    """SHA-256 hex string of the CSE encoding of a recipe form."""
    return hashlib.sha256(encode(recipe_form)).hexdigest()


def compute_seal(version, recipe_form, input_bindings):
    """
    Compute the seal hash.

    seal-preimage = (4:seal <version> <recipe-digest> ( (name hash)* ))
    seal = SHA256(CSE(seal-preimage))

    input_bindings: list of (name_bytes, hash_bytes) pairs, already sorted.
    """
    rd = atom(recipe_digest(recipe_form))
    binding_list = [
        [name, h] for name, h in input_bindings
    ]
    preimage = [b"seal", version, rd, binding_list]
    return hashlib.sha256(encode(preimage)).hexdigest()


# ── Merkle DAG ─────────────────────────────────────────────────────

def compute_node_digest(name, seal, output_bindings, child_digests):
    """
    Compute a node's Merkle digest.

    node-form = (4:node <name> <seal> ( (name hash)* ) ( digest* ))
    digest = SHA256(CSE(node-form))

    output_bindings: list of (name_bytes, hash_bytes) pairs.
    child_digests: list of digest bytes atoms.
    """
    out_list = [[n, h] for n, h in output_bindings]
    child_list = list(child_digests)
    node_form = [b"node", name, seal, out_list, child_list]
    return hashlib.sha256(encode(node_form)).hexdigest()


# ── Husk structure extraction ──────────────────────────────────────

def _extract_recipe_form(rule_node):
    """Extract the recipe sub-form from a parsed rule node.
    rule = (4:rule <name> <recipe> ( inputs... ) ( outputs... ) children... )
    recipe is the 3rd element (index 2).
    """
    return rule_node[2]


def _extract_rule_fields(rule_node):
    """
    Extract fields from a parsed rule node.
    rule = (4:rule <name> <recipe> ( inputs... ) ( outputs... ) children... )

    Returns (name, recipe, inputs, outputs, children) where:
      - name: bytes
      - recipe: CSE value (list or atom)
      - inputs: list of bytes (file names)
      - outputs: list of bytes (file names)
      - children: list of rule nodes
    """
    name = rule_node[1]
    recipe = rule_node[2]
    inputs = rule_node[3]   # list of name atoms
    outputs = rule_node[4]  # list of name atoms
    children = rule_node[5:]  # remaining elements are child rule nodes
    return name, recipe, inputs, outputs, children


def _extract_build(husk_tree):
    """
    Extract build fields from the top-level husk.
    husk = (4:husk 1:1 (5:build <name> <fuel> <target-node>))

    Returns (build_name, fuel, target_node).
    """
    # husk_tree = [b"husk", version, build_form]
    build_form = husk_tree[2]
    # build_form = [b"build", name, fuel, target_node]
    build_name = build_form[1]
    fuel = build_form[2]
    target_node = build_form[3]
    return build_name, fuel, target_node


# ── Recompute root ─────────────────────────────────────────────────

def _recompute_node(rule_node, site_dir):
    """
    Recursively recompute a node's digest from the site directory.
    Returns the hex digest string for this node.
    """
    name, recipe, inputs, outputs, children = _extract_rule_fields(rule_node)

    # Recurse into children first (depth-first)
    child_digests = []
    for child in children:
        cd = _recompute_node(child, site_dir)
        child_digests.append(atom(cd))

    # Compute input bindings: (name, content_hash)
    input_bindings = []
    for inp in inputs:
        inp_name = atom_str(inp)
        path = os.path.join(site_dir, inp_name)
        h = content_hash_or_absent(path)
        input_bindings.append((inp, h))

    # Compute seal
    seal = compute_seal(CSE_VERSION, recipe, input_bindings)

    # Compute output bindings: (name, content_hash)
    output_bindings = []
    for out in outputs:
        out_name = atom_str(out)
        path = os.path.join(site_dir, out_name)
        h = content_hash_or_absent(path)
        output_bindings.append((out, h))

    # Compute node digest
    digest = compute_node_digest(name, atom(seal), output_bindings, child_digests)
    return digest


def recompute_root(husk_bytes, site_dir):
    """
    Parse a husk file and recompute the build-root digest from the site directory.
    Returns the root digest as a lowercase hex string.
    """
    husk_tree = parse(husk_bytes)
    _build_name, _fuel, target_node = _extract_build(husk_tree)
    return _recompute_node(target_node, site_dir)


def verify(husk_bytes, site_dir, expected_root):
    """
    Verify that a husk + site reproduces the expected build-root.
    Returns True if the recomputed root matches expected_root.
    """
    return recompute_root(husk_bytes, site_dir) == expected_root
