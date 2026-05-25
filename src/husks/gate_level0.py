#!/usr/bin/env python3
"""
gate_level0.py — exogenous judge for the Level-0 generated reader.

Invoked as an action with the build site as argv[1] (cwd is the site).
The generated reader lives at <site>/readers/generated_reader.py and must:
  - print the lowercase-hex build-root for <husk> <site> and exit 0
  - exit nonzero on any CSE violation

The gate's teeth are the adversarial root, which only a real netstring reader
can reproduce. The import scan is a fast fail, not the real check.
"""
import os, sys, subprocess
from husks.resources import conformance_dir

# Conformance vectors: packaged (wheel) or repo-root spec/conformance (source).
CONF = str(conformance_dir())
REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))

ALLOWED_IMPORTS = {"sys", "os", "hashlib", "io", "pathlib", "typing",
                   "__future__", "binascii"}
FORBIDDEN = {"json", "re", "ast", "pickle", "yaml", "toml"}

def fail(msg):
    print(f"GATE FAIL: {msg}")
    sys.exit(1)

def run_reader(reader, husk, site):
    return subprocess.run([sys.executable, reader, husk, site],
                          capture_output=True, text=True, timeout=60)

def import_scan(reader):
    with open(reader) as f:
        src = f.read()
    for ln in src.splitlines():
        s = ln.strip()
        if s.startswith("import "):
            names = s[len("import "):]
        elif s.startswith("from "):
            names = s[len("from "):].split(" import ")[0]
        else:
            continue
        for part in names.split(","):
            mod = part.strip().split(" as ")[0].split(".")[0].strip()
            if not mod:
                continue
            if mod in FORBIDDEN:
                fail(f"reader imports forbidden module '{mod}'")
            if mod not in ALLOWED_IMPORTS:
                fail(f"reader imports non-whitelisted module '{mod}'")
    print("  import scan: clean")

def positive(reader, name):
    husk = os.path.join(CONF, f"{name}.husk")
    site = os.path.join(CONF, f"{name}.site")
    with open(os.path.join(CONF, f"{name}.root")) as f:
        expected = f.read().strip()
    r = run_reader(reader, husk, site)
    if r.returncode != 0:
        fail(f"{name}: reader exited {r.returncode}: {r.stderr[:300]}")
    got = r.stdout.strip()
    if got != expected:
        fail(f"{name}: root mismatch\n    expected {expected}\n    got      {got}")
    print(f"  {name}: root matches {expected[:16]}…")

def negative(reader, fn):
    r = run_reader(reader, os.path.join(CONF, fn), CONF)
    if r.returncode == 0:
        fail(f"{fn}: reader accepted malformed input (printed {r.stdout.strip()[:32]})")
    print(f"  {fn}: correctly rejected")

def cross_check(name):
    mjs = os.path.join(CONF, "verify.mjs")
    with open(os.path.join(CONF, f"{name}.root")) as f:
        root = f.read().strip()
    r = subprocess.run(["node", mjs, os.path.join(CONF, f"{name}.husk"),
                        os.path.join(CONF, f"{name}.site"), root],
                       capture_output=True, text=True)
    if r.returncode != 0:
        fail(f"cross-check {name}: independent JS reader disagrees: {r.stdout} {r.stderr}")
    print(f"  cross-check {name}: JS reader agrees")

def main():
    site = os.path.abspath(sys.argv[1] if len(sys.argv) > 1 else ".")
    reader = os.path.join(site, "readers", "generated_reader.py")

    if not os.path.exists(reader):
        fail(f"no generated reader at {reader}")
    print("Level-0 gate:")
    import_scan(reader)
    positive(reader, "demo")
    positive(reader, "adversarial")
    negative(reader, "malformed-leadingzero.husk")
    negative(reader, "malformed-truncated.husk")
    try:
        cross_check("demo"); cross_check("adversarial")
    except FileNotFoundError:
        print("  (node not found — skipping live JS cross-check; frozen roots stand)")
    os.makedirs(os.path.join(site, "readers"), exist_ok=True)
    with open(os.path.join(site, "readers", "VERIFIED"), "w") as f:
        f.write("PASS\n")
    print("GATE PASS")

if __name__ == "__main__":
    main()
