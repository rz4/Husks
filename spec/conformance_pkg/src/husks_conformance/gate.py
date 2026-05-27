"""
gate.py — command-agnostic conformance gate for CSE readers.

Any reader that accepts ``<reader_cmd> <husk> <site>`` and prints the
lowercase-hex root to stdout (exit 0 on success, nonzero on rejection)
can be validated against the frozen conformance vectors.

    from husks_conformance.gate import gate
    assert gate(["python", "generated_reader.py"])
    assert gate(["./my_rust_reader"])
    assert gate(["node", "reader.mjs"])
"""

import os
import subprocess
import shutil
from pathlib import Path

from husks_conformance import conformance_dir, vectors


# ── exception ────────────────────────────────────────────────────────

class GateError(Exception):
    """Raised by import_scan_python on policy violations."""


# ── constants ────────────────────────────────────────────────────────

ALLOWED_IMPORTS = frozenset({
    "sys", "os", "hashlib", "io", "pathlib", "typing",
    "__future__", "binascii",
})

FORBIDDEN_IMPORTS = frozenset({
    "json", "re", "ast", "pickle", "yaml", "toml",
})


# ── helpers ──────────────────────────────────────────────────────────

def run_reader(reader_cmd, husk_path, site_path):
    """Run *reader_cmd* with *husk_path* and *site_path* as arguments.

    Returns the ``subprocess.CompletedProcess``.
    """
    return subprocess.run(
        [*reader_cmd, str(husk_path), str(site_path)],
        capture_output=True, text=True, timeout=60,
    )


def import_scan_python(reader_path, *, allowed=None, forbidden=None):
    """Scan a Python reader for import policy violations.

    Raises ``GateError`` if the reader imports a forbidden module or one
    not in the allowed set.  This is a *fast-fail* heuristic, not a
    security boundary — the real gate is the conformance vectors.
    """
    allowed = ALLOWED_IMPORTS if allowed is None else frozenset(allowed)
    forbidden = FORBIDDEN_IMPORTS if forbidden is None else frozenset(forbidden)

    with open(reader_path) as f:
        src = f.read()

    for line in src.splitlines():
        s = line.strip()
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
            if mod in forbidden:
                raise GateError(f"reader imports forbidden module '{mod}'")
            if mod not in allowed:
                raise GateError(f"reader imports non-whitelisted module '{mod}'")


# ── main gate ────────────────────────────────────────────────────────

def gate(reader_cmd, *, stamp_dir=None, cross_check=True, verbose=True):
    """Run the full conformance gate for *reader_cmd*.

    Returns ``True`` on full pass, ``False`` on any failure.
    """
    conf = conformance_dir()
    ok = True

    def _print(msg):
        if verbose:
            print(msg)

    def _fail(msg):
        nonlocal ok
        ok = False
        print(f"GATE FAIL: {msg}")

    # ── positive vectors ─────────────────────────────────────────
    for name in vectors():
        root_file = conf / f"{name}.root"
        if not root_file.exists():
            continue  # handled in negative pass
        husk = conf / f"{name}.husk"
        site = conf / f"{name}.site"
        expected = root_file.read_text().strip()
        r = run_reader(reader_cmd, husk, site)
        if r.returncode != 0:
            _fail(f"{name}: reader exited {r.returncode}: {r.stderr[:300]}")
            continue
        got = r.stdout.strip()
        if got != expected:
            _fail(
                f"{name}: root mismatch\n"
                f"    expected {expected}\n"
                f"    got      {got}"
            )
            continue
        _print(f"  {name}: root matches {expected[:16]}…")

    # ── negative vectors ─────────────────────────────────────────
    for name in vectors():
        root_file = conf / f"{name}.root"
        if root_file.exists():
            continue  # already handled as positive
        husk = conf / f"{name}.husk"
        r = run_reader(reader_cmd, husk, conf)
        if r.returncode == 0:
            _fail(
                f"{name}: reader accepted malformed input "
                f"(printed {r.stdout.strip()[:32]})"
            )
            continue
        _print(f"  {name}: correctly rejected")

    # ── JS cross-check (optional) ────────────────────────────────
    if cross_check:
        mjs = conf / "verify.mjs"
        if mjs.exists() and shutil.which("node"):
            for name in vectors():
                root_file = conf / f"{name}.root"
                if not root_file.exists():
                    continue
                expected = root_file.read_text().strip()
                husk = conf / f"{name}.husk"
                site = conf / f"{name}.site"
                r = subprocess.run(
                    ["node", str(mjs), str(husk), str(site), expected],
                    capture_output=True, text=True,
                )
                if r.returncode != 0:
                    _fail(
                        f"cross-check {name}: JS reader disagrees: "
                        f"{r.stdout} {r.stderr}"
                    )
                    continue
                _print(f"  cross-check {name}: JS reader agrees")
        else:
            _print(
                "  (node not found or verify.mjs missing "
                "— skipping JS cross-check; frozen roots stand)"
            )

    # ── stamp ────────────────────────────────────────────────────
    if ok and stamp_dir is not None:
        stamp_dir = Path(stamp_dir)
        stamp_dir.mkdir(parents=True, exist_ok=True)
        (stamp_dir / "VERIFIED").write_text("PASS\n")

    if ok:
        _print("GATE PASS")
    return ok


# ── CLI entry point ─────────────────────────────────────────────────

def main(argv=None):
    """Entry point for the ``husks-gate`` console script."""
    import argparse
    import sys

    p = argparse.ArgumentParser(
        prog="husks-gate",
        description="Run the conformance gate against a CSE reader.",
    )
    p.add_argument(
        "reader_cmd",
        nargs="?",
        default="husks",
        help="Reader command (default: husks)",
    )
    p.add_argument("--stamp-dir", default=None, help="Write VERIFIED stamp here on pass")
    p.add_argument("--cross-check", action="store_true", default=True,
                   help="Enable JS cross-check (default)")
    p.add_argument("--no-cross-check", action="store_false", dest="cross_check",
                   help="Disable JS cross-check")
    p.add_argument("--verbose", action="store_true", default=True)
    p.add_argument("--quiet", action="store_false", dest="verbose")
    args = p.parse_args(argv)

    reader = args.reader_cmd.split()
    ok = gate(reader, stamp_dir=args.stamp_dir, cross_check=args.cross_check,
              verbose=args.verbose)
    sys.exit(0 if ok else 1)
