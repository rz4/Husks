#!/usr/bin/env python3
"""
CSE (Canonical S-Expression Encoding) Husk Verifier
Dependency-free implementation using only stdlib (hashlib, sys, os).
Implements byte-level netstring parser with strict conformance to CSE-v1/v2.
"""

import hashlib
import sys
import os


class ParseError(Exception):
    """Raised when CSE parsing fails."""
    pass


class CSEParser:
    """Byte-level netstring/S-expression parser for CSE."""
    
    def __init__(self, data):
        self.data = data
        self.pos = 0
    
    def parse(self):
        """Parse a single CSE value and ensure all input is consumed."""
        value = self._parse_value()
        if self.pos != len(self.data):
            raise ParseError(f"Trailing bytes after root value: {self.pos} != {len(self.data)}")
        return value
    
    def _parse_value(self):
        """Parse either an atom or a list."""
        if self.pos >= len(self.data):
            raise ParseError("Unexpected end of input")
        
        ch = self.data[self.pos:self.pos+1]
        
        if ch == b'(':
            return self._parse_list()
        else:
            return self._parse_atom()
    
    def _parse_atom(self):
        """Parse a netstring atom: <length>:<bytes>"""
        # Read decimal length
        length_start = self.pos
        while self.pos < len(self.data) and self.data[self.pos:self.pos+1] != b':':
            self.pos += 1
        
        if self.pos >= len(self.data):
            raise ParseError("Atom length missing colon terminator")
        
        length_bytes = self.data[length_start:self.pos]
        
        if not length_bytes:
            raise ParseError("Empty atom length")
        
        # Reject leading zeros
        if len(length_bytes) > 1 and length_bytes[0:1] == b'0':
            raise ParseError("Atom length has leading zero")
        
        try:
            length = int(length_bytes)
        except ValueError:
            raise ParseError(f"Invalid atom length: {length_bytes}")
        
        if length < 0:
            raise ParseError(f"Negative atom length: {length}")
        
        # Skip the colon
        self.pos += 1
        
        # Check that we have enough bytes remaining
        if self.pos + length > len(self.data):
            raise ParseError(f"Atom length {length} exceeds remaining bytes")
        
        # Read the atom bytes
        atom = self.data[self.pos:self.pos + length]
        self.pos += length
        
        return atom
    
    def _parse_list(self):
        """Parse a list: ( <values>* )"""
        if self.data[self.pos:self.pos+1] != b'(':
            raise ParseError("Expected '('")
        self.pos += 1
        
        values = []
        while self.pos < len(self.data):
            ch = self.data[self.pos:self.pos+1]
            if ch == b')':
                self.pos += 1
                return values
            values.append(self._parse_value())
        
        raise ParseError("Unclosed list")


def atom_to_str(atom):
    """Convert atom bytes to string (for display and name matching)."""
    if isinstance(atom, bytes):
        return atom.decode('utf-8', errors='replace')
    return str(atom)


def atom_to_bytes(atom):
    """Ensure atom is bytes."""
    if isinstance(atom, bytes):
        return atom
    return str(atom).encode('utf-8')


def sha256_hex(data):
    """Compute SHA-256 hash as lowercase hex string."""
    return hashlib.sha256(data).hexdigest()


def cse_encode(value):
    """Encode a value to CSE bytes."""
    if isinstance(value, bytes):
        # Atom: <length>:<bytes>
        length_str = str(len(value)).encode('ascii')
        return length_str + b':' + value
    elif isinstance(value, list):
        # List: ( values* )
        result = b'('
        for v in value:
            result += cse_encode(v)
        result += b')'
        return result
    else:
        raise ValueError(f"Invalid CSE value type: {type(value)}")


def verify_husk(husk_path, site_dir):
    """
    Parse husk file and compute build-root digest.
    
    Args:
        husk_path: path to .husk file
        site_dir: path to site directory containing input/output files
    
    Returns:
        build-root digest as lowercase hex string
    
    Raises:
        ParseError or other exceptions on CSE violations
    """
    with open(husk_path, 'rb') as f:
        husk_bytes = f.read()
    
    # Parse the husk CSE
    parser = CSEParser(husk_bytes)
    husk = parser.parse()
    
    if not isinstance(husk, list) or len(husk) < 3:
        raise ParseError("Invalid husk form")
    
    husk_tag = husk[0]
    husk_version = husk[1]
    build = husk[2]
    
    if husk_tag != b'husk':
        raise ParseError(f"Expected husk tag, got {husk_tag}")
    if husk_version != b'1':
        raise ParseError(f"Expected version 1, got {husk_version}")
    
    if not isinstance(build, list) or len(build) < 4:
        raise ParseError("Invalid build form")
    
    build_tag = build[0]
    build_name = build[1]
    build_fuel = build[2]
    target_node = build[3]
    
    if build_tag != b'build':
        raise ParseError(f"Expected build tag, got {build_tag}")
    
    # Verify the target node recursively
    root_digest = recompute_node(target_node, site_dir)
    return root_digest


def recompute_node(node, site_dir):
    """
    Recursively compute the node digest for a rule node.
    
    Args:
        node: parsed rule form (list)
        site_dir: site directory path
    
    Returns:
        node digest as lowercase hex string (64-byte atom content)
    """
    if not isinstance(node, list) or len(node) < 5:
        raise ParseError("Invalid rule form: must have at least 5 elements")
    
    rule_tag = node[0]
    if rule_tag != b'rule':
        raise ParseError(f"Expected rule tag, got {rule_tag}")
    
    name = node[1]
    recipe = node[2]
    inputs_list = node[3]
    outputs_list = node[4]
    
    # Extract children from positions 5+
    children = node[5:] if len(node) > 5 else []
    
    # Validate list structures
    if not isinstance(inputs_list, list):
        raise ParseError("Inputs must be a list")
    if not isinstance(outputs_list, list):
        raise ParseError("Outputs must be a list")
    
    # Recursively verify children in positional order
    child_digests = []
    for child in children:
        child_digest = recompute_node(child, site_dir)
        child_digests.append(child_digest)
    
    # Compute recipe digest
    recipe_cse = cse_encode(recipe)
    recipe_digest_hex = sha256_hex(recipe_cse)
    recipe_digest_atom = recipe_digest_hex.encode('ascii')
    
    # Compute input bindings
    input_bindings = []
    for input_name in inputs_list:
        input_name_str = atom_to_str(input_name)
        input_path = os.path.join(site_dir, input_name_str)
        
        if os.path.exists(input_path):
            with open(input_path, 'rb') as f:
                input_data = f.read()
            input_hash_hex = sha256_hex(input_data)
            input_hash_atom = input_hash_hex.encode('ascii')
        else:
            input_hash_atom = b'absent'
        
        input_bindings.append([input_name, input_hash_atom])
    
    # Build seal preimage
    seal_preimage = [
        b'seal',
        b'1',
        recipe_digest_atom,
        input_bindings
    ]
    
    # Compute seal
    seal_preimage_cse = cse_encode(seal_preimage)
    seal_hex = sha256_hex(seal_preimage_cse)
    seal_atom = seal_hex.encode('ascii')
    
    # Compute output bindings
    output_bindings = []
    for output_name in outputs_list:
        output_name_str = atom_to_str(output_name)
        output_path = os.path.join(site_dir, output_name_str)
        
        if os.path.exists(output_path):
            with open(output_path, 'rb') as f:
                output_data = f.read()
            output_hash_hex = sha256_hex(output_data)
            output_hash_atom = output_hash_hex.encode('ascii')
        else:
            output_hash_atom = b'absent'
        
        output_bindings.append([output_name, output_hash_atom])
    
    # Convert child_digests (strings) to atoms
    child_digest_atoms = [d.encode('ascii') if isinstance(d, str) else d for d in child_digests]
    
    # Build node form
    node_form = [
        b'node',
        name,
        seal_atom,
        output_bindings,
        child_digest_atoms
    ]
    
    # Compute node digest
    node_form_cse = cse_encode(node_form)
    node_digest_hex = sha256_hex(node_form_cse)
    
    return node_digest_hex


def main():
    """Command-line entry point."""
    if len(sys.argv) != 3:
        print(f"Usage: {sys.argv[0]} <husk-file> <site-dir>", file=sys.stderr)
        sys.exit(1)
    
    husk_file = sys.argv[1]
    site_dir = sys.argv[2]
    
    try:
        root_digest = verify_husk(husk_file, site_dir)
        print(root_digest)
        sys.exit(0)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == '__main__':
    main()
