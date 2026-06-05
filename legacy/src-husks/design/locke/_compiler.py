"""
_compiler.py -- High-level compilation pipeline.

Provides compile and compile_bytes functions.
"""

from __future__ import annotations

from typing import Any


def compile(source: str, base_dir: str = ".") -> Any:
    """Full pipeline: parse -> resolve -> elaborate -> CseValue."""
    from husks.design.transport import elaborate
    from ._tokenizer import tokenize
    from ._parser import parse
    from ._resolver import resolve

    tokens = tokenize(source)
    ast = parse(tokens)
    design = resolve(ast, base_dir)
    return elaborate(design)


def compile_bytes(source: str, base_dir: str = ".") -> bytes:
    """Full pipeline: parse -> resolve -> elaborate -> encode -> bytes."""
    from husks.core import encode

    return encode(compile(source, base_dir))
