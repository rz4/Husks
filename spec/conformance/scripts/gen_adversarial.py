#!/usr/bin/env python3
"""
gen_adversarial.py — Freeze the Level-0 adversarial conformance vector.

Produces, under spec/conformance/:
  adversarial.site/          byte-exact site files (nasty names + content)
  adversarial.husk           canonical CSE bytes
  adversarial.root           lowercase hex build-root (computed by trusted core)
  malformed-leadingzero.husk must be REJECTED by a conformant reader
  malformed-truncated.husk   must be REJECTED by a conformant reader

The root is computed by husks.core — the trusted reader — not by any oracle.
"""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from husks.core import encode, parse, recompute_root, verify, CSE_VERSION, NIL

SPEC = os.path.join(os.path.dirname(__file__), "..", "spec", "conformance")
SITE = os.path.join(SPEC, "adversarial.site")

def main():
    os.makedirs(SITE, exist_ok=True)

    # Nasty-on-purpose site files. A JSON/regex/whitespace parser mishandles
    # the structural bytes inside atom CONTENT; a netstring reader does not,
    # because it reads exactly <length> bytes and never inspects them.
    site_files = {
        "in put.txt":  b"x",                          # space in a name atom
        "a:b().txt":   b"(4:fake) 3:no\nweird",       # ()/:/fake-atom/newline
        "verdict.txt": b":)\n",
    }
    for name, content in site_files.items():
        with open(os.path.join(SITE, name), "wb") as f:
            f.write(content)
        print(f"  wrote {name!r} ({len(content)} bytes)")

    # AST. action child -> oracle parent. The oracle prompt itself carries
    # structural bytes: parens, a colon, a fake nested netstring, a newline.
    action_recipe = [b"action"]
    oracle_recipe = [
        b"oracle", NIL,
        b"Parse (4:fake): 3:no carefully.\nReturn :)",   # adversarial prompt
        [b"read-file", b"write-file"], b"3",
    ]
    weird = [b"rule", b"weird", action_recipe,
             [b"in put.txt"], [b"a:b().txt"]]
    judge = [b"rule", b"judge", oracle_recipe,
             [b"a:b().txt"], [b"verdict.txt"], weird]
    husk = [b"husk", CSE_VERSION,
            [b"build", b"adversarial", b"10", judge]]

    husk_bytes = encode(husk)
    with open(os.path.join(SPEC, "adversarial.husk"), "wb") as f:
        f.write(husk_bytes)
    assert encode(parse(husk_bytes)) == husk_bytes, "round-trip failed"
    print(f"  wrote adversarial.husk ({len(husk_bytes)} bytes), round-trip OK")

    root = recompute_root(husk_bytes, SITE)
    with open(os.path.join(SPEC, "adversarial.root"), "w") as f:
        f.write(root + "\n")
    assert verify(husk_bytes, SITE, root), "self-verification failed"
    print(f"  wrote adversarial.root: {root}")

    # Malformed negatives — valid-looking but violate one CSE rule each.
    with open(os.path.join(SPEC, "malformed-leadingzero.husk"), "wb") as f:
        f.write(b"(05:hello)")          # leading zero in length -> reject
    with open(os.path.join(SPEC, "malformed-truncated.husk"), "wb") as f:
        f.write(b"(9:abc)")             # claims 9 bytes, 3 present -> reject
    print("  wrote malformed-leadingzero.husk, malformed-truncated.husk")

    # Confirm the trusted reader rejects both (sanity, not the gate).
    for fn in ("malformed-leadingzero.husk", "malformed-truncated.husk"):
        with open(os.path.join(SPEC, fn), "rb") as f:
            data = f.read()
        try:
            parse(data); raise SystemExit(f"FAIL: {fn} was not rejected")
        except ValueError:
            print(f"  trusted reader correctly rejects {fn}")

    print("\nAdversarial vector frozen.")

if __name__ == "__main__":
    main()
