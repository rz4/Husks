def parse(data: bytes):
    """Parse a Canonical S-expression from bytes."""
    if not isinstance(data, bytes):
        raise ValueError("Input must be bytes")
    
    result, pos = _parse_value(data, 0)
    
    # Reject trailing bytes
    if pos != len(data):
        raise ValueError("Trailing bytes after complete value")
    
    return result


def _parse_value(data: bytes, pos: int):
    """Parse a single value (atom or list) starting at position pos.
    Returns (value, new_position)."""
    
    if pos >= len(data):
        raise ValueError("Unexpected end of input")
    
    # Check if it's a list
    if data[pos:pos+1] == b'(':
        return _parse_list(data, pos + 1)
    
    # Otherwise it's an atom
    return _parse_atom(data, pos)


def _parse_atom(data: bytes, pos: int):
    """Parse an atom (length:payload) starting at position pos.
    Returns (bytes_value, new_position)."""
    
    if pos >= len(data):
        raise ValueError("Unexpected end of input")
    
    # Parse length
    length_start = pos
    while pos < len(data) and data[pos:pos+1].isdigit():
        pos += 1
    
    if pos == length_start:
        raise ValueError("Empty length prefix")
    
    length_str = data[length_start:pos].decode('ascii')
    
    # Check for leading zeroes (invalid except for "0")
    if len(length_str) > 1 and length_str[0] == '0':
        raise ValueError("Leading zeroes in length")
    
    length = int(length_str)
    
    # Expect colon
    if pos >= len(data) or data[pos:pos+1] != b':':
        raise ValueError("Expected colon after length")
    
    pos += 1
    
    # Extract payload
    if pos + length > len(data):
        raise ValueError("Payload too short")
    
    payload = data[pos:pos+length]
    pos += length
    
    return payload, pos


def _parse_list(data: bytes, pos: int):
    """Parse a list starting after '(' at position pos.
    Returns (list_value, new_position)."""
    
    result = []
    
    while pos < len(data):
        if data[pos:pos+1] == b')':
            return result, pos + 1
        
        value, pos = _parse_value(data, pos)
        result.append(value)
    
    raise ValueError("Unclosed list")
