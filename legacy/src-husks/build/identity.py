"""Recipe identity and seals."""

from __future__ import annotations

import hashlib
import inspect
from typing import Callable, TYPE_CHECKING

from husks.core import NIL, CseValue
from husks.build.policies import verdict_identity

if TYPE_CHECKING:
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


# Verdict policies moved to build.policies (L1) to break the cycle.


# ── Action arg types ─────────────────────────────────────────────

_ACTION_ARG_TYPES = (str, int, float, bool, bytes, type(None))


# ── Recipe → CSE ──────────────────────────────────────────────────

def recipe_to_cse(recipe: Recipe) -> CseValue:
    """Convert an engine recipe dict to a CSE-serializable form (v2).

    The CSE form is what participates in the seal preimage.  It must
    be deterministic: the same recipe dict always produces the same
    CSE value.

    Recipe identity scheme v2 (independent of CSE wire version):
      - Shell actions: (action <cmd>) — command string is the identity.
      - Callable actions: (action <behavior-digest>) — source/bytecode
        digest is the identity. (v1 used function __qualname__)
      - Oracle/trial: unchanged from v1.

    See core.py for version terminology clarification.
    """
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
        policy_name = verdict_identity(verdict)
        return [b"trial", policy_name] + [recipe_to_cse(b) for b in recipe["branches"]]
    return NIL
