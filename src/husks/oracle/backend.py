"""
backend.py -- Oracle backend contract and registry for Husks.

An oracle backend produces the declared outputs of an oracle rule into
the build site, under a tool allowlist and a fuel bound, and reports
realized cost.  Backends are interchangeable *by construction*: the seal
keys on the recipe (prompt, tools, fuel) and the residue (the bytes),
never on which backend answered.  See oracle/__init__.py "Boundary".

Modules implementing OracleBackend
----------------------------------
  litellm.py      -- LiteLLM agent loop.  Owns the loop; enforces the
                     allowlist and fuel in-process because it dispatches
                     every tool call itself.
  claude_code.py  -- Claude Code Agent SDK.  Delegates the loop to the
                     SDK; enforces the allowlist and fuel through a
                     can_use_tool interceptor at the tool boundary.

Invariant (load-bearing)
------------------------
Backend selection and backend configuration live in the build store S,
never in the recipe.  The recipe form hashed into the seal is
``(oracle name prompt tools fuel)`` (see core.recipe_digest).  No model
id, provider, sampling param, router, or backend name may enter it.
Changing the backend or its config is *provenance*, not *identity*: it
does not re-fire sealed rules.  Verified against core.py: the oracle
recipe form is executor-free.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol, TypedDict, runtime_checkable


# -- Realized cost --------------------------------------------------

class RealizedCost(TypedDict):
    """What a backend reports after producing an oracle's outputs.

    Provenance only.  None of these fields enter the Merkle DAG.  At
    runtime this is a plain dict, so build.py consumes it unchanged.
    """
    tokens_in: int
    tokens_out: int
    cost_usd: float
    fuel_steps: int


# -- Backend protocol -----------------------------------------------

@runtime_checkable
class OracleBackend(Protocol):
    """Produce an oracle rule's outputs, bounded by tools and fuel.

    A backend MUST:
      1. Confine all file effects to the build site (and any declared
         readonly roots).
      2. Permit only the tools named in ``recipe["tools"]``.
      3. Stop at ``recipe["fuel"]`` steps.  A step is one tool call.
      4. Raise on any non-clean termination (fuel exhausted, error,
         interrupt, or text-without-stop).  Raising prevents the build
         from sealing partial output.  Output *correctness* is NOT the
         backend's concern: a downstream action gate checks the residue.
      5. Return a RealizedCost.

    A backend MUST NOT:
      - Read backend configuration from the recipe.
      - Validate its own output.  No oracle grades itself.
    """

    name: str

    def run(
        self,
        S: dict[str, Any],
        rule_name: str,
        recipe: dict[str, Any],
        outputs: list[str],
        config: dict[str, Any],
    ) -> RealizedCost:
        ...


# -- Registry -------------------------------------------------------

REGISTRY: dict[str, OracleBackend] = {}


def register(backend: OracleBackend) -> None:
    """Register a backend under its ``name``.  Idempotent."""
    REGISTRY[backend.name] = backend


def get_backend(name: str) -> OracleBackend:
    try:
        return REGISTRY[name]
    except KeyError:
        known = ", ".join(sorted(REGISTRY)) or "(none registered)"
        raise KeyError(
            f"unknown oracle backend {name!r}; registered: {known}"
        ) from None


# -- Shared scaffolding ---------------------------------------------
# Backend-agnostic.  Both backends use these so the oracle's standing
# orders and the success contract are identical regardless of who
# answers.  Identical orders are what make the seal backend-blind.

DEFAULT_TOOLS: list[str] = ["read-file", "write-file", "list-dir", "tree"]


def build_system_prompt(site: str, outputs: list[str]) -> str:
    """The oracle's standing orders: where it is, what it must leave."""
    output_lines = "\n".join(f"  - {o}" for o in outputs)
    return (
        "You are an oracle inside a build system.\n"
        f"Site directory: {site}\n"
        "File paths are relative to the site directory.\n"
        "You must produce these outputs:\n"
        f"{output_lines}\n\n"
        "Use the available tools to read inputs and write outputs. "
        "When finished, stop."
    )


def site_of(S: dict[str, Any]) -> Path:
    """Resolve the build site (the stage if a build is staging)."""
    return Path(S.get("stage", S["site"])).resolve()


def readonly_roots_of(S: dict[str, Any]) -> set[Path]:
    return {Path(p).resolve() for p in S.get("readonly-dirs", [])}


# -- Dispatcher -----------------------------------------------------

def run_oracle(
    S: dict[str, Any],
    rule_name: str,
    recipe: dict[str, Any],
    outputs: list[str],
) -> RealizedCost:
    """Build-facing entry point.  Replaces the hardcoded live_oracle.

    Selects the backend named in ``S["oracle-backend"]`` (default
    ``"litellm"``) and hands it the config in ``S["oracle-config"]``.
    The recipe passes through untouched and is never inspected for
    backend settings.

    Parameters
    ----------
    S : dict
        The build store.  Reads "site"/"stage", "readonly-dirs",
        "oracle-backend", "oracle-config".
    rule_name : str
        Name of the oracle rule being evaluated.
    recipe : dict
        The oracle recipe: prompt, tools, fuel.  Digest-relevant; not
        mutated.
    outputs : list of str
        Declared output filenames the oracle must produce.
    """
    name = S.get("oracle-backend-name", "litellm")
    config = dict(S.get("oracle-config", {}))
    return get_backend(name).run(S, rule_name, recipe, outputs, config)

