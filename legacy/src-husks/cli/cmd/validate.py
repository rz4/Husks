"""All _cmd_* command functions."""

from __future__ import annotations

import json
import os
import shlex
import shutil
import sys

from husks.cli.helpers import EXIT_OK, EXIT_BUILD_FAIL, EXIT_USAGE, EXIT_MISSING_DEP
from husks.gate import selftest, gate, _resolve_conformance
from husks._arch.check import check_architecture


# ── doctor ────────────────────────────────────────────────────────

def _cmd_doctor(args):
    # Handle --arch mode
    if args.arch:
        _doctor_arch(args)
        return

    # Handle --selftest mode
    if args.selftest:
        ok = selftest()
        if not args.json_output:
            print("selftest: pass" if ok else "selftest: FAIL")
        else:
            print(json.dumps({"selftest": ok}))
        sys.exit(EXIT_OK if ok else EXIT_BUILD_FAIL)

    # Handle --conformance mode
    if args.conformance:
        if not args.reader_cmd:
            print("error: --conformance requires --reader", file=sys.stderr)
            sys.exit(EXIT_USAGE)
        _doctor_conformance(args)
        return

    # Handle --live mode
    if args.live:
        _doctor_live(args)
        return

    # Default: core environment checks (Beta Gate G5)
    # Only checks things that work without external dependencies.
    # Use --live for oracle readiness checks.
    checks: list[dict] = []

    # 1. husks import
    try:
        import husks  # noqa: F401
        checks.append({"name": "husks", "ok": True, "detail": "importable"})
    except Exception as ex:
        checks.append({"name": "husks", "ok": False, "detail": str(ex)})

    # 2. conformance vectors
    try:
        conf = _resolve_conformance()
        vectors = sorted(p.stem for p in conf.glob("*.husk"))
        checks.append({"name": "conformance", "ok": bool(vectors),
                        "detail": f"{len(vectors)} vectors at {conf}"})
    except Exception as ex:
        checks.append({"name": "conformance", "ok": False, "detail": str(ex)})

    # 3. selftest (core deterministic verification)
    try:
        ok = selftest(verbose=False)
        checks.append({"name": "selftest", "ok": ok,
                        "detail": "pass" if ok else "fail"})
    except Exception as ex:
        checks.append({"name": "selftest", "ok": False, "detail": str(ex)})

    # Note: litellm, API key, git, node moved to --live mode (Beta Gate G5)

    if args.json_output:
        print(json.dumps({"checks": checks}, indent=2))
    else:
        print()
        for c in checks:
            if c["ok"] is True:
                sym = "\u2713"
            elif c["ok"] is False:
                sym = "\u2717"
            else:
                sym = "\u25cb"
            print(f"  {sym} {c['name']:<20s} {c['detail']}")
        print()

        any_fail = any(c["ok"] is False for c in checks)
        if any_fail:
            sys.exit(EXIT_MISSING_DEP)


def _doctor_conformance(args):
    """Run external reader conformance gate (formerly top-level 'gate')."""
    # Beta B6: Use shlex.split() to handle quoted arguments
    reader = shlex.split(args.reader_cmd)
    cross_check = getattr(args, "cross_check", True)
    verbose = args.verbose if not args.json_output else False

    ok = gate(reader, stamp_dir=args.stamp_dir, cross_check=cross_check,
              verbose=verbose)

    if args.json_output:
        print(json.dumps({"pass": ok}))

    sys.exit(EXIT_OK if ok else EXIT_BUILD_FAIL)


def _doctor_live(args):
    """Check live oracle readiness (Beta Gate G5).

    Tests all dependencies and services needed for live oracle runs:
    - API key configuration
    - litellm library
    - Live oracle ping test
    - Optional dev tools (git, node)
    """
    checks = []

    # 1. ANTHROPIC_API_KEY
    key = os.environ.get("ANTHROPIC_API_KEY", "")
    if key:
        checks.append({"name": "ANTHROPIC_API_KEY", "ok": True,
                        "detail": f"set ({key[:4]}...)"})
    else:
        checks.append({"name": "ANTHROPIC_API_KEY", "ok": False,
                        "detail": "not set"})

    # 2. litellm library
    try:
        import litellm  # noqa: F401
        checks.append({"name": "litellm", "ok": True, "detail": "importable"})
    except ImportError:
        checks.append({"name": "litellm", "ok": False, "detail": "not installed"})

    # 3. Live oracle ping (only if key is set)
    if key:
        try:
            from litellm import completion
            resp = completion(
                model="anthropic/claude-haiku-4-5-20251001",
                messages=[{"role": "user", "content": "ping"}],
                max_tokens=1,
            )
            checks.append({"name": "oracle ping", "ok": True, "detail": "responded"})
        except Exception as ex:
            checks.append({"name": "oracle ping", "ok": False, "detail": str(ex)})

    # 4. git (optional dev tool)
    if shutil.which("git"):
        checks.append({"name": "git", "ok": True, "detail": "found"})
    else:
        checks.append({"name": "git", "ok": None, "detail": "not found (optional)"})

    # 5. node (optional for JS cross-check)
    if shutil.which("node"):
        checks.append({"name": "node", "ok": True, "detail": "found"})
    else:
        checks.append({"name": "node", "ok": None,
                        "detail": "not found (needed for JS cross-check)"})

    if args.json_output:
        print(json.dumps({"checks": checks}, indent=2))
    else:
        print()
        for c in checks:
            sym = "\u2713" if c["ok"] else "\u2717"
            print(f"  {sym} {c['name']:<20s} {c['detail']}")
        print()

    if any(c["ok"] is False for c in checks):
        sys.exit(EXIT_MISSING_DEP)


def _doctor_arch(args):
    """Check architecture conformance (Phase 0: report-only).

    Verifies the module dependency graph against layers.toml.
    In Phase 0, this runs in report-only mode (always exits 0).
    In Phase 3, this will be enforcing mode (exits non-zero on violations).
    """
    from pathlib import Path
    try:
        import tomllib  # Python 3.11+
    except ImportError:
        import tomli as tomllib  # Python 3.10

    # Find layers.toml (packaged in wheel or at repo root)
    pkg_dir = Path(__file__).resolve().parent.parent.parent  # ...husks/cli/cmd -> husks
    packaged_layers = pkg_dir / "_resources" / "layers.toml"

    if packaged_layers.exists():
        # Wheel install
        layers_toml = packaged_layers
        src_root = pkg_dir.parent / "husks"  # site-packages/husks
    else:
        # Editable/source install - walk up to find repo root
        current = Path(__file__).resolve()
        for parent in [current] + list(current.parents):
            candidate = parent / "layers.toml"
            if candidate.exists():
                layers_toml = candidate
                src_root = parent / "src"
                break
        else:
            print("error: could not find layers.toml", file=sys.stderr)
            sys.exit(EXIT_USAGE)

    if not src_root.exists():
        print(f"error: src directory not found at {src_root}", file=sys.stderr)
        sys.exit(EXIT_USAGE)

    # Load the contract
    try:
        contract = tomllib.loads(layers_toml.read_text())
    except Exception as e:
        print(f"error: failed to load layers.toml: {e}", file=sys.stderr)
        sys.exit(EXIT_USAGE)

    # Run the checker
    try:
        violations = check_architecture(src_root, contract)
    except Exception as e:
        print(f"error: architecture check failed: {e}", file=sys.stderr)
        sys.exit(EXIT_BUILD_FAIL)

    # Output results
    if args.json_output:
        result = {
            "violations": violations,
            "count": len(violations),
            "pass": len(violations) == 0,
        }
        print(json.dumps(result, indent=2))
    else:
        print()
        if violations:
            print(f"Architecture violations: {len(violations)}")
            print()
            for v in violations:
                print(f"  \u2717 {v}")
            print()
            print("Phase 0: Report-only mode (exit 0)")
            print("These violations will be removed in phases 1-2.")
        else:
            print("\u2713 No architecture violations detected!")
        print()

    # Phase 3: Enforcing mode enabled
    # Exit non-zero if any violations detected
    if len(violations) > 0:
        if not args.json_output:
            print(f"FAIL: {len(violations)} architecture violations")
        sys.exit(EXIT_BUILD_FAIL)

    sys.exit(EXIT_OK)
