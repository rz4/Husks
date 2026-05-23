"""
test_core_isolation.py — Import guard: core imports nothing downward.

Asserts that husks.core:
  1. Imports no other husks.* modules
  2. Uses only stdlib packages
"""

import importlib
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

# Known stdlib top-level modules that core.py is allowed to use.
# This is intentionally conservative.
ALLOWED_STDLIB = {
    "hashlib", "os", "sys", "builtins", "_thread", "_io",
    "abc", "codecs", "collections", "contextlib", "copy",
    "errno", "fnmatch", "functools", "genericpath", "io",
    "itertools", "keyword", "linecache", "marshal", "math",
    "operator", "posixpath", "re", "reprlib", "stat",
    "string", "struct", "textwrap", "threading", "token",
    "tokenize", "traceback", "types", "typing", "warnings",
    "weakref", "_abc", "_codecs", "_collections", "_collections_abc",
    "_functools", "_heapq", "_operator", "_signal", "_sre",
    "_stat", "_string", "_struct", "_thread", "_warnings",
    "_weakref", "_weakrefset", "posix", "nt", "ntpath",
    "encodings", "sre_compile", "sre_constants", "sre_parse",
    "copyreg", "importlib", "_bootlocal", "_frozen_importlib",
    "_frozen_importlib_external", "atexit", "zipimport",
}


def test_no_husks_imports():
    """husks.core's source must not reference any other husks.* module."""
    import husks.core
    source_path = os.path.abspath(husks.core.__file__)

    with open(source_path, "r") as f:
        source = f.read()

    # Check that no import line references husks.*
    husks_imports = []
    for line in source.splitlines():
        line = line.strip()
        if line.startswith("#"):
            continue
        if line.startswith("import husks.") or line.startswith("from husks."):
            husks_imports.append(line)
        # Also catch "import husks" (the package itself)
        if line == "import husks":
            husks_imports.append(line)

    assert husks_imports == [], (
        f"husks.core references other husks modules:\n"
        + "\n".join(f"  {l}" for l in husks_imports)
    )


def test_stdlib_only():
    """husks.core must only import stdlib modules."""
    import husks.core
    source_path = os.path.abspath(husks.core.__file__)

    # Read source and extract import lines
    with open(source_path, "r") as f:
        source = f.read()

    imports = set()
    for line in source.splitlines():
        line = line.strip()
        if line.startswith("import "):
            # import foo, bar
            parts = line[len("import "):].split(",")
            for p in parts:
                mod = p.strip().split(" as ")[0].split(".")[0]
                imports.add(mod)
        elif line.startswith("from "):
            # from foo.bar import baz
            mod = line.split()[1].split(".")[0]
            imports.add(mod)

    # Only hashlib and os should be imported
    expected = {"hashlib", "os"}
    assert imports == expected, (
        f"husks.core imports: {imports}, expected only: {expected}"
    )
