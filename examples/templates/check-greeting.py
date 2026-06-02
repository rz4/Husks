#!/usr/bin/env python3
"""Validate that greeting.txt follows the spec."""
import sys
from pathlib import Path

greeting_file = Path("greeting.txt")
if not greeting_file.exists():
    print("ERROR: greeting.txt not found", file=sys.stderr)
    Path("result.txt").write_text("fail: file not found\n")
    sys.exit(1)

text = greeting_file.read_text().strip()
lines = text.splitlines()

errors = []
if not lines:
    errors.append("empty file")
elif len(lines) != 1:
    errors.append(f"expected 1 line, got {len(lines)}")
else:
    line = lines[0]
    if not line.startswith("Hello"):
        errors.append("must start with 'Hello'")
    if not line.endswith("!"):
        errors.append("must end with '!'")

if errors:
    for err in errors:
        print(f"FAIL: {err}", file=sys.stderr)
    Path("result.txt").write_text("fail\n")
    sys.exit(1)
else:
    print("PASS: greeting validated")
    Path("result.txt").write_text("pass\n")
    sys.exit(0)
