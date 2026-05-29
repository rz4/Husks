def parse(data: bytes):
    parser = Parser(data)
    result = parser.parse_value()
    if parser.pos != len(data):
        raise ValueError("trailing bytes after value")
    return result


class Parser:
    def __init__(self, data: bytes):
        self.data = data
        self.pos = 0

    def parse_value(self):
        if self.pos >= len(self.data):
            raise ValueError("unexpected end of input")
        
        ch = self.data[self.pos]
        
        if ch == ord('('):
            return self.parse_list()
        else:
            return self.parse_atom()

    def parse_atom(self):
        length = self.parse_length()
        
        if self.pos >= len(self.data) or self.data[self.pos] != ord(':'):
            raise ValueError("expected colon after length")
        
        self.pos += 1
        
        if self.pos + length > len(self.data):
            raise ValueError("atom payload too short")
        
        payload = self.data[self.pos:self.pos + length]
        self.pos += length
        
        return payload

    def parse_length(self):
        if self.pos >= len(self.data):
            raise ValueError("unexpected end of input")
        
        start = self.pos
        
        while self.pos < len(self.data) and self.data[self.pos:self.pos + 1].isdigit():
            self.pos += 1
        
        if start == self.pos:
            raise ValueError("empty length prefix")
        
        length_str = self.data[start:self.pos].decode('ascii')
        
        if len(length_str) > 1 and length_str[0] == '0':
            raise ValueError("leading zero in length")
        
        return int(length_str)

    def parse_list(self):
        if self.data[self.pos] != ord('('):
            raise ValueError("expected '('")
        
        self.pos += 1
        result = []
        
        while self.pos < len(self.data) and self.data[self.pos] != ord(')'):
            result.append(self.parse_value())
        
        if self.pos >= len(self.data):
            raise ValueError("unclosed list")
        
        self.pos += 1
        
        return result
