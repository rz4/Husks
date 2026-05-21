"""Husks — fuel-bounded build calculus over an artifact store."""

from husks.tools import tool, schemas, dispatch  # noqa: F401
from husks.plan import check, show, compile, run, from_json, to_json  # noqa: F401

# Hy imports must happen after hy is available on sys.path
def _load_build():
    import hy  # noqa: F401
    from husks.build import (build, rule, action, oracle, trial,  # noqa: F401
                             site_path, read_text, write_text, ensure_dir)
    return build, rule, action, oracle, trial, site_path, read_text, write_text, ensure_dir

try:
    build, rule, action, oracle, trial, site_path, read_text, write_text, ensure_dir = _load_build()
    from husks.kernel import live_oracle, set_oracle_model  # noqa: F401
except ImportError:
    pass
