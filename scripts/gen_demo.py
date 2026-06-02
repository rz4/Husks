#!/usr/bin/env python3
"""
gen_demo.py — Generate the golden conformance vector for CSE v1.

Creates:
  spec/conformance/demo.site/   — byte-exact site files
  spec/conformance/demo.husk    — canonical CSE bytes
  spec/conformance/demo.root    — lowercase hex build-root

This script uses husks.core (the dependency-free reader) to build
the demo AST and serialize it.
"""

import os
import sys

# Ensure we can import from src/
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from husks.core import (
    encode, parse, atom, atom_str, sha256_bytes,
    content_hash, content_hash_or_absent,
    compute_seal, compute_node_digest, recipe_digest,
    recompute_root, verify,
    NIL, CSE_VERSION, ABSENT,
)

SPEC_DIR = os.path.join(os.path.dirname(__file__), "..", "spec", "conformance")
SITE_DIR = os.path.join(SPEC_DIR, "demo.site")


def main():
    # ── Step 1: Create demo.site/ with exact byte content ──────────

    os.makedirs(SITE_DIR, exist_ok=True)

    site_files = {
        "greeting.txt": b"Hello, world!\n",       # 14 bytes
        "config.txt":   b"mode=demo\n",            # 10 bytes
        "hello.txt":    b"Hello from demo!\n",     # 17 bytes
        "result.txt":   b"Combined: Hello from demo!\n",  # 27 bytes
    }

    for name, content in site_files.items():
        path = os.path.join(SITE_DIR, name)
        with open(path, "wb") as f:
            f.write(content)
        print(f"  wrote {name} ({len(content)} bytes)")

    # ── Step 2: Construct the demo AST ─────────────────────────────
    #
    # Two rules:
    #   "greet"   — action, inputs=[config.txt, greeting.txt], outputs=[hello.txt]
    #   "combine" — oracle, inputs=[hello.txt], outputs=[result.txt], children=[greet]
    #
    # Recipe forms:
    #   action  = (6:action)
    #   oracle  = (6:oracle 0: 18:Combine the files. (9:read-file 10:write-file) 1:3)
    #             (6:oracle <name=NIL> <prompt> (tools...) <fuel>)

    action_recipe = [b"action"]

    oracle_recipe = [
        b"oracle",
        NIL,                              # name (nil)
        b"Combine the files.",            # prompt
        [b"read-file", b"write-file"],    # tools
        b"3",                             # fuel
    ]

    # Rule: greet
    #   (4:rule 5:greet <action_recipe> (10:config.txt 12:greeting.txt) (9:hello.txt))
    greet_rule = [
        b"rule",
        b"greet",
        action_recipe,
        [b"config.txt", b"greeting.txt"],   # inputs (sorted by design)
        [b"hello.txt"],                      # outputs
        # no children
    ]

    # Rule: combine
    #   (4:rule 7:combine <oracle_recipe> (9:hello.txt) (10:result.txt) <greet_rule>)
    combine_rule = [
        b"rule",
        b"combine",
        oracle_recipe,
        [b"hello.txt"],                      # inputs
        [b"result.txt"],                     # outputs
        greet_rule,                          # child
    ]

    # Build wrapper
    #   (4:husk 1:1 (5:build 4:demo 2:10 <combine_rule>))
    husk_tree = [
        b"husk",
        CSE_VERSION,
        [
            b"build",
            b"demo",
            b"10",
            combine_rule,
        ],
    ]

    # ── Step 3: Serialize and write demo.husk ──────────────────────

    husk_bytes = encode(husk_tree)
    husk_path = os.path.join(SPEC_DIR, "demo.husk")
    with open(husk_path, "wb") as f:
        f.write(husk_bytes)
    print(f"  wrote demo.husk ({len(husk_bytes)} bytes)")

    # Verify it round-trips
    parsed_back = parse(husk_bytes)
    assert encode(parsed_back) == husk_bytes, "round-trip failed!"
    print("  round-trip OK")

    # ── Step 4: Compute root and write demo.root ───────────────────

    root = recompute_root(husk_bytes, SITE_DIR)
    root_path = os.path.join(SPEC_DIR, "demo.root")
    with open(root_path, "w") as f:
        f.write(root + "\n")
    print(f"  wrote demo.root: {root}")

    # ── Step 5: Self-verify ────────────────────────────────────────

    assert verify(husk_bytes, SITE_DIR, root), "verification failed!"
    print("  self-verification PASSED")

    print("\nDone. Golden vector generated successfully.")


if __name__ == "__main__":
    main()
