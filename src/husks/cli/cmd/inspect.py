"""All _cmd_* command functions."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from husks.designs.ir import from_json
from husks.designs.convergence import read_history, convergence_summary
from husks.utils.console import _shorthash
from husks.cli.helpers import _load_manifest, _STATE_SYM, resolve_design, EXIT_OK, EXIT_USAGE, EXIT_DIRTY_STALE, EXIT_BUILD_FAIL
from husks.cli.residue import CliResidue, CliNode, map_manifest_state


# ── Residue collectors (Beta Gate 95) ────────────────────────────────

def collect_site_residue(manifest: dict, site: str) -> CliResidue:
    """Collect site residue for status command.

    Maps manifest freshness states to unified CLI state vocabulary.
    Builds target-rooted tree.

    Beta 100: Adds cse_path, target, and output records.
    Blocker #7: Check history for cache evidence to distinguish sealed vs cached.
    """
    from husks.manifest import compute_rule_states
    from husks.cli.residue import CliOutput
    import os

    rule_states = compute_rule_states(site, manifest)
    rules = manifest.get("rules", [])
    rules_by_name = {r["name"]: r for r in rules}

    # Build dependency map
    deps = {}
    for rule in rules:
        rule_inputs = set(rule.get("inputs", []))
        deps[rule["name"]] = []
        for other in rules:
            other_outputs = set(other.get("outputs", []))
            if rule_inputs & other_outputs:
                deps[rule["name"]].append(other["name"])

    nodes = []
    for rs in rule_states:
        rule_name = rs["name"]
        rule = rules_by_name.get(rule_name, {})

        # Blocker #7: Check history for cache evidence
        history = read_history(site, rule_name)
        was_cached = False
        trace_metadata = None
        if history:
            last_run = history[-1]
            was_cached = last_run.get("cached", False)
            # Phase 3: Extract trace metadata from history
            trace_metadata = last_run

        # Map manifest state to CLI state
        # If fresh and was cached in last run, show as cached instead of sealed
        manifest_state = rs["state"]
        if manifest_state == "fresh" and was_cached:
            state = "cached"
        else:
            state = map_manifest_state(manifest_state)

        # Beta 100: Collect outputs with hashes for sealed nodes
        outputs = []
        for output_path in rule.get("outputs", []):
            full_path = os.path.join(site, output_path)
            output_hash = None
            if os.path.isfile(full_path):
                import hashlib
                with open(full_path, 'rb') as f:
                    output_hash = hashlib.sha256(f.read()).hexdigest()
            outputs.append(CliOutput(path=output_path, sha256=output_hash))

        # Phase 3: Read seal data for aperture 2
        from husks.manifest import read_seal
        seal = read_seal(site, rule_name)
        seal_digest = None
        recipe_digest = None
        input_hashes = None
        output_hashes = None
        if seal:
            seal_digest = seal.get("digest")
            recipe_digest = seal.get("recipe_digest")
            input_hashes = seal.get("input_hashes", {})
            output_hashes = seal.get("output_hashes", {})

        # Phase 3: Build trace for aperture 3
        from husks.cli.residue import CliTrace
        trace = None
        if trace_metadata:
            trace = CliTrace(
                backend=trace_metadata.get("backend"),
                model=trace_metadata.get("model"),
                config_hash=trace_metadata.get("config_hash"),
                prompt_hash=trace_metadata.get("prompt_hash"),
                input_tokens=trace_metadata.get("tokens_in", 0),
                output_tokens=trace_metadata.get("tokens_out", 0),
                elapsed_s=trace_metadata.get("elapsed_s"),
                cost_usd=trace_metadata.get("cost_usd", 0.0),
                stdout=trace_metadata.get("stdout"),
                stderr=trace_metadata.get("stderr"),
                cache_source="local" if was_cached else None,
            )

        node = CliNode(
            name=rs["name"],
            kind=rule.get("kind", "action"),
            state=state,
            children=deps.get(rs["name"], []),
            fuel_budget=rule.get("fuel"),
            stale_reason=rs.get("reason"),
            outputs=outputs,
            seal_digest=seal_digest,
            recipe_digest=recipe_digest,
            input_hashes=input_hashes,
            output_hashes=output_hashes,
            trace=trace,
        )
        nodes.append(node)

    # Reorder: target first
    target = manifest.get("target")
    if target:
        target_idx = next((i for i, n in enumerate(nodes) if n.name == target), 0)
        if target_idx > 0:
            nodes.insert(0, nodes.pop(target_idx))

    # Compute summary categories
    has_stale = any(n.state == "stale" for n in nodes)

    passes = ["site"] if not has_stale else []
    fails = ["site"] if has_stale else []

    # Beta 100: Add cse_path and target
    design_name = manifest.get("name", "unknown")
    cse_path = f"{design_name}.husk"
    target_name = manifest.get("target")

    return CliResidue(
        command="status",
        design_name=design_name,
        site=site,
        cse_path=cse_path,
        status="committed" if manifest.get("root") else "dry",
        root=manifest.get("root"),
        target=target_name,
        nodes=nodes,
        passes=passes,
        fails=fails,
    )


# ── status ────────────────────────────────────────────────────────────

def _cmd_status(args):
    """Status command - show site conformance state.

    Beta Gate 95: Uses residue→surface→view architecture.
    """
    from husks.manifest import compute_artifact_states
    from husks.cli.surface import emit_residue

    # Step 1: Load manifest and site (keep existing logic)
    manifest, site = _load_manifest(args)

    # Step 2: Collect site residue
    residue = collect_site_residue(manifest, site)

    # Step 3: Emit via surface layer
    verbose = getattr(args, 'verbose', False)
    output = emit_residue(residue, json_mode=args.json_output, verbose=verbose)
    print(output)

    # Step 4: Preserve exit code logic
    if args.fail_if_dirty:
        artifact_states = compute_artifact_states(site, manifest)
        if any(a["state"] == "modified" for a in artifact_states):
            sys.exit(EXIT_DIRTY_STALE)

    if args.fail_if_stale:
        if len(residue.fails) > 0:  # Any stale or failed nodes
            sys.exit(EXIT_DIRTY_STALE)


# ── explain ───────────────────────────────────────────────────────

def _read_key():
    """Read a single keypress without blocking (Phase 6 task #40).

    Returns:
        str: Key name ('up', 'down', 'left', 'right', 'q', or raw char)
    """
    import sys
    import tty
    import termios

    fd = sys.stdin.fileno()
    old_settings = termios.tcgetattr(fd)
    try:
        tty.setraw(fd)
        ch = sys.stdin.read(1)

        # Handle escape sequences (arrow keys)
        if ch == '\x1b':
            ch2 = sys.stdin.read(1)
            if ch2 == '[':
                ch3 = sys.stdin.read(1)
                if ch3 == 'A':
                    return 'up'
                elif ch3 == 'B':
                    return 'down'
                elif ch3 == 'C':
                    return 'right'
                elif ch3 == 'D':
                    return 'left'

        # Handle ctrl+c
        if ch == '\x03':
            raise KeyboardInterrupt

        return ch
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)


def _run_interactive_pilot(state):
    """Run interactive pilot loop (Phase 6 task #41).

    Continuously renders state, reads keyboard input, updates state,
    and re-renders until user quits.

    Controls:
        ↑/↓: Move cursor up/down through nodes
        ←/→: Decrease/increase aperture
        q: Quit
    """
    from husks.cli.navigator import move_cursor, adjust_aperture
    from husks.cli.view import render_dag
    import sys

    # Clear screen and hide cursor
    print('\033[2J\033[H', end='', flush=True)
    print('\033[?25l', end='', flush=True)  # Hide cursor

    try:
        while True:
            # Render current state (task #42)
            output = render_dag(
                state.residue,
                verbose=False,
                cursor=state.cursor,
                aperture=state.aperture,
                controls=True
            )

            # Clear and redraw
            print('\033[H', end='')  # Move to top
            print(output, flush=True)

            # Read keyboard input
            try:
                key = _read_key()
            except KeyboardInterrupt:
                break

            # Update state based on key
            if key == 'q':
                break
            elif key == 'up':
                state = move_cursor(state, 'up')
            elif key == 'down':
                state = move_cursor(state, 'down')
            elif key == 'left':
                state = adjust_aperture(state, -1)
            elif key == 'right':
                state = adjust_aperture(state, +1)
    finally:
        # Show cursor and clear screen
        print('\033[?25h', end='', flush=True)  # Show cursor
        print('\033[2J\033[H', end='', flush=True)  # Clear screen


def _explain_navigate(args):
    """Navigate site residue tree (Phase 5+6).

    Loads site manifest, builds residue, creates ExplainState,
    and renders with cursor/aperture. No design.json required.

    Phase 6: Interactive mode when --interactive and in a TTY.
    """
    from husks.manifest import read_manifest
    from husks.cli.navigator import create_explain_state
    from husks.cli.view import render_dag
    from husks.cli.surface import emit_residue
    import sys

    site = args.site

    # Phase 5: Infer CSE from site manifest (task #36)
    try:
        manifest = read_manifest(site)
        if not manifest:
            print(f"error: no manifest found in {site}", file=sys.stderr)
            sys.exit(EXIT_USAGE)
    except Exception as e:
        print(f"error: failed to read manifest from {site}: {e}", file=sys.stderr)
        sys.exit(EXIT_USAGE)

    # Build site residue (same as status command)
    residue = collect_site_residue(manifest, site)

    # Create navigation state
    cursor_node = args.node  # None uses target as default
    aperture_level = args.aperture
    state = create_explain_state(residue, cursor=cursor_node, aperture=aperture_level)

    # Phase 5: JSON output (task #37)
    if args.json_output:
        output = emit_residue(state.residue, json_mode=True, verbose=False)
        # Add explain metadata
        import json
        data = json.loads(output)
        data["cursor"] = state.cursor
        data["aperture"] = state.aperture
        data["order"] = state.order
        print(json.dumps(data, indent=2))
        return

    # Phase 6: TTY detection (task #39)
    is_tty = sys.stdout.isatty()
    interactive_requested = getattr(args, 'interactive', False)

    if is_tty and interactive_requested:
        # Phase 6: Interactive pilot loop (task #41)
        _run_interactive_pilot(state)
    else:
        # Deterministic single-frame render
        output = render_dag(
            state.residue,
            verbose=False,
            cursor=state.cursor,
            aperture=state.aperture,
            controls=interactive_requested  # Show controls if interactive was requested
        )
        print(output)


def _cmd_explain(args):
    """Dispatch to the appropriate explain mode.

    Phase 5: --site mode routes to navigator (deterministic explain)
    Legacy modes: --diff, --seal, subject path
    """
    # Phase 5: Navigator mode when --site is provided without legacy flags
    is_legacy_mode = args.diff or args.seal or (args.subject and not args.site)
    if args.site and not is_legacy_mode:
        _explain_navigate(args)
        return

    # Legacy modes
    if args.diff:
        _explain_diff(args)          # legacy
    elif args.seal:
        _explain_seal(args)          # legacy
    elif args.subject:
        subject = args.subject
        if subject.endswith(('.json', '.hy')):
            args.design = subject
            _explain_graph(args)
        else:
            _explain_subject(args)   # legacy
    else:
        _explain_graph(args)


def _explain_graph(args):
    """Render the bordered DAG tree (primary explain output)."""
    from husks.graph import render_graph
    from husks.manifest import read_manifest

    design_path = resolve_design(args)
    design = from_json(design_path)

    # Extract root hash from manifest when a site is provided
    root_hash = None
    site = getattr(args, "site", None) or design.get("site")
    if site:
        try:
            manifest = read_manifest(site)
            if manifest:
                root_hash = manifest.get("root")
        except Exception:
            pass

    print(render_graph(
        design,
        fmt=args.graph_format,
        site=site,
        root_hash=root_hash,
    ))


# ── legacy ───────────────────────────────────────────────────────
# These modes are kept for backwards compatibility but are clearly
# separated from the primary bordered-tree explain output above.

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


def _explain_diff(args):
    """Show differences between sealed and current artifacts."""
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
