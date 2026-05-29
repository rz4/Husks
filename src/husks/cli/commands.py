"""All _cmd_* command functions."""

from __future__ import annotations

import json
import os
import shlex
import shutil
import sys
from pathlib import Path

from husks.designs.ir import check, check_categorized, show, run, from_json
from husks.designs.convergence import read_history, convergence_summary
from husks.utils.console import _shorthash

from husks.cli.helpers import (
    _load_manifest, _STATE_SYM, resolve_design,
    EXIT_OK, EXIT_BUILD_FAIL, EXIT_USAGE, EXIT_MISSING_DEP, EXIT_DIRTY_STALE,
)


# ── run (Hy) ──────────────────────────────────────────────────────

def _cmd_run_hy(args):
    """Execute a .hy design file directly."""
    design_path = str(Path(args.design).resolve())

    # Suppress console trace in JSON mode or non-verbose default mode
    if args.json_output or not args.verbose:
        from husks.utils import trace as T_pre
        T_pre.clear_listeners()

    # Configure oracle backend before executing the .hy file
    if args.stub:
        # Replace live_oracle in the module so the .hy file picks up the stub
        import husks.oracle as _omod
        from husks.build.eval import default_oracle_backend
        _omod.live_oracle = default_oracle_backend
    else:
        from husks.oracle import set_oracle_model
        set_oracle_model(args.model)

    # Execute the .hy design
    try:
        import hy  # noqa: F401
        import runpy
        runpy.run_path(design_path, run_name="__main__")
    except ImportError:
        print("error: hy is not installed (pip install hy)", file=sys.stderr)
        sys.exit(EXIT_MISSING_DEP)
    except Exception as e:
        print(f"error: {e}", file=sys.stderr)
        sys.exit(EXIT_BUILD_FAIL)

    # Retrieve the Store captured by build()
    import husks.build.run as _brun
    S = _brun._last_store
    if S is None:
        print("error: .hy design did not call build()", file=sys.stderr)
        sys.exit(EXIT_BUILD_FAIL)

    # Build Report
    from husks.report import assemble, render_text, render_concise, render_json
    from husks.utils import trace as T

    report = assemble(S, T, {})
    if args.json_output:
        print(render_json(report))
    elif args.verbose:
        print(render_text(report))
    else:
        print(render_concise(report))

    if S.get("status") == "halted" and not args.soft_fail:
        sys.exit(EXIT_BUILD_FAIL)


# ── check ─────────────────────────────────────────────────────────

def _cmd_check(args, design):
    if args.json_output:
        result = check_categorized(design)
        print(json.dumps(result, indent=2))
        sys.exit(EXIT_OK if result["ok"] else EXIT_BUILD_FAIL)

    if args.verbose:
        # Validate then show full design details
        errs = check(design)
        if errs:
            print("warnings:", file=sys.stderr)
            for e in errs:
                print(f"  - {e}", file=sys.stderr)
        show(design)
        if errs:
            sys.exit(EXIT_BUILD_FAIL)
    else:
        # Structured per-category output
        result = check_categorized(design)
        for cat_name, cat in result["categories"].items():
            sym = "\u2713" if cat["ok"] else "\u2717"
            print(f"  {sym} {cat_name}")
            for err in cat["errors"]:
                print(f"    {err}")
        if result["ok"]:
            print("\nok")
        else:
            sys.exit(EXIT_BUILD_FAIL)


# ── run ───────────────────────────────────────────────────────────

def _cmd_run(args, design):
    overrides = {}
    if args.site:
        overrides["site"] = args.site

    if not args.stub:
        if args.hy:
            from husks.designs.hy import hy_kernel_backend
            kern = hy_kernel_backend()
            kern["set_oracle_model"](args.model)
            overrides["oracle_backend"] = kern["live_oracle"]
        else:
            from husks.oracle import live_oracle, set_oracle_model
            set_oracle_model(args.model)
            overrides["oracle_backend"] = live_oracle
        overrides["oracle_model"] = args.model

    # Suppress console trace in JSON mode or non-verbose default mode
    if args.json_output or not args.verbose:
        from husks.utils import trace as T_pre
        T_pre.clear_listeners()

    S = run(design, **overrides)

    # Build Report
    from husks.report import assemble, render_text, render_concise, render_json
    from husks.utils import trace as T

    report = assemble(S, T, design)
    if args.json_output:
        print(render_json(report))
    elif args.verbose:
        print(render_text(report))
    else:
        print(render_concise(report))

    if S.get("status") == "halted" and not args.soft_fail:
        sys.exit(EXIT_BUILD_FAIL)


# ── status ────────────────────────────────────────────────────────

def _cmd_status(args):
    from husks.manifest import compute_rule_states, compute_artifact_states
    from husks.core import recompute_root
    from pathlib import Path

    manifest, site = _load_manifest(args)
    rule_states = compute_rule_states(site, manifest)
    artifact_states = compute_artifact_states(site, manifest)

    # Beta Gate C3: Verify .husk root against live site
    manifest_root = manifest.get("root")
    root_valid = None
    recomputed_root = None

    if manifest_root:
        # Try to read and verify the .husk file
        build_name = manifest.get("name")
        if build_name:
            husk_path = Path(site) / f"{build_name}.husk"
            if husk_path.exists():
                try:
                    husk_bytes = husk_path.read_bytes()
                    recomputed_root = recompute_root(husk_bytes, site)
                    root_valid = (recomputed_root == manifest_root)
                except Exception:
                    # Recomputation failed (corrupt husk, missing files, etc.)
                    root_valid = False

    if args.json_output:
        output = {
            "site": site,
            "root": manifest_root,
            "rules": rule_states,
            "artifacts": artifact_states,
        }
        # Beta C3: Add root verification fields
        if root_valid is not None:
            output["root_valid"] = root_valid
        if recomputed_root is not None:
            output["recomputed_root"] = recomputed_root
        print(json.dumps(output, indent=2))
    else:
        print(f"\n  site: {site}")
        root = manifest_root or "none"
        root_display = root if root == "none" else f"{root[:16]}..."

        # Beta C3: Show root validity
        if root_valid is True:
            print(f"  root: {root_display} (verified)")
        elif root_valid is False:
            print(f"  root: {root_display} (INVALID)")
        else:
            print(f"  root: {root_display}")

        print(f"  {'─' * 50}")

        print("\n  rules:")
        for rs in rule_states:
            sym = _STATE_SYM.get(rs["state"], "?")
            reason = f"  ({rs['reason']})" if rs["reason"] else ""
            print(f"    {sym} {rs['name']:<20s} {rs['state']}{reason}")

        print("\n  artifacts:")
        for a in artifact_states:
            sym = _STATE_SYM.get(a["state"], "?")
            print(f"    {sym} {a['path']:<24s} {a['state']}")

        print(f"  {'─' * 50}\n")

    if args.fail_if_dirty:
        if any(a["state"] == "modified" for a in artifact_states):
            sys.exit(EXIT_DIRTY_STALE)
    if args.fail_if_stale:
        if any(rs["state"] in ("stale", "missing") for rs in rule_states):
            sys.exit(EXIT_DIRTY_STALE)


# ── explain ───────────────────────────────────────────────────────

def _cmd_explain(args):
    """Dispatch to the appropriate explain mode.

    In graph mode, treat subject as the design file path.
    """
    if args.graph:
        # Graph mode: subject is the design file
        if args.subject:
            args.design = args.subject
        _explain_graph(args)
    elif args.diff:
        _explain_diff(args)
    elif args.seal:
        _explain_seal(args)
    elif args.subject:
        _explain_subject(args)
    else:
        print("error: explain requires SUBJECT, --graph, --diff, or --seal",
              file=sys.stderr)
        sys.exit(EXIT_USAGE)


def _explain_subject(args):
    """Explain a rule, artifact, or root by name."""
    from husks.manifest import (
        read_seal, read_trial_report, compute_rule_state,
        compute_artifact_states,
    )

    manifest, site = _load_manifest(args)

    subject = args.subject
    rules = manifest.get("rules", [])
    rule_by_name = {r["name"]: r for r in rules}

    # Build output -> rule mapping
    output_to_rule: dict[str, dict] = {}
    for r in rules:
        for o in r.get("outputs", []):
            output_to_rule[o] = r

    info: dict = {}

    if subject == "root":
        # Explain the build root
        info = {
            "type": "root",
            "root": manifest.get("root"),
            "name": manifest.get("name"),
            "run_id": manifest.get("run_id"),
            "rules": [r["name"] for r in rules],
        }
    elif subject in rule_by_name:
        rule = rule_by_name[subject]
        seal = read_seal(site, subject)
        state, reason = compute_rule_state(site, rule, seal)
        trial = read_trial_report(site, subject)
        history = read_history(site, subject)

        info = {
            "type": "rule",
            "name": subject,
            "kind": rule["kind"],
            "inputs": rule.get("inputs", []),
            "outputs": rule.get("outputs", []),
            "state": state,
            "reason": reason,
            "seal": {
                "hash": seal.get("seal", "") if seal else None,
                "recipe_digest": seal.get("recipe_digest", "") if seal else None,
            } if seal else None,
            "history_count": len(history),
        }
        if trial:
            info["trial"] = trial
    elif subject in output_to_rule:
        rule = output_to_rule[subject]
        seal = read_seal(site, rule["name"])
        state, _ = compute_rule_state(site, rule, seal)

        # Use compute_artifact_states for this single rule's artifacts
        mini_manifest = {"rules": [rule]}
        artifacts = compute_artifact_states(site, mini_manifest)
        art = next((a for a in artifacts if a["path"] == subject), None)

        info = {
            "type": "artifact",
            "path": subject,
            "producing_rule": rule["name"],
            "rule_kind": rule["kind"],
            "state": state,
            "sealed_hash": art["sealed_hash"] if art else None,
            "current_hash": art["current_hash"] if art else None,
            "modified": art["state"] == "modified" if art else None,
        }
        trial = read_trial_report(site, rule["name"])
        if trial:
            info["trial"] = trial
    else:
        print(f"error: '{subject}' is not a known rule or artifact", file=sys.stderr)
        sys.exit(EXIT_USAGE)

    if args.json_output:
        print(json.dumps(info, indent=2))
    else:
        _render_explain(info)


def _explain_graph(args):
    """Render the dependency graph (formerly top-level 'graph' command)."""
    from husks.graph import render_graph

    design_path = resolve_design(args)
    design = from_json(design_path)
    print(render_graph(design, fmt=args.graph_format, site=args.site))


def _explain_diff(args):
    """Show differences between sealed and current artifacts (formerly top-level 'diff')."""
    from husks.manifest import compute_artifact_states

    manifest, site = _load_manifest(args)
    artifacts = compute_artifact_states(site, manifest)

    # Filter to specific artifacts if given
    if args.artifact:
        filter_set = set(args.artifact)
        artifacts = [a for a in artifacts if a["path"] in filter_set]

    # Categorize
    modified = [a for a in artifacts if a["state"] == "modified"]
    missing = [a for a in artifacts if a["state"] == "missing"]
    fresh = [a for a in artifacts if a["state"] == "fresh"]

    # Check for undeclared files in site (not in any rule's outputs)
    declared = {a["path"] for a in artifacts}
    undeclared: list[str] = []
    site_path = Path(site)
    if site_path.exists():
        for f in site_path.iterdir():
            if f.name.startswith(".") or f.name.endswith(".husk"):
                continue
            if f.is_file() and f.name not in declared:
                undeclared.append(f.name)

    if args.json_output:
        print(json.dumps({
            "site": site,
            "modified": [a["path"] for a in modified],
            "missing": [a["path"] for a in missing],
            "fresh": [a["path"] for a in fresh],
            "undeclared": undeclared,
        }, indent=2))
    else:
        if not modified and not missing and not undeclared:
            print("  no differences")
            return

        if modified:
            print("\n  modified:")
            for a in modified:
                sealed = (a["sealed_hash"] or "")[:10]
                current = (a["current_hash"] or "")[:10]
                print(f"    {a['path']:<24s} {sealed} -> {current}")
        if missing:
            print("\n  missing:")
            for a in missing:
                print(f"    {a['path']}")
        if undeclared:
            print("\n  undeclared:")
            for u in undeclared:
                print(f"    {u}")
        print()


def _explain_seal(args):
    """Show seal material for a rule, artifact, or root."""
    from husks.manifest import read_seal

    manifest, site = _load_manifest(args)
    subject = args.seal

    rules = manifest.get("rules", [])
    rule_by_name = {r["name"]: r for r in rules}

    # Build output -> rule mapping
    output_to_rule: dict[str, dict] = {}
    for r in rules:
        for o in r.get("outputs", []):
            output_to_rule[o] = r

    if subject == "root":
        info = {
            "type": "root_seal",
            "root": manifest.get("root"),
        }
    elif subject in rule_by_name:
        seal = read_seal(site, subject)
        info = {
            "type": "rule_seal",
            "name": subject,
            "seal": seal,
        }
    elif subject in output_to_rule:
        rule = output_to_rule[subject]
        seal = read_seal(site, rule["name"])
        info = {
            "type": "artifact_seal",
            "path": subject,
            "producing_rule": rule["name"],
            "seal": seal,
        }
    else:
        print(f"error: '{subject}' is not a known rule or artifact", file=sys.stderr)
        sys.exit(EXIT_USAGE)

    if args.json_output:
        print(json.dumps(info, indent=2, default=str))
    else:
        print(json.dumps(info, indent=2, default=str))


def _render_explain(info: dict) -> None:
    """Render explain output as text."""
    etype = info.get("type", "?")
    print()

    if etype == "root":
        root = info.get("root", "none") or "none"
        print(f"  build root: {root}")
        print(f"  name:       {info.get('name', '?')}")
        print(f"  run_id:     {info.get('run_id', '?')}")
        print(f"\n  rules:")
        for rn in info.get("rules", []):
            print(f"    {rn}")

    elif etype == "rule":
        print(f"  rule: {info['name']}  ({info['kind']})")
        print(f"  state: {info['state']}", end="")
        if info.get("reason"):
            print(f"  ({info['reason']})", end="")
        print()
        if info.get("inputs"):
            print(f"  inputs:  {', '.join(info['inputs'])}")
        if info.get("outputs"):
            print(f"  outputs: {', '.join(info['outputs'])}")
        if info.get("seal"):
            seal = info["seal"]
            print(f"  seal:    {(seal.get('hash') or '')[:16]}...")
        print(f"  history: {info.get('history_count', 0)} runs")
        if info.get("trial"):
            trial = info["trial"]
            print(f"\n  trial verdict: {trial.get('winner', '?')}")
            for b in trial.get("branches", []):
                sel = " \u25c0" if b.get("selected") else ""
                score = f"  score {b['score']:.2f}" if "score" in b else ""
                print(f"    {b['name']}  {b['kind']}  "
                      f"{b.get('elapsed_ms', 0):.0f}ms{score}{sel}")

    elif etype == "artifact":
        print(f"  artifact: {info['path']}")
        print(f"  rule:     {info['producing_rule']}  ({info['rule_kind']})")
        print(f"  state:    {info['state']}")
        if info.get("sealed_hash"):
            print(f"  sealed:   {info['sealed_hash'][:16]}...")
        if info.get("current_hash"):
            print(f"  current:  {info['current_hash'][:16]}...")
        if info.get("modified") is True:
            print(f"  modified: yes")
        if info.get("trial"):
            trial = info["trial"]
            print(f"\n  trial verdict: {trial.get('winner', '?')}")

    print()


# ── history ───────────────────────────────────────────────────────

def _cmd_history(args, design):
    site = args.site or design.get("site")
    if not site:
        print("error: no site directory. Use --site or set 'site' in design.",
              file=sys.stderr)
        sys.exit(EXIT_BUILD_FAIL)

    if args.rule:
        # detailed history for one rule
        entries = read_history(site, args.rule)
        if not entries:
            print(f"  no history for '{args.rule}' in {site}")
            sys.exit(EXIT_OK)
        recent = entries[-args.n:]
        print(f"\n  history: {args.rule}  ({len(entries)} total, showing last {len(recent)})")
        print(f"  {'─' * 72}")
        print(f"  {'run_id':<12s} {'fuel':>4s} {'prompt':>6s} {'sat':>5s} {'reads':>5s} {'output hash':<12s}")
        print(f"  {'─' * 72}")
        for e in recent:
            rid = e.get("run_id", "?")[:10]
            fuel = str(e.get("fuel_consumed", "?"))
            pl = e.get("prompt_length")
            prompt = str(pl) if pl is not None else "\u2013"
            sat = e.get("satisfaction")
            sat_str = "true" if sat is True else ("false" if sat is False else "\u2013")
            reads = str(len(e.get("traced_reads", [])))
            hashes = e.get("output_hashes", [])
            ohash = _shorthash(hashes[0]) if hashes else "\u2013"
            print(f"  {rid:<12s} {fuel:>4s} {prompt:>6s} {sat_str:>5s} {reads:>5s} {ohash:<12s}")
        print(f"  {'─' * 72}")

        # convergence summary
        cs = convergence_summary(args.rule, site, n=args.n)
        print(f"\n  convergence: {cs['classification']}")
        if cs["fuel_trend"]:
            print(f"    fuel:   {cs['fuel_trend']}")
        if cs["prompt_trend"]:
            print(f"    prompt: {cs['prompt_trend']}")
        if cs["output_stable"] is not None:
            print(f"    output: {'stable' if cs['output_stable'] else 'varying'}")
        print()
    else:
        # summary for all rules
        rules = design.get("rules", [])
        print(f"\n  convergence history summary  (site: {site})")
        print(f"  {'─' * 60}")
        for r in rules:
            rname = r["name"]
            entries = read_history(site, rname)
            if not entries:
                print(f"  {rname:<24s} no history")
                continue
            n = min(args.n, len(entries))
            cs = convergence_summary(rname, site, n=n)
            print(f"  {rname:<24s} {len(entries)} runs  {cs['classification']}")
        print(f"  {'─' * 60}\n")


# ── doctor ────────────────────────────────────────────────────────

def _cmd_doctor(args):
    # Handle --selftest mode
    if args.selftest:
        from husks.setup import selftest
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

    # Default: environment checks
    checks: list[dict] = []

    # 1. husks import
    try:
        import husks  # noqa: F401
        checks.append({"name": "husks", "ok": True, "detail": "importable"})
    except Exception as ex:
        checks.append({"name": "husks", "ok": False, "detail": str(ex)})

    # 2. conformance vectors
    try:
        from husks.setup import _resolve_conformance
        conf = _resolve_conformance()
        vectors = sorted(p.stem for p in conf.glob("*.husk"))
        checks.append({"name": "conformance", "ok": bool(vectors),
                        "detail": f"{len(vectors)} vectors at {conf}"})
    except Exception as ex:
        checks.append({"name": "conformance", "ok": False, "detail": str(ex)})

    # 3. selftest
    try:
        from husks.setup import selftest
        ok = selftest(verbose=False)
        checks.append({"name": "selftest", "ok": ok,
                        "detail": "pass" if ok else "fail"})
    except Exception as ex:
        checks.append({"name": "selftest", "ok": False, "detail": str(ex)})

    # 4. hy
    try:
        import hy  # noqa: F401
        checks.append({"name": "hy", "ok": True, "detail": "importable"})
    except ImportError:
        checks.append({"name": "hy", "ok": None, "detail": "not installed (optional)"})

    # 5. litellm
    try:
        import litellm  # noqa: F401
        checks.append({"name": "litellm", "ok": True, "detail": "importable"})
    except ImportError:
        checks.append({"name": "litellm", "ok": False,
                        "detail": "not installed (required for live oracle)"})

    # 6. ANTHROPIC_API_KEY
    key = os.environ.get("ANTHROPIC_API_KEY", "")
    if key:
        checks.append({"name": "ANTHROPIC_API_KEY", "ok": True,
                        "detail": f"set ({key[:4]}...)"})
    else:
        checks.append({"name": "ANTHROPIC_API_KEY", "ok": None,
                        "detail": "not set (needed for live runs)"})

    # 7. git
    if shutil.which("git"):
        checks.append({"name": "git", "ok": True, "detail": "found"})
    else:
        checks.append({"name": "git", "ok": None, "detail": "not found (optional)"})

    # 8. node
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
    from husks.gate import gate

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
    """Check live oracle readiness (API key + test call)."""
    key = os.environ.get("ANTHROPIC_API_KEY", "")
    checks = []

    if key:
        checks.append({"name": "ANTHROPIC_API_KEY", "ok": True,
                        "detail": f"set ({key[:4]}...)"})
    else:
        checks.append({"name": "ANTHROPIC_API_KEY", "ok": False,
                        "detail": "not set"})

    try:
        import litellm  # noqa: F401
        checks.append({"name": "litellm", "ok": True, "detail": "importable"})
    except ImportError:
        checks.append({"name": "litellm", "ok": False, "detail": "not installed"})

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
