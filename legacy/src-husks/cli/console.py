"""Centralized console output handling with color and quiet mode support.

C22, C23, C24: Unified console output that honors --quiet and --color flags.
"""

import sys
from typing import TextIO


class Console:
    """Console output manager supporting quiet mode and color control.

    C22: Routes all output through this object to honor --quiet
    C23, C24: Centralizes color handling to respect --color flag and TTY detection
    """

    def __init__(self, quiet: bool = False, color: str = "auto"):
        """Initialize console.

        Parameters
        ----------
        quiet : bool
            Suppress non-essential output
        color : str
            Color mode: "auto", "always", or "never"
        """
        self.quiet = quiet
        self._color_mode = color
        self._use_color = self._should_use_color()

    def _should_use_color(self) -> bool:
        """Determine if color should be used based on mode and TTY status.

        C24: Disable color when stdout is not a TTY under auto mode.
        """
        if self._color_mode == "never":
            return False
        if self._color_mode == "always":
            return True
        # auto mode: use color only if stdout is a TTY
        return sys.stdout.isatty()

    def strip_ansi(self, text: str) -> str:
        """Remove ANSI escape codes from text.

        C24: Strip ANSI codes when color is disabled.
        """
        if self._use_color:
            return text
        # Simple ANSI escape code removal (handles most common cases)
        import re
        ansi_escape = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')
        return ansi_escape.sub('', text)

    def print(self, *args, file: TextIO | None = None, essential: bool = False, **kwargs):
        """Print with quiet mode and color handling.

        Parameters
        ----------
        *args : Any
            Arguments to print
        file : TextIO, optional
            File to write to (default: stdout)
        essential : bool
            If True, print even in quiet mode (for errors, final results)
        **kwargs : Any
            Additional arguments passed to print()
        """
        if self.quiet and not essential:
            return

        if file is None:
            file = sys.stdout

        # Strip ANSI codes if color is disabled
        if not self._use_color and args:
            args = tuple(self.strip_ansi(str(arg)) for arg in args)

        print(*args, file=file, **kwargs)

    def error(self, *args, **kwargs):
        """Print to stderr (always essential, never suppressed by quiet)."""
        self.print(*args, file=sys.stderr, essential=True, **kwargs)

    def status(self, *args, **kwargs):
        """Print status message (non-essential, suppressed in quiet mode)."""
        self.print(*args, essential=False, **kwargs)


# Global console instance (set by main())
_console: Console | None = None


def get_console() -> Console:
    """Get the global console instance."""
    if _console is None:
        # Default console if not initialized
        return Console()
    return _console


def set_console(console: Console):
    """Set the global console instance."""
    global _console
    _console = console
