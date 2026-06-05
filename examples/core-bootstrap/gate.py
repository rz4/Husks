"""
gate.py — Standalone conformance gate for CSE readers.

Runs frozen conformance vectors against a reader command and verifies
correct roots (positive vectors) and correct rejection (negative vectors).
Optionally cross-checks against the independent JavaScript reader.

Usage:
    python3 gate.py 'python3 readers/generated_reader.py' --stamp-dir readers
"""

import hashlib
import os
import shlex
import shutil
import subprocess
import sys
from pathlib import Path


# ── Vector resolution ────────────────────────────────────────────

def _conformance_dir() -> Path:
    """Resolve conformance vectors directory."""
    env = os.environ.get("HUSKS_CONFORMANCE_DIR")
    if env:
        p = Path(env).resolve()
        if p.exists():
            return p

    # Use the package accessor (handles wheel bundle and editable fallback)
    try:
        from husks._resources import conformance_dir
        return conformance_dir()
    except (ImportError, FileNotFoundError):
        pass

    # Repo-relative: examples/core-bootstrap -> repo -> spec/conformance
    here = Path(__file__).resolve().parent
    candidate = here.parent.parent / "spec" / "conformance"
    if candidate.exists():
        return candidate

    # Sibling spec/ directory (copied into example)
    sibling = here / "spec"
    if sibling.exists():
        return sibling

    raise FileNotFoundError(
        "Conformance vectors not found. Set HUSKS_CONFORMANCE_DIR or "
        "run from a source checkout."
    )


def _vectors(conf: Path) -> list[str]:
    """Return stem names of all .husk vector files."""
    return sorted(p.stem for p in conf.glob("*.husk"))


# ── Reader execution ─────────────────────────────────────────────

def _run_reader(reader_cmd: list[str], husk_path: Path, site_path: Path):
    """Run reader_cmd with husk and site as arguments."""
    try:
        return subprocess.run(
            [*reader_cmd, str(husk_path), str(site_path)],
            capture_output=True, text=True, timeout=60,
        )
    except FileNotFoundError:
        return None


# ── Gate logic ───────────────────────────────────────────────────

def gate(reader_cmd: list[str], *, stamp_dir=None, cross_check=True,
         verbose=True) -> bool:
    """Run the full conformance gate. Returns True on full pass."""
    conf = _conformance_dir()
    ok = True

    def _print(msg):
        if verbose:
            print(msg)

    def _fail(msg):
        nonlocal ok
        ok = False
        print(f"GATE FAIL: {msg}")

    names = _vectors(conf)
    conformance_pairs = []

    # ── positive vectors ─────────────────────────────────────
    for name in names:
        root_file = conf / f"{name}.root"
        if not root_file.exists():
            continue
        husk = conf / f"{name}.husk"
        site = conf / f"{name}.site"
        expected = root_file.read_text().strip()
        r = _run_reader(reader_cmd, husk, site)
        if r is None:
            _fail(f"{name}: reader command not found: {reader_cmd[0]}")
            continue
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
        _print(f"  {name}: root matches {expected[:16]}...")
        conformance_pairs.append((name, got))

    # ── negative vectors ─────────────────────────────────────
    for name in names:
        root_file = conf / f"{name}.root"
        if root_file.exists():
            continue
        husk = conf / f"{name}.husk"
        r = _run_reader(reader_cmd, husk, conf)
        if r is None:
            _fail(f"{name}: reader command not found: {reader_cmd[0]}")
            continue
        if r.returncode == 0:
            _fail(
                f"{name}: reader accepted malformed input "
                f"(printed {r.stdout.strip()[:32]})"
            )
            continue
        _print(f"  {name}: correctly rejected")

    # ── JS cross-check (optional) ────────────────────────────
    if cross_check:
        mjs = conf / "verify.mjs"
        if mjs.exists() and shutil.which("node"):
            for name in names:
                root_file = conf / f"{name}.root"
                if not root_file.exists():
                    husk = conf / f"{name}.husk"
                    r = subprocess.run(
                        ["node", str(mjs), str(husk), str(conf)],
                        capture_output=True, text=True, timeout=10,
                    )
                    if r.returncode == 0:
                        _fail(
                            f"cross-check {name}: JS reader accepted "
                            f"malformed input ({r.stdout.strip()[:32]})"
                        )
                    else:
                        _print(f"  cross-check {name}: JS reader correctly rejected")
                    continue
                expected = root_file.read_text().strip()
                husk = conf / f"{name}.husk"
                site = conf / f"{name}.site"
                r = subprocess.run(
                    ["node", str(mjs), str(husk), str(site), expected],
                    capture_output=True, text=True, timeout=10,
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
                "-- skipping JS cross-check; frozen roots stand)"
            )

    # ── stamp ────────────────────────────────────────────────
    if ok and stamp_dir is not None:
        stamp_dir = Path(stamp_dir)
        stamp_dir.mkdir(parents=True, exist_ok=True)

        digest_input = "\n".join(
            f"{name}:{root}" for name, root in sorted(conformance_pairs)
        )
        conformance_digest = hashlib.sha256(digest_input.encode()).hexdigest()

        (stamp_dir / "VERIFIED").write_text(conformance_digest + "\n")

        report_lines = [
            "Conformance Gate Report",
            "=" * 40,
            f"Reader: {' '.join(reader_cmd)}",
            f"Vectors: {len(conformance_pairs)} positive, "
            f"{len([n for n in names if not (conf / f'{n}.root').exists()])} negative",
            "",
            "Verified roots:",
        ]
        for name, root in sorted(conformance_pairs):
            report_lines.append(f"  {name}: {root}")
        report_lines.append("")
        report_lines.append(f"Conformance digest: {conformance_digest}")

        (stamp_dir / "gate-report.txt").write_text("\n".join(report_lines) + "\n")

    if ok:
        _print("GATE PASS")
    return ok


# ── CLI entry point ──────────────────────────────────────────────

def main(argv=None):
    import argparse

    p = argparse.ArgumentParser(
        prog="gate",
        description="Run the conformance gate against a CSE reader.",
    )
    p.add_argument(
        "reader_cmd",
        help='Reader command, e.g. "python my_reader.py"',
    )
    p.add_argument("--stamp-dir", default=None,
                   help="Write VERIFIED stamp here on pass")
    p.add_argument("--cross-check", action="store_true", default=True)
    p.add_argument("--no-cross-check", action="store_false", dest="cross_check")
    p.add_argument("--verbose", action="store_true", default=True)
    p.add_argument("--quiet", action="store_false", dest="verbose")
    args = p.parse_args(argv)

    reader = shlex.split(args.reader_cmd)
    ok = gate(reader, stamp_dir=args.stamp_dir, cross_check=args.cross_check,
              verbose=args.verbose)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
