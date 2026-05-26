"""
utils -- Observation layer for Husks builds.

This package provides build tracing (structured events) and console
rendering (ANSI output).  The two concerns are cleanly separated:

  events.py   -- BuildTrace class.  Accumulates timestamped event dicts
                 in a JSONL stream.  Pure data, no I/O.  Supports a
                 listener protocol so renderers can subscribe.

  console.py  -- Console class.  Implements the TraceListener protocol.
                 Formats events as ANSI terminal output.  Can be omitted
                 for headless execution.

Usage
-----
Import the module-level ``trace`` instance for default behavior
(events + console rendering wired together)::

    from husks.utils import trace

    trace.build_start("my-build", fuel=10, site="/tmp/site")
    ...
    trace.build_end("committed", fuel_left=7, fuel_total=10)

For headless/test execution, create a bare BuildTrace without the
console listener::

    from husks.utils.events import BuildTrace
    t = BuildTrace()
    # no console output, events still recorded

Interface with husks
-------------------------
Consumed by:

  build.py         -- uses ``trace`` for build event emission.
  oracle/kernel.py -- uses ``trace`` for tool call/result events.
  cli.py           -- may access ``trace.to_jsonl()`` for export.
"""

from husks.utils.events import BuildTrace, TraceListener
from husks.utils.console import Console

# Module-level default trace with console rendering.
trace: BuildTrace = BuildTrace()
trace.add_listener(Console())


def reset() -> None:
    """Reset the default trace and re-attach the console listener."""
    global trace
    trace = BuildTrace()
    trace.add_listener(Console())


__all__ = [
    "BuildTrace",
    "TraceListener",
    "Console",
    "trace",
    "reset",
]
