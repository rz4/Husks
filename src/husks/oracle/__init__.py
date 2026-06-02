"""
oracle -- Nondeterministic substrate for Husks builds.

This package executes oracle recipes behind an interchangeable backend.
A backend produces files; the build checks only the residue (the bytes).
Model identity, token counts, cost, wall time, and tool-call traces are
provenance that never enters the Merkle DAG.

Layout
------
  backend.py     -- OracleBackend protocol, RealizedCost, registry, the
                    run_oracle dispatcher, and backend-agnostic
                    scaffolding (system prompt, site resolution).
  litellm.py     -- LiteLLMBackend.  Owns an OpenAI-shaped loop (kernel)
                    and reaches providers through litellm.  Full
                    power-user config surface (params, router, per_rule).
  claude_code.py -- ClaudeCodeBackend.  Delegates the loop to the Claude
                    Code Agent SDK; enforces allowlist, fuel, and sandbox
                    through a can_use_tool interceptor.
  kernel.py      -- Loop primitives used by the litellm backend.
  llm.py         -- litellm wrapper with usage tracking + param/router
                    pass-through.
  tools.py       -- Sandboxed filesystem tools for the litellm loop.

Boundary
--------
Backend selection and config live in the build store S
(S["oracle-backend"], S["oracle-config"]), never in the recipe.  The
seal is executor-blind: a husk built under one backend resumes under the
other without busting a single seal.
"""

from husks.oracle import backend as _backend
from husks.oracle.backend import (
    OracleBackend,
    RealizedCost,
    register,
    run_oracle,
)
from husks.oracle.litellm import LiteLLMBackend
from husks.oracle.claude_code import ClaudeCodeBackend

_backend.register(LiteLLMBackend())
_backend.register(ClaudeCodeBackend())


# -- Back-compat ----------------------------------------------------
# build.py historically called live_oracle(S, rule, recipe, outputs).
# run_oracle has the identical 4-arg contract, so alias it.

live_oracle = run_oracle


def set_oracle_model(model: str) -> None:
    """Deprecated shim: set the process-default litellm model.

    Prefer S["oracle-config"]["model"].  This only affects the litellm
    backend and only when the store carries no model.
    """
    from husks.oracle import kernel
    kernel.set_oracle_model(model)


__all__ = [
    "run_oracle",
    "live_oracle",
    "set_oracle_model",
    "register",
    "OracleBackend",
    "RealizedCost",
    "LiteLLMBackend",
    "ClaudeCodeBackend",
]
