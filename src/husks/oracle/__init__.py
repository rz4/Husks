"""
oracle -- Nondeterministic substrate for Husks builds.

This package contains everything needed to execute oracle recipes:
the LLM client, the agentic kernel, and the sandboxed tool registry.

Modules
-------
  llm.py     -- LiteLLM wrapper with cumulative usage tracking.
                Single-shot and multi-turn calls, response metadata
                extraction.

  kernel.py  -- Agentic loop: parse LLM responses into actions,
                dispatch tool calls, recurse until stop or fuel
                exhaustion.  Adapts the agent to the build's oracle
                backend signature via live_oracle().

  tools.py   -- Filesystem tools (read-file, write-file, list-dir,
                tree) with site-root sandboxing.  Auto-generates
                OpenAI function-calling schemas from decorated
                Python functions.

Boundary
--------
Nothing in this package participates in seals or verification.
The oracle is opaque to the build system: it produces files, and
the build checks only the residue (the bytes).  Model identity,
token counts, cost, wall time, and tool call traces are provenance
metadata that never enters the Merkle DAG.
"""

from husks.oracle.kernel import live_oracle, set_oracle_model

__all__ = ["live_oracle", "set_oracle_model"]
