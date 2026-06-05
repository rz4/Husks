"""Architecture enforcement — import graph analysis and cycle detection.

This package contains zero husks.* imports (only stdlib) so it cannot
violate the layering contract it enforces.
"""

from husks._arch.check import check_architecture, parse_import_edges

__all__ = ["check_architecture", "parse_import_edges"]
