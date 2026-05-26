"""
designs -- Build specification layer for Husks.

This package contains everything between human/agent intent and the
build runtime.  Three sub-modules:

  ir.py          -- The design intermediate representation.  JSON-native
                    build graph: static validation (check), pretty-print
                    (show), compilation to runtime nodes (compile), and
                    end-to-end execution (run).

  transport.py   -- Bijective CSE <-> JSON mapping and flat-design
                    elaboration.  Translates between the permanent
                    wire format (CSE byte trees) and the ergonomic
                    authoring format (JSON dicts).

  convergence.py -- Post-execution analysis of rule history.  Reads
                    JSONL history logs from the site directory and
                    classifies rule behavior (stable, converging,
                    prompt-loading, volatile).
"""

from husks.designs.ir import check, show, compile, run, from_json, to_json
from husks.designs.convergence import convergence_summary, declared_vs_traced

try:
    from husks.designs.hy import HY_AVAILABLE, hy_build_backend, hy_kernel_backend
except Exception:
    HY_AVAILABLE = False
    hy_build_backend = None
    hy_kernel_backend = None

__all__ = [
    "check",
    "show",
    "compile",
    "run",
    "from_json",
    "to_json",
    "convergence_summary",
    "declared_vs_traced",
    "HY_AVAILABLE",
    "hy_build_backend",
    "hy_kernel_backend",
]
