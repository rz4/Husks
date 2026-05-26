"""
designs.hy -- Hy interop bridge.

Provides lazy, safe access to the original Hy-authored build and kernel
modules from ``husks``.  Activates Hy's import hook on demand so callers
never need a bare ``import hy`` scattered through their code.
"""

import importlib
import sys

__all__ = [
    "HY_AVAILABLE",
    "ensure_hy",
    "load_hy_module",
    "hy_build_backend",
    "hy_kernel_backend",
]

_HY_IMPORT_ERROR = "Hy is not installed. Install with: pip install husks[hy]"

# -- Availability flag (set once at import time) --

try:
    importlib.import_module("hy")
    HY_AVAILABLE: bool = True
except ImportError:
    HY_AVAILABLE: bool = False


# -- Hook activation --

def ensure_hy() -> bool:
    """Activate Hy's import hook if not already on ``sys.meta_path``.

    Returns ``True`` when Hy is available (hook is active), ``False``
    otherwise.  Safe to call repeatedly.
    """
    if not HY_AVAILABLE:
        return False

    # Hy registers its finder on sys.meta_path at import time.
    # Check whether it is already present before importing again.
    for finder in sys.meta_path:
        cls_name = type(finder).__name__
        if "hy" in cls_name.lower() or type(finder).__module__.startswith("hy"):
            return True

    # Not yet registered -- importing hy installs it.
    importlib.import_module("hy")
    return True


# -- Generic module loader --

def load_hy_module(dotted_name: str):
    """Import a ``.hy`` module by its dotted Python path.

    Calls :func:`ensure_hy` first so the Hy import hook is active.
    Raises ``ImportError`` if Hy is not installed.
    """
    if not ensure_hy():
        raise ImportError(_HY_IMPORT_ERROR)
    return importlib.import_module(dotted_name)


# -- Backend accessors (lazy) --

_BUILD_API_NAMES = (
    "build", "rule", "action", "oracle", "trial",
    "site_path", "read_text", "write_text", "ensure_dir",
)

_KERNEL_API_NAMES = (
    "live_oracle", "set_oracle_model",
)


def hy_build_backend() -> dict:
    """Return the Hy build API as a dict of callables.

    Keys: ``build``, ``rule``, ``action``, ``oracle``, ``trial``,
    ``site_path``, ``read_text``, ``write_text``, ``ensure_dir``.
    """
    mod = load_hy_module("husks.build")
    return {name: getattr(mod, name) for name in _BUILD_API_NAMES}


def hy_kernel_backend() -> dict:
    """Return the Hy kernel API as a dict of callables.

    Keys: ``live_oracle``, ``set_oracle_model``.
    """
    mod = load_hy_module("husks.kernel")
    return {name: getattr(mod, name) for name in _KERNEL_API_NAMES}
