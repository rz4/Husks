#!/usr/bin/env python3
"""
CSE (Canonical S-Expression Encoding) Reader for Husks.
Parses CSE bytes and computes deterministic Merkle digests.
Uses only Python standard library: hashlib, sys, os.
"""

import hashlib
import sys
import os


class CSEParser:
    """Byte-level netstring parser for CSE format."""
    
    def __init__(self, data):
        self.data = data
        self.pos = 0
    
    def parse(self):
        """Parse a CSE value (atom or list) from current position."""
        value = self._parse_value()
        if self.pos != len(self.data):
            raise ValueError("Trailing bytes after root value")
        return value
    
    def _parse_value(self):
        """Parse a single CSE value (atom or list)."""
        if self.pos >= len(self.data):
            raise ValueError("Unexpected end of input")
        
        ch = self.data[self.pos:self.pos+1]
        
        if ch == b'(':
            return self._parse_list()
        elif ch.isdigit():
            return self._parse_atom()
        else:
            raise ValueError(f"Unexpected character: {ch}")
    
    def _parse_atom(self):
        """Parse a netstring atom: <length>:<bytes>."""
        # Parse decimal length
        start = self.pos
        while self.pos < len(self.data) and self.data[self.pos:self.pos+1].isdigit():
            self.pos += 1
        
        length_str = self.data[start:self.pos].decode('ascii')
        
        # Check for leading zeros
        if len(length_str) > 1 and length_str[0] == '0':
            raise ValueError(f"Leading zero in atom length: {length_str}")
        
        length = int(length_str)
        
        # Expect colon
        if self.pos >= len(self.data) or self.data[self.pos:self.pos+1] != b':':
            raise ValueError("Expected colon after atom length")
        self.pos += 1
        
        # Check that declared length doesn't exceed remaining bytes
        if self.pos + length > len(self.data):
            raise ValueError("Atom length exceeds remaining bytes")
        
        # Extract atom bytes
        atom_bytes = self.data[self.pos:self.pos+length]
        self.pos += length
        
        return atom_bytes
    
    def _parse_list(self):
        """Parse a list: ( <values>* )."""
        if self.data[self.pos:self.pos+1] != b'(':
            raise ValueError("Expected open paren")
        self.pos += 1
        
        values = []
        while self.pos < len(self.data):
            ch = self.data[self.pos:self.pos+1]
            if ch == b')':
                self.pos += 1
                return values
            values.append(self._parse_value())
        
        raise ValueError("Unexpected end of input in list")


def cse_encode(value):
    """Encode a value as CSE bytes."""
    if isinstance(value, bytes):
        # Atom: encode as netstring
        length_str = str(len(value)).encode('ascii')
        return length_str + b':' + value
    elif isinstance(value, list):
        # List: encode children and wrap in parens
        result = b'('
        for item in value:
            result += cse_encode(item)
        result += b')'
        return result
    else:
        raise ValueError(f"Invalid CSE value type: {type(value)}")


def sha256_hex(data):
    """Compute SHA-256 hash as lowercase hex string."""
    return hashlib.sha256(data).hexdigest()


def file_hash(path):
    """Compute SHA-256 of file contents, or b'absent' if missing."""
    try:
        with open(path, 'rb') as f:
            return sha256_hex(f.read()).encode('ascii')
    except (FileNotFoundError, IOError):
        return b'absent'


def parse_husk(data):
    """Parse husk CSE bytes and extract the build's target node."""
    parser = CSEParser(data)
    husk = parser.parse()
    
    if not isinstance(husk, list) or len(husk) < 3:
        raise ValueError("Invalid husk structure")
    
    tag = husk[0]
    if tag != b'husk':
        raise ValueError(f"Expected 'husk' tag, got {tag}")
    
    version = husk[1]
    if version != b'1':
        raise ValueError(f"Unsupported husk version: {version}")
    
    build = husk[2]
    if not isinstance(build, list) or len(build) < 4:
        raise ValueError("Invalid build structure")
    
    build_tag = build[0]
    if build_tag != b'build':
        raise ValueError(f"Expected 'build' tag, got {build_tag}")
    
    target_node = build[3]
    if not isinstance(target_node, list):
        raise ValueError("Target node is not a list")
    
    return target_node


def recompute_node(node, site_dir):
    """
    Compute the node digest for a rule node.
    
    Args:
        node: A parsed rule form (list)
        site_dir: Path to the site directory
    
    Returns:
        The lowercase hex node digest (64-byte string as bytes)
    """
    if not isinstance(node, list) or len(node) < 5:
        raise ValueError("Invalid rule form")
    
    tag = node[0]
    if tag != b'rule':
        raise ValueError(f"Expected 'rule' tag, got {tag}")
    
    name = node[1]
    recipe = node[2]
    inputs_list = node[3]
    outputs_list = node[4]
    
    if not isinstance(inputs_list, list):
        raise ValueError("Inputs is not a list")
    if not isinstance(outputs_list, list):
        raise ValueError("Outputs is not a list")
    
    # Extract children (indices 5+)
    children = node[5:] if len(node) > 5 else []
    
    # Step 3b: Recursively process children in positional order
    child_digests = []
    for child in children:
        child_digest = recompute_node(child, site_dir)
        child_digests.append(child_digest)
    
    # Step 3c: Compute input bindings
    input_bindings = []
    for input_name in inputs_list:
        if not isinstance(input_name, bytes):
            raise ValueError("Input name is not an atom")
        input_path = os.path.join(site_dir, input_name.decode('utf-8', errors='replace'))
        input_hash = file_hash(input_path)
        input_bindings.append([input_name, input_hash])
    
    # Step 3d: Compute recipe digest
    recipe_cse = cse_encode(recipe)
    recipe_digest = sha256_hex(recipe_cse).encode('ascii')
    
    # Step 3e: Construct seal preimage and compute seal
    seal_preimage = [
        b'seal',
        b'1',
        recipe_digest,
        input_bindings
    ]
    seal_preimage_cse = cse_encode(seal_preimage)
    seal = sha256_hex(seal_preimage_cse).encode('ascii')
    
    # Step 3f: Compute output bindings
    output_bindings = []
    for output_name in outputs_list:
        if not isinstance(output_name, bytes):
            raise ValueError("Output name is not an atom")
        output_path = os.path.join(site_dir, output_name.decode('utf-8', errors='replace'))
        output_hash = file_hash(output_path)
        output_bindings.append([output_name, output_hash])
    
    # Step 3g: Construct node form and compute node digest
    node_form = [
        b'node',
        name,
        seal,
        output_bindings,
        child_digests
    ]
    node_form_cse = cse_encode(node_form)
    node_digest = sha256_hex(node_form_cse).encode('ascii')
    
    return node_digest


def main():
    """Main entry point: parse husk file and compute build-root."""
    if len(sys.argv) != 3:
        sys.stderr.write("Usage: python generated_reader.py <husk-file> <site-dir>\n")
        sys.exit(1)
    
    husk_file = sys.argv[1]
    site_dir = sys.argv[2]
    
    try:
        # Read husk file
        with open(husk_file, 'rb') as f:
            husk_data = f.read()
        
        # Parse husk and extract target node
        target_node = parse_husk(husk_data)
        
        # Compute build-root
        build_root = recompute_node(target_node, site_dir)
        
        # Print result
        sys.stdout.write(build_root.decode('ascii') + '\n')
        sys.exit(0)
    
    except Exception as e:
        sys.stderr.write(f"Error: {e}\n")
        sys.exit(1)


if __name__ == '__main__':
    main()
