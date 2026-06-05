"""
design -- Build specification layer for Husks.

This package contains everything between human/agent intent and the
build runtime. Three sub-modules:

  locke.py       -- The design intermediate representation and Locke
                    surface language: parser, validator, compiler,
                    executor. The canonical IR for Husks builds.

  transport.py   -- Bijective CSE <-> JSON mapping and flat-design
                    elaboration. Translates between the permanent
                    wire format (CSE byte trees) and the ergonomic
                    authoring format (JSON dicts).

  convergence.py -- Post-execution analysis of rule history. Reads
                    JSONL history logs from the site directory and
                    classifies rule behavior (stable, converging,
                    prompt-loading, volatile).
"""

from husks.design.locke import (
    check, check_categorized, show, compile_design as compile, run,
    from_json, from_locke, to_json
)
from husks.design.convergence import (
    convergence_summary, declared_vs_traced
)

__all__ = [
    "check", "check_categorized", "show", "compile", "run",
    "from_json", "from_locke", "to_json",
    "convergence_summary", "declared_vs_traced",
]
