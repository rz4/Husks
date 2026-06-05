"""
_tokenizer.py -- Lexical analysis for Locke.

Provides token types, Token class, and tokenize function.
"""

from __future__ import annotations


# ── Token types ──────────────────────────────────────────────────

class _TT:
    IDENT    = "IDENT"
    BIND     = "BIND"      # :-
    DECL     = "DECL"      # :=  (realization)
    LBRACKET = "LBRACKET"  # [
    RBRACKET = "RBRACKET"  # ]
    STRING   = "STRING"
    INT      = "INT"
    FLOAT    = "FLOAT"
    BAREWORD = "BAREWORD"
    EOF      = "EOF"


class Token:
    __slots__ = ("type", "value", "line", "col")

    def __init__(self, type: str, value: str, line: int = 0, col: int = 0):
        self.type = type
        self.value = value
        self.line = line
        self.col = col

    def __repr__(self) -> str:
        return f"Token({self.type}, {self.value!r}, L{self.line})"


# ── Keywords ─────────────────────────────────────────────────────

_RULE_KEYWORDS = frozenset({
    "oracle", "action", "trial", "commit", "halt", "cond", "let",
})

_DECL_KEYWORDS = frozenset({
    "public", "fuel", "site-inputs", "cost-tolerance",
    # Surface aliases (canonical Locke syntax)
    "design", "tolerance", "site",
})

# Labels allowed on the right side of := inside a rule block
_BLOCK_LABELS = frozenset({
    "inputs", "outputs", "free", "exact",
    "prompt", "tools", "fuel", "run",
    "value", "reason",
    "predicate", "then", "else",
})


# ── Lexer ────────────────────────────────────────────────────────

def _is_bareword_char(c: str) -> bool:
    return c.isalnum() or c in "_./-"


def tokenize(source: str) -> list[Token]:
    """Lex *source* into a flat list of tokens."""
    tokens: list[Token] = []
    i = 0
    line = 1
    col = 1
    n = len(source)

    while i < n:
        c = source[i]

        # newline
        if c == "\n":
            i += 1
            line += 1
            col = 1
            continue

        # whitespace
        if c in " \t\r":
            i += 1
            col += 1
            continue

        # comment
        if c == "#":
            while i < n and source[i] != "\n":
                i += 1
            continue

        # := (realization) — must check before :-
        if c == ":" and i + 1 < n and source[i + 1] == "=":
            tokens.append(Token(_TT.DECL, ":=", line, col))
            i += 2
            col += 2
            continue

        # :- (composition)
        if c == ":" and i + 1 < n and source[i + 1] == "-":
            tokens.append(Token(_TT.BIND, ":-", line, col))
            i += 2
            col += 2
            continue

        # brackets
        if c == "[":
            tokens.append(Token(_TT.LBRACKET, "[", line, col))
            i += 1
            col += 1
            continue
        if c == "]":
            tokens.append(Token(_TT.RBRACKET, "]", line, col))
            i += 1
            col += 1
            continue

        # string (triple-quoted or single-quoted)
        if c == '"':
            start_line, start_col = line, col
            # Check for triple-quoted string
            if i + 2 < n and source[i + 1] == '"' and source[i + 2] == '"':
                i += 3
                col += 3
                buf: list[str] = []
                while i < n:
                    if source[i] == '"' and i + 2 < n and source[i + 1] == '"' and source[i + 2] == '"':
                        i += 3
                        col += 3
                        break
                    if source[i] == "\n":
                        line += 1
                        col = 0
                    buf.append(source[i])
                    i += 1
                    col += 1
                else:
                    raise SyntaxError(
                        f"unterminated triple-quoted string starting at line {start_line}, col {start_col}"
                    )
                tokens.append(Token(_TT.STRING, "".join(buf), start_line, start_col))
                continue
            # Single-quoted string
            i += 1
            col += 1
            buf = []
            while i < n and source[i] != '"':
                if source[i] == "\n":
                    line += 1
                    col = 0
                buf.append(source[i])
                i += 1
                col += 1
            if i >= n:
                raise SyntaxError(
                    f"unterminated string starting at line {start_line}, col {start_col}"
                )
            i += 1  # closing quote
            col += 1
            tokens.append(Token(_TT.STRING, "".join(buf), start_line, start_col))
            continue

        # number or bareword
        if c.isdigit() or _is_bareword_char(c):
            start_col = col
            buf = []
            while i < n and _is_bareword_char(source[i]):
                buf.append(source[i])
                i += 1
                col += 1
            word = "".join(buf)
            if _looks_like_float(word):
                tokens.append(Token(_TT.FLOAT, word, line, start_col))
            elif _looks_like_int(word):
                tokens.append(Token(_TT.INT, word, line, start_col))
            else:
                tokens.append(Token(_TT.BAREWORD, word, line, start_col))
            continue

        raise SyntaxError(f"unexpected character {c!r} at line {line}, col {col}")

    tokens.append(Token(_TT.EOF, "", line, col))
    return tokens


def _looks_like_int(word: str) -> bool:
    return word.isdigit()


def _looks_like_float(word: str) -> bool:
    parts = word.split(".")
    return len(parts) == 2 and parts[0].isdigit() and parts[1].isdigit()
