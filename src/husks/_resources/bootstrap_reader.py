#!/usr/bin/env python3
"""
Minimal CSE reader for bootstrap verification.

This reader is used by the stub oracle when running core-bootstrap in --stub mode.
It implements the CSE v2 wire format verification algorithm.

Usage:
    python generated_reader.py <husk-file> <site-dir>
"""

import hashlib
import os
import sys


def sha256_hex(data):
    """SHA-256 of data, returned as lowercase hex string."""
    return hashlib.sha256(data).hexdigest()


def encode_atom(value):
    """Encode bytes as netstring: <length>:<bytes>."""
    return f"{len(value)}:".encode('ascii') + value


def encode(value):
    """Encode a CSE value to canonical wire bytes."""
    if isinstance(value, bytes):
        return encode_atom(value)
    if isinstance(value, list):
        return b"(" + b"".join(encode(child) for child in value) + b")"
    raise TypeError(f"CSE encode: expected bytes or list, got {type(value).__name__}")


def parse(data, offset=0, depth=0):
    """Parse CSE wire bytes. Returns (value, next_offset)."""
    if depth > 128:
        raise ValueError(f"Nesting depth exceeds 128 at offset {offset}")
    if offset >= len(data):
        raise ValueError("Unexpected end of data")

    # List
    if data[offset:offset+1] == b"(":
        offset += 1
        items = []
        while offset < len(data) and data[offset:offset+1] != b")":
            item, offset = parse(data, offset, depth + 1)
            items.append(item)
        if offset >= len(data):
            raise ValueError("Unterminated list")
        return items, offset + 1

    # Atom
    try:
        colon = data.index(b":", offset)
    except ValueError:
        raise ValueError(f"No colon found for atom length at offset {offset}")

    length_str = data[offset:colon]

    # Reject non-digit bytes
    for byte in length_str:
        if byte < 0x30 or byte > 0x39:
            raise ValueError(f"Non-digit byte 0x{byte:02x} in length at offset {offset}")

    # Reject leading zeros
    if len(length_str) > 1 and length_str[0:1] == b"0":
        raise ValueError(f"Leading zero in length at offset {offset}")

    length = int(length_str)
    start = colon + 1
    end = start + length
    if end > len(data):
        raise ValueError(f"Atom truncated at offset {offset}")

    return data[start:end], end


def parse_full(data):
    """Parse CSE data, consuming entire input."""
    value, rest = parse(data, 0, 0)
    if rest != len(data):
        raise ValueError(f"Trailing data at offset {rest}")
    return value


def file_hash_or_absent(path):
    """Hash file contents or return 'absent' if not a regular file."""
    if os.path.isfile(path):
        with open(path, 'rb') as f:
            return sha256_hex(f.read()).encode('ascii')
    return b"absent"


def recipe_digest(recipe_form):
    """Compute SHA-256 hex digest of recipe CSE encoding."""
    return sha256_hex(encode(recipe_form))


def compute_seal(version, recipe_form, input_bindings):
    """Compute seal hash for a rule."""
    rd = recipe_digest(recipe_form).encode('ascii')
    binding_list = [[name, h] for name, h in input_bindings]
    preimage = [b"seal", version, rd, binding_list]
    return sha256_hex(encode(preimage))


def compute_node_digest(name, seal, output_bindings, child_digests):
    """Compute a node's Merkle digest."""
    out_list = [[n, h] for n, h in output_bindings]
    child_list = list(child_digests)
    node_form = [b"node", name, seal.encode('ascii'), out_list, child_list]
    return sha256_hex(encode(node_form))


def recompute_node(rule, site_dir, version):
    """Recursively recompute node digest."""
    name = rule[1]
    recipe = rule[2]
    inputs = rule[3]
    outputs = rule[4]
    children = rule[5:] if len(rule) > 5 else []

    # Recurse into children first (bottom-up)
    child_digests = [recompute_node(child, site_dir, version).encode('ascii') for child in children]

    # Input bindings
    input_bindings = []
    for inp in inputs:
        inp_name = inp
        path = os.path.join(site_dir, inp_name.decode('utf-8'))
        h = file_hash_or_absent(path)
        input_bindings.append((inp_name, h))

    # Compute seal
    seal = compute_seal(version, recipe, input_bindings)

    # Output bindings
    output_bindings = []
    for out in outputs:
        out_name = out
        path = os.path.join(site_dir, out_name.decode('utf-8'))
        h = file_hash_or_absent(path)
        output_bindings.append((out_name, h))

    # Compute node digest
    return compute_node_digest(name, seal, output_bindings, child_digests)


def recompute_root(husk_bytes, site_dir):
    """Parse husk and recompute build-root digest."""
    husk_tree = parse_full(husk_bytes)

    # Extract build: (husk <version> (build <name> <fuel> <target-node>))
    if husk_tree[0] != b"husk":
        raise ValueError("Not a husk file")

    version = husk_tree[1]
    build = husk_tree[2]

    if build[0] != b"build":
        raise ValueError("Invalid build form")

    target_node = build[3]

    # Recompute target node digest
    return recompute_node(target_node, site_dir, version)


def main():
    """CLI entry point: python generated_reader.py <husk-file> <site-dir>"""
    if len(sys.argv) != 3:
        print("Usage: python generated_reader.py <husk-file> <site-dir>", file=sys.stderr)
        sys.exit(1)

    husk_file = sys.argv[1]
    site_dir = sys.argv[2]

    try:
        with open(husk_file, 'rb') as f:
            husk_bytes = f.read()
        root = recompute_root(husk_bytes, site_dir)
        print(root)
        sys.exit(0)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
