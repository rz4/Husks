#- cli.py — command-line interface for Husks designs
#
# Commands:
#   husks check   design.json [--verbose] [--json]
#   husks run     design.json [--site ...] [--model ...] [--verbose] [--json]
#   husks status  [design.json] --site SITE [--json] [--fail-if-dirty] [--fail-if-stale]
#   husks diff    [design.json] --site SITE [artifact...] [--json]
#   husks explain subject --site SITE [--json]
#   husks graph   design.json [--format text|mermaid|dot|json] [--site SITE]
#   husks history design.json [rule] [--site SITE] [-n N]
#   husks gate    reader_cmd [--stamp-dir DIR] [--no-cross-check] [--json] [--verbose]
#   husks doctor  [--json]
#   husks selftest [--conformance DIR]
#   husks init    [target] [--no-claude-code] [--force]

import argparse
import json
import sys
from pathlib import Path

from husks.designs.ir import check, check_categorized, show, run, from_json
from husks.designs.convergence import read_history, convergence_summary
from husks.utils.console import _shorthash

# ── Exit codes ────────────────────────────────────────────────────

EXIT_OK = 0
EXIT_BUILD_FAIL = 1
EXIT_USAGE = 2
EXIT_MISSING_DEP = 3
EXIT_DIRTY_STALE = 4
EXIT_INTERNAL = 5


def main():
    p = argparse.ArgumentParser(prog="husks", description="Husks design CLI")

    # Global options
    p.add_argument("--color", choices=["auto", "always", "never"], default="auto",
                   help="Color output mode")
    p.add_argument("--quiet", "-q", action="store_true",
                   help="Suppress non-essential output")
    p.add_argument("--version", action="store_true",
                   help="Print version and exit")

    sub = p.add_subparsers(dest="cmd")

    # check
    c = sub.add_parser("check", help="Validate a design (exit 1 if errors)")
    c.add_argument("design", help="Path to design JSON file")
    c.add_argument("--verbose", "-v", action="store_true",
                   help="Show full design details after validation (replaces old 'show')")
    c.add_argument("--json", action="store_true", dest="json_output",
                   help="Output categorized check results as JSON")

    # run
    r = sub.add_parser("run", help="Check, compile, and execute a design")
    r.add_argument("design", help="Path to design JSON file")
    r.add_argument("--site", help="Override site directory")
    r.add_argument("--model", help="LLM model for oracle rules",
                   default="anthropic/claude-haiku-4-5-20251001")
    r.add_argument("--stub", action="store_true",
                   help="Use stub oracle (no LLM, placeholder outputs)")
    r.add_argument("--hy", action="store_true",
                   help="Use original Hy kernel backend instead of Python")
    r.add_argument("--json", action="store_true", dest="json_output",
                   help="Output full Report as JSON instead of text")
    r.add_argument("--soft-fail", action="store_true",
                   help="Exit 0 even when the build halts")
    r.add_argument("--verbose", "-v", action="store_true",
                   help="Verbose output (full trace + detailed report)")

    # status
    st_cmd = sub.add_parser("status", help="Show freshness state of a built site")
    st_cmd.add_argument("design", nargs="?", default=None,
                        help="Path to design JSON file (optional)")
    st_cmd.add_argument("--site", help="Site directory")
    st_cmd.add_argument("--json", action="store_true", dest="json_output",
                        help="Output as JSON")
    st_cmd.add_argument("--fail-if-dirty", action="store_true",
                        help="Exit 4 if any artifact is modified")
    st_cmd.add_argument("--fail-if-stale", action="store_true",
                        help="Exit 4 if any rule is stale")

    # diff
    d = sub.add_parser("diff", help="Show differences between sealed and current artifacts")
    d.add_argument("design", nargs="?", default=None,
                   help="Path to design JSON file (optional)")
    d.add_argument("artifact", nargs="*", default=[],
                   help="Specific artifacts to diff (default: all)")
    d.add_argument("--site", help="Site directory")
    d.add_argument("--json", action="store_true", dest="json_output",
                   help="Output as JSON")

    # explain
    e = sub.add_parser("explain", help="Explain a rule or artifact")
    e.add_argument("subject", help="Rule name or artifact path")
    e.add_argument("--site", help="Site directory (required)")
    e.add_argument("--json", action="store_true", dest="json_output",
                   help="Output as JSON")

    # graph
    g = sub.add_parser("graph", help="Render the dependency graph")
    g.add_argument("design", help="Path to design JSON file")
    g.add_argument("--format", choices=["text", "mermaid", "dot", "json"],
                   default="text", dest="graph_format",
                   help="Output format (default: text)")
    g.add_argument("--site", help="Site directory (for freshness overlay)")

    # history
    h = sub.add_parser("history", help="Show convergence history for rules")
    h.add_argument("design", help="Path to design JSON file")
    h.add_argument("rule", nargs="?", default=None,
                   help="Rule name (omit for summary of all rules)")
    h.add_argument("--site", help="Override site directory")
    h.add_argument("-n", type=int, default=5,
                   help="Number of recent entries to show (default: 5)")

    # gate
    gt = sub.add_parser("gate", help="Run the conformance gate against a CSE reader")
    gt.add_argument("reader_cmd", help='Reader command, e.g. "python my_reader.py"')
    gt.add_argument("--stamp-dir", default=None,
                    help="Write VERIFIED stamp here on pass")
    gt.add_argument("--no-cross-check", action="store_false", dest="cross_check",
                    help="Disable JS cross-check")
    gt.add_argument("--json", action="store_true", dest="json_output",
                    help="Output as JSON")
    gt.add_argument("--verbose", "-v", action="store_true",
                    help="Verbose output")

    # doctor
    doc = sub.add_parser("doctor", help="Check environment and dependencies")
    doc.add_argument("--json", action="store_true", dest="json_output",
                     help="Output as JSON")

    # selftest
    st = sub.add_parser("selftest", help="Verify engine against frozen conformance vectors")
    st.add_argument("--conformance", help="Path to conformance vector directory")

    # init
    i = sub.add_parser("init", help="Wire a project to drive Husks from Claude Code")
    i.add_argument("target", nargs="?", default=".",
                   help="Target directory (default: .)")
    i.add_argument("--no-claude-code", action="store_true",
                   help="Skip Claude Code skill hookup")
    i.add_argument("--force", action="store_true",
                   help="Overwrite existing skill symlink and CLAUDE.md")

    args = p.parse_args()

    # --version
    if args.version:
        try:
            from importlib.metadata import version as pkg_version
            print(f"husks {pkg_version('husks')}")
        except Exception:
            print("husks (version unknown)")
        sys.exit(EXIT_OK)

    if args.cmd is None:
        p.print_help()
        sys.exit(EXIT_USAGE)

    # ── Commands that take no design file ─────────────────────
    if args.cmd == "selftest":
        from husks.setup import selftest
        sys.exit(EXIT_OK if selftest(conformance=args.conformance) else EXIT_BUILD_FAIL)

    if args.cmd == "init":
        from husks.setup import init
        sys.exit(init(args.target, claude_code=not args.no_claude_code, force=args.force))

    if args.cmd == "doctor":
        _cmd_doctor(args)
        return

    if args.cmd == "gate":
        _cmd_gate(args)
        return

    # ── Commands that may or may not need a design ────────────
    if args.cmd == "status":
        _cmd_status(args)
        return

    if args.cmd == "diff":
        _cmd_diff(args)
        return

    if args.cmd == "explain":
        _cmd_explain(args)
        return

    # ── Commands that require a design ────────────────────────
    design = from_json(args.design)

    if args.cmd == "check":
        _cmd_check(args, design)

    elif args.cmd == "run":
        _cmd_run(args, design)

    elif args.cmd == "graph":
        _cmd_graph(args, design)

    elif args.cmd == "history":
        _cmd_history(args, design)


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
    from husks.oracle.llm import get_usage

    report = assemble(S, T, design, get_usage())
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
    from husks.manifest import (
        resolve_manifest, read_seal, compute_rule_state, compute_artifact_states,
    )

    manifest, site = resolve_manifest(
        getattr(args, "design", None), args.site
    )
    if not site:
        print("error: no site directory. Use --site or provide a design with 'site' key.",
              file=sys.stderr)
        sys.exit(EXIT_USAGE)
    if not manifest:
        print(f"error: no build manifest in {site}/.traces/", file=sys.stderr)
        sys.exit(EXIT_BUILD_FAIL)

    # Compute rule states
    rule_states: list[dict] = []
    for rule in manifest.get("rules", []):
        seal = read_seal(site, rule["name"])
        state, reason = compute_rule_state(site, rule, seal)
        rule_states.append({
            "name": rule["name"],
            "kind": rule["kind"],
            "state": state,
            "reason": reason,
        })

    # Compute artifact states
    artifact_states = compute_artifact_states(site, manifest)

    if args.json_output:
        print(json.dumps({
            "site": site,
            "root": manifest.get("root"),
            "rules": rule_states,
            "artifacts": artifact_states,
        }, indent=2))
    else:
        print(f"\n  site: {site}")
        root = manifest.get("root", "none") or "none"
        print(f"  root: {root[:16]}...")
        print(f"  {'─' * 50}")

        _sym = {"fresh": "\u2713", "stale": "\u25b8", "missing": "\u2717",
                "dirty": "!", "modified": "!"}

        print("\n  rules:")
        for rs in rule_states:
            sym = _sym.get(rs["state"], "?")
            reason = f"  ({rs['reason']})" if rs["reason"] else ""
            print(f"    {sym} {rs['name']:<20s} {rs['state']}{reason}")

        print("\n  artifacts:")
        for a in artifact_states:
            sym = _sym.get(a["state"], "?")
            print(f"    {sym} {a['path']:<24s} {a['state']}")

        print(f"  {'─' * 50}\n")

    # Exit code checks
    if args.fail_if_dirty:
        if any(a["state"] == "modified" for a in artifact_states):
            sys.exit(EXIT_DIRTY_STALE)
    if args.fail_if_stale:
        if any(rs["state"] in ("stale", "missing") for rs in rule_states):
            sys.exit(EXIT_DIRTY_STALE)


# ── diff ──────────────────────────────────────────────────────────

def _cmd_diff(args):
    from husks.manifest import resolve_manifest, compute_artifact_states

    manifest, site = resolve_manifest(
        getattr(args, "design", None), args.site
    )
    if not site:
        print("error: no site directory. Use --site or provide a design.",
              file=sys.stderr)
        sys.exit(EXIT_USAGE)
    if not manifest:
        print(f"error: no build manifest in {site}/.traces/", file=sys.stderr)
        sys.exit(EXIT_BUILD_FAIL)

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


# ── explain ───────────────────────────────────────────────────────

def _cmd_explain(args):
    from husks.manifest import (
        read_manifest, read_seal, read_trial_report, compute_rule_state, file_hash,
    )

    site = args.site
    if not site:
        print("error: --site is required for explain", file=sys.stderr)
        sys.exit(EXIT_USAGE)

    manifest = read_manifest(site)
    if not manifest:
        print(f"error: no build manifest in {site}/.traces/", file=sys.stderr)
        sys.exit(EXIT_BUILD_FAIL)

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
        sealed_hash = seal.get("outputs", {}).get(subject) if seal else None
        current = file_hash(str(Path(site) / subject))
        state, _ = compute_rule_state(site, rule, seal)

        info = {
            "type": "artifact",
            "path": subject,
            "producing_rule": rule["name"],
            "rule_kind": rule["kind"],
            "state": state,
            "sealed_hash": sealed_hash,
            "current_hash": current,
            "modified": sealed_hash != current if sealed_hash and current else None,
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


# ── graph ─────────────────────────────────────────────────────────

def _cmd_graph(args, design):
    from husks.graph import render_graph
    print(render_graph(design, fmt=args.graph_format, site=args.site))


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


# ── gate ──────────────────────────────────────────────────────────

def _cmd_gate(args):
    from husks.gate import gate

    reader = args.reader_cmd.split()
    cross_check = getattr(args, "cross_check", True)
    verbose = args.verbose if not args.json_output else False

    ok = gate(reader, stamp_dir=args.stamp_dir, cross_check=cross_check,
              verbose=verbose)

    if args.json_output:
        print(json.dumps({"pass": ok}))

    sys.exit(EXIT_OK if ok else EXIT_BUILD_FAIL)


# ── doctor ────────────────────────────────────────────────────────

def _cmd_doctor(args):
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
    import os
    key = os.environ.get("ANTHROPIC_API_KEY", "")
    if key:
        checks.append({"name": "ANTHROPIC_API_KEY", "ok": True,
                        "detail": f"set ({key[:4]}...)"})
    else:
        checks.append({"name": "ANTHROPIC_API_KEY", "ok": None,
                        "detail": "not set (needed for live runs)"})

    # 7. git
    import shutil
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


if __name__ == "__main__":
    main()
