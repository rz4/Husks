"""
locke.py -- Husks language: Parser + Design IR.

Locke is the canonical intermediate representation for Husks builds.
Provides:
  - Surface language parser (tokenize, parse)
  - Design validation (check, check_categorized)
  - Design compilation (compile_design)
  - Design execution (run)
  - I/O (from_json, from_locke, to_json)

Surface syntax: Square-Lisp-Python with minimal operators.
Zero external parser dependencies (stdlib only).

Two operators
-------------

``:=``  realization — value on the left, label on the right.
        Declares something concrete and deterministic.

``:-``  composition — name on the left, kind + block on the right.
        Defines a sub-rule that connects into the build tree.

Inside a rule block:

    ``value := label``   deterministic declaration (inputs, outputs, ...)
    ``name :- kind [...]``  nested sub-rule (child in the DAG)

At the top level:

    ``"core-bootstrap" := public``   build name
    ``20 := fuel``                   fuel budget
    ``rule := action [...]``         target rule (first := rule wins)

Type semantics for ``:=`` values:

    atom (bare word)    file reference — resolved at parse time
    string (quoted)     inline data — embedded in the design
    int / float         numeric literal
    cell (brackets)     list of values

Grammar
-------
::

    program    = (comment | top_decl | top_rule | top_bind)*

    top_decl   = expr ':=' DECL_KW
    top_rule   = IDENT (':=' | ':-') RULE_KW block
    top_bind   = IDENT ':-' expr

    DECL_KW    = 'public' | 'fuel' | 'site-inputs' | 'cost-tolerance'
    RULE_KW    = 'oracle' | 'action' | 'trial' | 'commit' | 'halt' | 'cond' | 'let'

    block      = '[' block_item* ']'
    block_item = expr ':=' IDENT           # realization (value := label)
               | IDENT ':-' RULE_KW block  # sub-rule
               | ':-' 'let' block          # anonymous let scope
               | IDENT                     # bare reference (cond predicate)

    cell       = '[' expr* ']'
    expr       = cell | atom
    atom       = STRING | FLOAT | INT | BAREWORD
    STRING     = '"' [^"]* '"'
    INT        = [0-9]+
    FLOAT      = [0-9]+ '.' [0-9]+
    BAREWORD   = [A-Za-z0-9_./-]+
    comment    = '#' [^\\n]*
"""

from __future__ import annotations

# ── Public API: Parser ───────────────────────────────────────────

from ._tokenizer import _TT, Token, tokenize
from ._parser import DeclNode, RuleNode, BindNode, LetNode, parse
from ._resolver import resolve, from_file
from ._compiler import compile, compile_bytes

# ── Public API: Validation ───────────────────────────────────────

from ._validation import check, check_categorized

# ── Public API: Pretty-print ─────────────────────────────────────

from ._show import show

# ── Public API: Execution ────────────────────────────────────────

from ._executor import compile_design, run

# ── Public API: I/O ──────────────────────────────────────────────

from ._io import from_json, from_locke, to_json, normalize_site_inputs

# ── Re-export for backward compatibility ─────────────────────────

# Re-export compile_design as "compile" for the executor
# (Note: there's also _compiler.compile which is the parse pipeline)
compile = compile_design

__all__ = [
    # Tokenizer
    "_TT",
    "Token",
    "tokenize",
    # Parser
    "DeclNode",
    "RuleNode",
    "BindNode",
    "LetNode",
    "parse",
    # Resolver
    "resolve",
    "from_file",
    # Compiler
    "compile",
    "compile_bytes",
    # Validation
    "check",
    "check_categorized",
    # Show
    "show",
    # Executor
    "compile_design",
    "run",
    # I/O
    "from_json",
    "from_locke",
    "to_json",
    "normalize_site_inputs",
]
