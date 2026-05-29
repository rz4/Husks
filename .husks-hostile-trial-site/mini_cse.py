def parse(data: bytes):
    if not isinstance(data, bytes):
        raise TypeError("Input must be bytes")
    
    result, pos = _parse_value(data, 0)
    
    if pos != len(data):
        raise ValueError(f"Trailing bytes after complete value at position {pos}")
    
    return result


def _parse_value(data: bytes, pos: int):
    if pos >= len(data):
        raise ValueError("Unexpected end of input")
    
    byte = data[pos]
    
    if byte == ord(b'('):
        return _parse_list(data, pos + 1)
    elif 48 <= byte <= 57:
        return _parse_atom(data, pos)
    else:
        raise ValueError(f"Invalid character at position {pos}: {chr(byte)}")


def _parse_atom(data: bytes, pos: int):
    length_start = pos
    
    while pos < len(data) and 48 <= data[pos] <= 57:
        pos += 1
    
    if pos == length_start:
        raise ValueError(f"Empty length prefix at position {length_start}")
    
    length_str = data[length_start:pos].decode('ascii')
    
    if len(length_str) > 1 and length_str[0] == '0':
        raise ValueError(f"Leading zero in length at position {length_start}")
    
    length = int(length_str)
    
    if pos >= len(data) or data[pos] != ord(b':'):
        raise ValueError(f"Expected ':' at position {pos}")
    
    pos += 1
    
    if pos + length > len(data):
        raise ValueError(f"Atom length {length} exceeds remaining data")
    
    atom_data = data[pos:pos + length]
    pos += length
    
    return atom_data, pos


def _parse_list(data: bytes, pos: int):
    elements = []
    
    while pos < len(data):
        if data[pos] == ord(b')'):
            return elements, pos + 1
        
        element, pos = _parse_value(data, pos)
        elements.append(element)
    
    raise ValueError("Unclosed list")
