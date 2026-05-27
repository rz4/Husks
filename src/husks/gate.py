"""
gate.py — Thin entry point for ``husks-gate`` console script.

Delegates to ``husks_conformance.gate.main()`` if the conformance package
is installed, otherwise errors with an install hint.
"""

import sys


def main(argv=None):
    """Entry point for the ``husks-gate`` console script."""
    try:
        from husks_conformance.gate import main as _gate_main
    except ImportError:
        print(
            "error: husks-gate requires the husks-conformance package.\n"
            "Install it with:\n"
            "  pip install -e spec/conformance_pkg  (from a source checkout)\n"
            "Or install the conformance package separately.",
            file=sys.stderr,
        )
        sys.exit(1)
    _gate_main(argv)


if __name__ == "__main__":
    main()
