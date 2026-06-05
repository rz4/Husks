"""Verdict policies and verdict identity (L1).

RECONSTRUCTED MODULE — was wired into the package (build/__init__.py,
eval.py, identity.py) and marked complete in docs/phase-1-complete.md,
but the file itself was never committed, leaving the package unimportable.

Layer 1 (pure, content-addressing). Holds:
  - first_valid(results)      default verdict policy (moved from eval.py)
  - VERDICT_POLICIES          registry of built-in verdict policies
  - DEFAULT_VERDICT           the default policy object
  - verdict_identity(verdict) canonical identity bytes for a verdict policy

Reconstructed to the contract pinned by:
  - docs/phase-1-complete.md
  - tests/test_SOLID_15_triage_regressions.py  (cse[1] == b"first-valid")
  - usage in build/eval.py::eval_trial and build/identity.py::recipe_to_cse
"""

from __future__ import annotations

from typing import Any, Callable

# Canonical CSE name for the default verdict policy. This byte string
# participates in the trial recipe seal preimage and MUST remain stable.
_FIRST_VALID_NAME = b"first-valid"


def first_valid(results: list[dict[str, Any]]) -> dict[str, Any]:
    """Default verdict: pick the first branch that ran without error.

    Pure: list[dict] -> dict. A branch result carries an ``"error"`` key
    only if the branch raised. The first error-free result wins; if every
    branch errored, the first result is returned so the caller can surface
    the failure rather than crash on an empty selection.

    Returns the winning result dict directly (legacy protocol). eval_trial
    also accepts the ``{"winner": ..., "scores": ...}`` dict protocol from
    other policies.
    """
    for r in results:
        if "error" not in r:
            return r
    return results[0]


# Registry of built-in, name-addressable verdict policies. A trial recipe
# may set ``verdict`` to one of these names (resolved in eval_trial). Both
# the canonical hyphen form and the Python underscore form resolve to the
# same function.
VERDICT_POLICIES: dict[str, Callable[[list[dict[str, Any]]], Any]] = {
    "first-valid": first_valid,
    "first_valid": first_valid,
}

# The default policy object. Compared by identity in eval_trial via
# ``verdict_fn is DEFAULT_VERDICT``; kept as the same object as first_valid.
DEFAULT_VERDICT = first_valid


def verdict_identity(verdict: Any) -> bytes:
    """Canonical identity bytes for a trial's verdict policy.

    This value sits in the trial recipe's CSE form: ``[b"trial",
    verdict_identity(verdict), *branches]``. It must be deterministic and
    must distinguish different policies so that changing the verdict
    changes the recipe digest.

      - None / first_valid / DEFAULT_VERDICT -> b"first-valid"
      - a registered policy name (str)       -> canonical name bytes
      - any other string                     -> that string, encoded
      - a custom callable                    -> behavior digest bytes
    """
    if verdict is None or verdict is first_valid or verdict is DEFAULT_VERDICT:
        return _FIRST_VALID_NAME

    if isinstance(verdict, str):
        if verdict in VERDICT_POLICIES and VERDICT_POLICIES[verdict] is first_valid:
            return _FIRST_VALID_NAME
        return verdict.encode()

    # Custom callable: identity is its behavior digest. Deferred import of
    # the L1 sibling (sanctioned in layers.toml [allow_deferred]) to avoid a
    # module-load circular import between policies and identity.
    from husks.build.identity import _fn_behavior_digest

    return _fn_behavior_digest(verdict).encode()
