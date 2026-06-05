"""CLI rendering contract — shared argparse help primitives.

Layer 7 leaf (beneath both main and surface) — exists to break the cycle.

These are shared rendering primitives, not dispatcher internals. They were
originally defined in main.py only because that's where argparse is wired,
but they're conceptually shared between main (which sets up parsers) and
surface (which renders help output).
"""

import argparse


# -- Argparse action types that take no value ----------------------------

_NO_VALUE_ACTIONS = (
    argparse._StoreTrueAction,
    argparse._StoreFalseAction,
    argparse._StoreConstAction,
    argparse._CountAction,
)


# -- Flag string formatter ------------------------------------------------

def _flag_str(action):
    """Build the left-column display string for an argparse action.

    Examples:
        -h, --help
        --json
        --site SITE
        --model {gpt-4,claude-3}
    """
    if not action.option_strings:
        return action.metavar or action.dest
    parts = sorted(action.option_strings, key=len)
    s = ", ".join(parts)
    if isinstance(action, _NO_VALUE_ACTIONS):
        return s
    if action.metavar:
        meta = action.metavar
    elif action.choices:
        meta = "{" + ",".join(str(c) for c in action.choices) + "}"
    else:
        meta = action.dest.upper()
    return f"{s} {meta}"


# -- Styled help action ---------------------------------------------------

class _StyledHelpAction(argparse.Action):
    """Custom -h/--help action that renders our branded subcommand help.

    Delegates to surface.emit_subcommand_help() for actual rendering.
    The import is deferred because contract is a leaf beneath surface.
    """

    def __init__(self, option_strings, dest=argparse.SUPPRESS,
                 default=argparse.SUPPRESS, help=None):
        super().__init__(option_strings=option_strings, dest=dest,
                         default=default, nargs=0, help=help)

    def __call__(self, parser, namespace, values, option_string=None):
        # Deferred import: contract (leaf) calls up to surface (its user)
        # This is the argparse action callback, not module initialization
        from husks.cli.surface import emit_subcommand_help
        print(emit_subcommand_help(parser))
        parser.exit()
