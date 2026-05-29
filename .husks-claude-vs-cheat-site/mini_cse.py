def parse(data: bytes):
    """Parse a Canonical S-expression from bytes."""
    if not isinstance(data, bytes):
        raise TypeError("Input must be bytes")
    
    result, pos = _parse_value(data, 0)
    
    # Reject trailing bytes after one complete value
    if pos != len(data):
        raise ValueError(f"Trailing bytes after complete value at position {pos}")
    
    return result


def _parse_value(data: bytes, pos: int):
    """Parse a single CSE value. Returns (value, new_position)."""
    if pos >= len(data):
        raise ValueError("Unexpected end of input")
    
    # Check for list
    if data[pos:pos+1] == b'(':
        return _parse_list(data, pos + 1)
    
    # Otherwise, parse atom
    return _parse_atom(data, pos)


def _parse_atom(data: bytes, pos: int):
    """Parse an atom (length-prefixed bytes). Returns (bytes_value, new_position)."""
    if pos >= len(data):
        raise ValueError("Unexpected end of input while parsing atom")
    
    # Find the colon separator
    colon_pos = -1
    for i in range(pos, len(data)):
        if data[i:i+1] == b':':
            colon_pos = i
            break
    
    if colon_pos == -1:
        raise ValueError("Missing colon in atom")
    
    length_str = data[pos:colon_pos]
    
    # Length prefix must contain only digits
    if not length_str:
        raise ValueError("Empty length prefix")
    
    if not all(48 <= b <= 57 for b in length_str):  # 48-57 are '0'-'9'
        raise ValueError(f"Invalid length prefix: {length_str!r}")
    
    # Check for leading zeroes (invalid except for length 0)
    if len(length_str) > 1 and length_str[0:1] == b'0':
        raise ValueError("Leading zeroes in length prefix")
    
    try:
        atom_length = int(length_str)
    except ValueError:
        raise ValueError(f"Invalid length prefix: {length_str!r}")
    
    # Extract atom payload
    payload_start = colon_pos + 1
    payload_end = payload_start + atom_length
    
    if payload_end > len(data):
        raise ValueError(f"Atom length {atom_length} exceeds remaining data")
    
    atom_payload = data[payload_start:payload_end]
    
    # Verify payload length matches prefix exactly
    if len(atom_payload) != atom_length:
        raise ValueError(f"Atom payload length mismatch")
    
    return atom_payload, payload_end


def _parse_list(data: bytes, pos: int):
    """Parse a list starting after the opening paren. Returns (list, new_position)."""
    result = []
    
    while pos < len(data):
        # Check for closing paren
        if data[pos:pos+1] == b')':
            return result, pos + 1
        
        # Parse next value in the list
        value, pos = _parse_value(data, pos)
        result.append(value)
    
    raise ValueError("Unclosed list - missing closing paren")
