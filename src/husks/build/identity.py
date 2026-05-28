"""Recipe identity and seals."""

from __future__ import annotations

import hashlib
import inspect
from typing import Callable

from husks.core import NIL, CseValue

from husks.build.site import Recipe


# ── Behavior digest ───────────────────────────────────────────────

def _fn_behavior_digest(fn: Callable) -> str:
    """Compute a behavior-based SHA-256 digest for a Python callable.

    Tries inspect.getsource first (deterministic across runs for
    statically defined functions).  Falls back to bytecode + constants
    if source is unavailable (e.g. for dynamically generated callables).
    """
    try:
        source = inspect.getsource(fn)
        return hashlib.sha256(source.encode()).hexdigest()
    except (OSError, TypeError):
        code = fn.__code__
        data = code.co_code + repr(code.co_consts).encode()
        return hashlib.sha256(data).hexdigest()


def _pred_identity(predicate: Callable) -> str:
    """Return the identity string for a cond predicate (v2).

    Built-in predicates carry _husks_pred_spec (the full spec string).
    Custom Python predicates use a behavior digest.
    """
    spec = getattr(predicate, "_husks_pred_spec", None)
    if spec is not None:
        return spec
    return _fn_behavior_digest(predicate)


# ── Verdict policies ──────────────────────────────────────────────

# Registry of named built-in verdict policies for trial recipes.
# The name is included in the recipe CSE form so that changing the
# verdict changes the recipe digest.
VERDICT_POLICIES: dict[str, Callable] = {}
# Populated after first_valid is defined (in eval.py).


# ── Action arg types ─────────────────────────────────────────────

_ACTION_ARG_TYPES = (str, int, float, bool, bytes, type(None))


# ── Recipe → CSE ──────────────────────────────────────────────────

def recipe_to_cse(recipe: Recipe) -> CseValue:
    """Convert an engine recipe dict to a CSE-serializable form (v2).

    The CSE form is what participates in the seal preimage.  It must
    be deterministic: the same recipe dict always produces the same
    CSE value.

    v2 recipe identity:
      - Shell actions: (action <cmd>) — command string is the identity.
      - Callable actions: (action <behavior-digest>) — source/bytecode
        digest is the identity.
      - Oracle/trial: unchanged from v1.
    """
    # Import here to avoid circular import; first_valid is defined in eval.py
    from husks.build.eval import first_valid

    if recipe is None:
        return NIL
    kind: str = recipe["type"]
    if kind == "action":
        fn = recipe["fn"]
        args = recipe.get("args", ())
        cmd: str = getattr(fn, "_husks_cmd", "")
        if cmd:
            # Shell action — command string is the sole identity
            return [b"action", cmd.encode()]
        else:
            # Callable action — behavior digest + args
            parts = [b"action", _fn_behavior_digest(fn).encode()]
            if args:
                parts.append(repr(args).encode())
            return parts
    if kind == "oracle":
        name = recipe.get("name")
        return [
            b"oracle",
            name.encode() if name else NIL,
            recipe.get("prompt", "").encode(),
            [t.encode() for t in sorted(recipe.get("tools", []))],
            str(recipe.get("fuel", 8)).encode(),
        ]
    if kind == "trial":
        verdict = recipe.get("verdict")
        if verdict is None or verdict is first_valid:
            policy_name = b"first-valid"
        elif isinstance(verdict, str) and verdict in VERDICT_POLICIES:
            policy_name = verdict.encode()
        else:
            policy_name = b"custom:" + _fn_behavior_digest(verdict).encode()
        return [b"trial", policy_name] + [recipe_to_cse(b) for b in recipe["branches"]]
    return NIL
