"""
Backward compatibility shim for CLI commands.

This module preserves import paths for code that imports from husks.cli.commands
instead of husks.cli.cmd. Deprecated - use husks.cli.cmd directly.
"""

import warnings

# Emit deprecation warning on import
warnings.warn(
    "husks.cli.commands is deprecated. Use husks.cli.cmd instead. "
    "Import from husks.cli.cmd: _cmd_check, _cmd_run, _cmd_status, etc.",
    DeprecationWarning,
    stacklevel=2
)

# Re-export all command functions from the new location
from husks.cli.cmd import (
    _cmd_check as cmd_check,
    _cmd_run as cmd_run,
    _cmd_run_hy as cmd_run_hy,
    _cmd_status as cmd_status,
    _cmd_explain as cmd_explain,
    _cmd_history as cmd_history,
    _cmd_doctor as cmd_doctor,
    _cmd_compare as cmd_compare,
    _cmd_compare_runs as cmd_compare_runs,
    _cmd_cache_export as cmd_cache_export,
    _cmd_cache_import as cmd_cache_import,
)

# Also export with underscore prefix for backward compat
from husks.cli.cmd import (
    _cmd_check,
    _cmd_run,
    _cmd_run_hy,
    _cmd_status,
    _cmd_explain,
    _cmd_history,
    _cmd_doctor,
    _cmd_compare,
    _cmd_compare_runs,
    _cmd_cache_export,
    _cmd_cache_import,
)

__all__ = [
    'cmd_check', '_cmd_check',
    'cmd_run', '_cmd_run',
    'cmd_run_hy', '_cmd_run_hy',
    'cmd_status', '_cmd_status',
    'cmd_explain', '_cmd_explain',
    'cmd_history', '_cmd_history',
    'cmd_doctor', '_cmd_doctor',
    'cmd_compare', '_cmd_compare',
    'cmd_compare_runs', '_cmd_compare_runs',
    'cmd_cache_export', '_cmd_cache_export',
    'cmd_cache_import', '_cmd_cache_import',
]
