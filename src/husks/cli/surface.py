"""
CLI Surface layer - owns all "what to show" decisions.

The surface layer takes CliResidue (shared intermediate representation)
and decides which sections to render, what data to pass to the view,
and which entry point to use:

- ``emit_residue()`` — check/run/status command output (JSON or visual)
- ``emit_explain()`` — explain mode with cursor/aperture navigation
- ``emit_help()`` — top-level ``husks --help`` output
- ``emit_subcommand_help()`` — per-subcommand ``--help`` output
- ``emit_init()`` — ``husks init`` output

"What to show" lives here.  "How to show it" lives in view.py.
cmd/ just collects data.
"""

from __future__ import annotations
import json
from husks.cli.residue import CliResidue, CliNode, map_display_status
from husks.cli.view import (
    render_output, render_preamble, render_motif_tree,
    render_footer, render_explain_mode,
    _format_tokens, _rpad, R,
)
from husks.utils.console import (
    GREEN, YELLOW, RED, CYAN, DIM, BOLD, RESET,
    _visible_len, render_banner, cursor_up, CLEAR_DOWN, _IS_TTY,
)


# -- Constants ----------------------------------------------------------------

STAGE_MAP = {
    "check": "design",
    "run": "build",
    "status": "status",
}


# -- Primary entry point: residue dispatch ------------------------------------

def emit_residue(
    residue: CliResidue,
    *,
    json_mode: bool = False,
    verbose: bool = False,
    quiet: bool = False,
    log_lines: dict[str, list[str]] | None = None,
) -> str:
    """Dispatch residue to JSON or visual output.

    **Beta Gate 95**: Enforces mutual exclusivity of --verbose and --json.

    Parameters
    ----------
    residue : CliResidue
        Shared intermediate representation from command
    json_mode : bool
        Output as pure JSON (no ANSI codes, machine-readable)
    verbose : bool
        Output in verbose visual mode (ignored if json_mode=True)
    quiet : bool
        Suppress all output (returns empty string)
    log_lines : dict, optional
        Per-node live log lines from LiveFrameEmitter.

    Returns
    -------
    str
        Formatted output string

    Raises
    ------
    ValueError
        If both json_mode and verbose are True (mutually exclusive)
    """
    if quiet:
        return ""

    if json_mode and verbose:
        raise ValueError("--verbose and --json are mutually exclusive")

    if json_mode:
        return _emit_json(residue)
    else:
        return _emit_visual(residue, verbose=verbose, log_lines=log_lines)


# -- Explain entry point ------------------------------------------------------

def emit_explain(
    residue: CliResidue,
    *,
    cursor: str,
    aperture: int = 1,
    controls: bool = False,
) -> str:
    """Render explain mode with cursor/aperture navigation."""
    return render_explain_mode(
        residue, cursor=cursor, aperture=aperture, controls=controls,
    )


# -- Help entry points --------------------------------------------------------

def emit_help(version: str, *, animate: bool = False) -> str | None:
    """Render top-level ``husks --help`` output.

    If *animate* is True and stdout is a TTY, plays a brief diamond
    crystallisation sequence (dry → hydrating → sealed) before
    settling on the final frame.  Returns None in this case (output
    is written directly).
    """
    if animate and _IS_TTY:
        _animate_help(version)
        return None

    # -- Preamble: diamond banner (white, static) --
    preamble = render_banner("white", [
        f"{BOLD}husks{RESET} {DIM}{version}{RESET}",
        f"{DIM}A small build system for nondeterministic work.{RESET}",
        "",
        "",
        "",
    ])

    # -- Trace: command group listings --
    def _group(name: str) -> str:
        return f"\n  {BOLD}{name}{RESET}"

    def _cmd(name: str, desc: str) -> str:
        return f"    {name:<18s}{DIM}{desc}{RESET}"

    trace = [
        _group("design"),
        _cmd("init", "Scaffold a new project"),
        _cmd("doctor", "Diagnose the local environment"),
        _cmd("check", "Validate a design"),
        _group("build"),
        _cmd("run", "Execute a design into a site"),
        _cmd("status", "Inspect site state"),
        _cmd("cache export", "Export site cache for transfer"),
        _cmd("cache import", "Import cache into a site"),
        _group("verify"),
        _cmd("verify", "Recompute .husk root hash in a site"),
        _cmd("compare", "Equivalence across sites (three-machine proof with 3+)"),
        _group("inspect"),
        _cmd("explain", "Navigate the residue tree"),
        _cmd("history", "Show convergence across runs"),
        "",
        f"  {DIM}--color <mode>   auto \u00b7 always \u00b7 never{RESET}",
        f"  {DIM}-q, --quiet      Suppress output{RESET}",
        f"  {DIM}--version        Print version{RESET}",
    ]

    # -- Footer: help hint + exit codes --
    footer_lines = [
        f"  {DIM}husks <command> --help for details{RESET}",
        "",
        f"  {BOLD}Exit codes{RESET}",
        f"    {DIM}0  Success - build committed or command succeeded{RESET}",
        f"    {DIM}1  Build failed - halted, missing deps, or error{RESET}",
        f"    {DIM}2  Usage error - invalid arguments or options{RESET}",
        f"    {DIM}3  Missing dependency - LLM backend unavailable{RESET}",
        f"    {DIM}4  Status check - artifacts are dirty or stale{RESET}",
        f"    {DIM}5  Internal error - unexpected failure{RESET}",
    ]

    return render_output(
        preamble=preamble,
        trace=trace,
        footer="\n".join(footer_lines),
    )


def _animate_help(version: str) -> None:
    """Play the diamond crystallisation animation on a TTY.

    Character-level progressive typing:
    1. Dry diamond types in character by character
    2. Hydrating pulse (frame swap)
    3. Sealed snap → body types in: category headers char-by-char,
       command names char-by-char, descriptions word-by-word
    """
    import sys
    from time import sleep

    # -- Segment-based printer (à la pprint) ───────────────────
    def _pp(segments: list[dict]) -> None:
        """Print a list of {str, color, end, t} segments."""
        for seg in segments:
            s = seg.get("str", "")
            color = seg.get("color", "")
            end = seg.get("end", "")
            t = seg.get("t", 0)
            if color:
                print(f"{color}{s}{RESET}", end=end, flush=True)
            else:
                print(s, end=end, flush=True)
            if t > 0:
                sleep(t)

    def _type_chars(text: str, color: str = "", t: float = 0.03) -> list[dict]:
        """Build segments for character-by-character typing."""
        return [{"str": ch, "color": color, "t": t} for ch in text]

    def _type_words(text: str, color: str = "", t: float = 0.03) -> list[dict]:
        """Build segments for word-by-word typing."""
        words = text.split(" ")
        segs = []
        for i, word in enumerate(words):
            prefix = " " if i > 0 else ""
            segs.append({"str": prefix + word, "color": color, "t": t})
        return segs

    right_info = [
        f"{BOLD}husks{RESET} {DIM}{version}{RESET}",
        f"{DIM}A small build system for nondeterministic work.{RESET}",
        "",
        "",
        "",
    ]

    # -- Phase 1: dry diamond (char by char) ───────────────────
    banner = render_banner("dry", right_info)
    rows = banner.count("\n") + 1
    for line in banner.split("\n"):
        _pp([{"str": line, "t": 0.06, "end": "\n"}])
    sleep(0.3)

    # -- Phase 2: hydrating (pulse) ────────────────────────────
    for stage, hold in [("hydrating", 0.2), ("dry", 0.12), ("hydrating", 0.15)]:
        sys.stdout.write(cursor_up(rows) + CLEAR_DOWN)
        b = render_banner(stage, right_info)
        print(b, flush=True)
        sleep(hold)

    # -- Phase 3: sealed snap → body types in ──────────────────
    sys.stdout.write(cursor_up(rows) + CLEAR_DOWN)
    print(render_banner("sealed", right_info), flush=True)
    sleep(0.15)

    col = 18
    groups = [
        ("design", [
            ("init", "Scaffold a new project"),
            ("doctor", "Diagnose the local environment"),
            ("check", "Validate a design"),
        ]),
        ("build", [
            ("run", "Execute a design into a site"),
            ("status", "Inspect site state"),
            ("cache export", "Export site cache for transfer"),
            ("cache import", "Import cache into a site"),
        ]),
        ("verify", [
            ("verify", "Recompute .husk root hash in a site"),
            ("compare", "Equivalence across sites (three-machine proof with 3+)"),
        ]),
        ("inspect", [
            ("explain", "Navigate the residue tree"),
            ("history", "Show convergence across runs"),
        ]),
    ]

    for group_name, cmds in groups:
        # Blank line before category
        print(flush=True)
        # Category header: char by char, bold
        _pp([{"str": "  "}])
        _pp(_type_chars(group_name, color=BOLD, t=0.04))
        _pp([{"str": "", "end": "\n", "t": 0.15}])

        for name, desc in cmds:
            # Indent
            _pp([{"str": "    "}])
            # Command name: char by char
            _pp(_type_chars(name, t=0.03))
            # Pad to column
            pad = max(1, col - len(name))
            _pp([{"str": " " * pad, "t": 0.04}])
            # Description: word by word, dim
            _pp(_type_words(desc, color=DIM, t=0.025))
            _pp([{"str": "", "end": "\n", "t": 0.03}])

    # Trailing options: word by word
    print(flush=True)
    sleep(0.08)
    for opt in [
        ("--color <mode>", "auto \u00b7 always \u00b7 never"),
        ("-q, --quiet", "Suppress output"),
        ("--version", "Print version"),
    ]:
        _pp([{"str": "  "}])
        _pp(_type_chars(opt[0], color=DIM, t=0.015))
        pad = max(1, 17 - len(opt[0]))
        _pp([{"str": " " * pad}])
        _pp(_type_words(opt[1], color=DIM, t=0.02))
        _pp([{"str": "", "end": "\n", "t": 0.02}])

    # Footer divider
    hline = '\u2500' * (R - 2)
    _pp([{"str": f"  {DIM}{hline}{RESET}", "end": "\n", "t": 0.1}])

    # Footer: fast, line by line
    footer = [
        f"  {DIM}husks <command> --help for details{RESET}",
        "",
        f"  {BOLD}Exit codes{RESET}",
        f"    {DIM}0  Success - build committed or command succeeded{RESET}",
        f"    {DIM}1  Build failed - halted, missing deps, or error{RESET}",
        f"    {DIM}2  Usage error - invalid arguments or options{RESET}",
        f"    {DIM}3  Missing dependency - LLM backend unavailable{RESET}",
        f"    {DIM}4  Status check - artifacts are dirty or stale{RESET}",
        f"    {DIM}5  Internal error - unexpected failure{RESET}",
    ]
    for line in footer:
        _pp([{"str": line, "end": "\n", "t": 0.025}])


def emit_subcommand_help(parser) -> str:
    """Render branded help for a subcommand parser."""
    import argparse
    from husks.cli.main import _flag_str, _StyledHelpAction, _NO_VALUE_ACTIONS

    desc = parser.description or ""

    positionals = []
    optionals = []
    subcommands = []

    for action in parser._actions:
        if action.help == argparse.SUPPRESS:
            continue
        if isinstance(action, _StyledHelpAction):
            continue
        if isinstance(action, argparse._SubParsersAction):
            for ca in action._choices_actions:
                subcommands.append((ca.metavar, ca.help or ""))
            continue
        if action.option_strings:
            optionals.append(action)
        else:
            positionals.append(action)

    # Compute column width from all left-column entries
    all_lefts = [_flag_str(a) for a in positionals + optionals]
    all_lefts += [name for name, _ in subcommands]
    col = max((len(s) for s in all_lefts), default=14) + 2
    col = max(col, 18)

    # -- Trace: command name + description + arguments/options --
    trace = [
        f"  {BOLD}{parser.prog}{RESET}",
        f"  {DIM}{desc}{RESET}",
    ]

    if positionals:
        trace.append(f"\n  {BOLD}arguments{RESET}")
        for action in positionals:
            fs = _flag_str(action)
            trace.append(f"    {fs:<{col}}{DIM}{action.help or ''}{RESET}")

    if optionals:
        trace.append(f"\n  {BOLD}options{RESET}")
        for action in optionals:
            fs = _flag_str(action)
            trace.append(f"    {fs:<{col}}{DIM}{action.help or ''}{RESET}")

    if subcommands:
        trace.append(f"\n  {BOLD}commands{RESET}")
        for name, help_text in subcommands:
            trace.append(f"    {name:<{col}}{DIM}{help_text}{RESET}")

    trace.append("")

    # -- Footer: usage line --
    usage_parts = [parser.prog]
    if subcommands:
        usage_parts.append("<command>")
    if optionals:
        usage_parts.append("[options]")
    for action in positionals:
        name = action.metavar or action.dest
        if action.nargs in ("?", "*"):
            usage_parts.append(f"[{name}]")
        elif action.nargs == "+":
            usage_parts.append(f"<{name}> [...]")
        else:
            usage_parts.append(f"<{name}>")

    footer = f"  {DIM}{' '.join(usage_parts)}{RESET}"

    return render_output(trace=trace, footer=footer)


# -- Init entry point ---------------------------------------------------------

def emit_init(
    steps: list[tuple[str, str]],
    design_file: str,
    target,
    *,
    verbose: bool = True,
) -> str:
    """Render init output using the three-section architecture.

    Parameters
    ----------
    steps : list of (name, state) tuples
        Init step results. state is "sealed", "failed", or "stale".
    design_file : str
        Name of the design file created.
    target : Path-like
        Target directory.
    verbose : bool
        Whether to show the hydration-style tree.
    """
    import os

    # Build CliNode objects for each init step
    nodes = []
    child_names = [name for name, _ in steps]
    # Root node: "init" with all steps as children
    root = CliNode(
        name="init",
        kind="action",
        state="sealed" if all(s != "failed" for _, s in steps) else "failed",
        children=child_names,
    )
    nodes.append(root)
    for name, state in steps:
        nodes.append(CliNode(name=name, kind="action", state=state))

    # Trace: hydration-style tree
    trace = render_motif_tree(nodes, verbose=False) if verbose else None

    # Footer: next steps
    rel = os.path.relpath(target)
    footer_lines = [
        f"  {DIM}cd {rel}{RESET}",
        f"  {DIM}husks check {design_file} --verbose{RESET}",
        f"  {DIM}husks run {design_file} --site m1 --stub{RESET}",
    ]
    footer = "\n".join(footer_lines)

    return render_output(trace=trace, footer=footer)


# -- Private: visual composition ----------------------------------------------

def _emit_visual(
    residue: CliResidue,
    *,
    verbose: bool = False,
    log_lines: dict[str, list[str]] | None = None,
) -> str:
    """Compose visual output from residue.

    Decides: preamble data, which sections to include, footer content.
    Calls view renderers with explicit data.
    """
    display_status = map_display_status(residue.status, residue.command)
    diamond_stage = _diamond_stage(residue)
    stage_label = STAGE_MAP.get(residue.command, residue.command)

    # Status command: append run count next to state
    status_suffix = ""
    if residue.command == "status" and residue.run_count > 0:
        n = residue.run_count
        status_suffix = f" {DIM}\u00b7 {n} run{'s' if n != 1 else ''}{RESET}"

    # Show the prior hydrating state as a ghost banner when a build failed —
    # the disconnected diamond records the state that was attempted.
    prior = "hydrating" if display_status == "failed" and residue.command == "run" else None

    preamble = render_preamble(
        design_name=residue.design_name,
        display_status=display_status,
        diamond_stage=diamond_stage,
        husk_hash=residue.husk_hash,
        root=residue.root,
        site=residue.site,
        stage_label=stage_label,
        fuel_budget=residue.fuel_budget,
        prior_stage=prior,
        status_suffix=status_suffix,
    )

    left = _footer_left(residue)
    right = _footer_right(residue)
    footer = render_footer(left_text=left, right_text=right)

    # Status without --verbose: logo + footer only (no tree)
    if residue.command == "status" and not verbose:
        return render_output(preamble=preamble, footer=footer)

    trace = render_motif_tree(
        residue.nodes, verbose=verbose, log_lines=log_lines,
    )

    return render_output(preamble=preamble, trace=trace, footer=footer)


# -- Private: command-aware helpers (moved from view.py) ----------------------

def _diamond_stage(residue: CliResidue) -> str:
    """Map residue to diamond animation stage."""
    if residue.status == "dry" or residue.command == "check":
        return "dry"
    if residue.status == "hydrating":
        return "hydrating"
    if residue.status == "halted":
        return "failed"
    return "sealed"


def _footer_left(residue: CliResidue) -> str:
    """Build the left-side state summary for the footer."""
    has_fails = (
        residue.fails and len(residue.fails) > 0
        if isinstance(residue.fails, list)
        else residue.fails > 0
    )

    if residue.command == "check":
        if has_fails:
            # Check found errors — show what failed
            fail_items = residue.fails if isinstance(residue.fails, list) else []
            return f"failures in {', '.join(fail_items)}" if fail_items else "failed"
        return "dry"

    if residue.command == "run":
        if residue.status == "committed":
            root_short = residue.root[:10] if residue.root else ""
            return f"committed: {root_short}" if root_short else "committed"
        if residue.status == "halted":
            # Find first failed node name
            failed_node = ""
            for n in residue.nodes:
                if n.state == "failed":
                    failed_node = n.name
                    break
            return f"halt: {failed_node}" if failed_node else "halted"
        if residue.status == "hydrating":
            # Find the currently running node
            for n in residue.nodes:
                if n.state == "running":
                    return f"running: {n.name}"
            return "hydrating"
        return residue.status

    if residue.command == "status":
        if has_fails:
            # Find stale reasons
            stale_nodes = [n for n in residue.nodes if n.state == "stale"]
            if stale_nodes and stale_nodes[0].stale_reason:
                return f"stale: {stale_nodes[0].stale_reason}"
            return "stale"
        return "sealed"

    # Fallback
    if has_fails:
        fail_items = residue.fails if isinstance(residue.fails, list) else []
        return f"failures in {', '.join(fail_items)}" if fail_items else "failed"
    return "passed"


def _footer_right(residue: CliResidue) -> str:
    """Build the right-side execution metrics for the footer.

    Shows: tokens_in · tokens_out · $cost · elapsed · ⚡fuel
    Always shown for run/status commands — zero values are informative
    (e.g. "$0.0000" on a cached re-run means "this was free").
    """
    # Only show metrics for commands that have execution context
    if residue.command not in ("run", "status"):
        return ""

    # Aggregate token counts from node traces
    total_in = 0
    total_out = 0
    for n in residue.nodes:
        if n.trace:
            total_in += n.trace.input_tokens or 0
            total_out += n.trace.output_tokens or 0

    total_elapsed = sum(
        n.duration for n in residue.nodes
        if n.duration is not None and n.duration > 0
    )

    cost = residue.cost or 0.0
    fuel_used = residue.fuel_used or 0
    fuel_budget = residue.fuel_budget or 0

    sep = f" {DIM}\u00b7{RESET} "
    parts: list[str] = [
        f"{_format_tokens(total_in)}in",
        f"{_format_tokens(total_out)}out",
        f"${cost:.4f}",
        f"{total_elapsed:.2f}s",
        f"\u26a1{fuel_used}/{fuel_budget}" if residue.command != "status" else f"\u26a1{fuel_used}",
    ]

    return sep.join(parts)


# -- Private: JSON emission ---------------------------------------------------

def _emit_json(residue: CliResidue) -> str:
    """Emit residue as pure JSON with shared vocabulary."""
    status_display = map_display_status(residue.status, residue.command)

    # Build top-level structure
    output = {
        "command": residue.command,
        "name": residue.design_name,
        "site": residue.site,
        "status": status_display,
        "root": residue.root,
        "husk": residue.husk_hash,
        "fuel_budget": residue.fuel_budget,
        "fuel_used": residue.fuel_used,
        "cost": residue.cost,
        "nodes": [],
        "passes": residue.passes,
        "fails": residue.fails,
    }

    # Build node list
    for node in residue.nodes:
        node_dict = {
            "name": node.name,
            "kind": node.kind,
            "state": node.state,
        }

        # Optional fields (only include if not None)
        if node.children:
            node_dict["children"] = node.children
        if node.fuel is not None:
            node_dict["fuel"] = node.fuel
        if node.fuel_budget is not None:
            node_dict["fuel_budget"] = node.fuel_budget
        if node.cost is not None:
            node_dict["cost"] = node.cost
        if node.cache:
            node_dict["cache"] = node.cache
        if node.output_hash is not None:
            node_dict["output_hash"] = node.output_hash
        if node.diagnosis is not None:
            node_dict["diagnosis"] = node.diagnosis
        if node.stale_reason is not None:
            node_dict["stale_reason"] = node.stale_reason

        output["nodes"].append(node_dict)

    # Add error message if present
    if residue.error_message:
        output["error"] = residue.error_message

    return json.dumps(output, indent=2)
