"""
CLI View layer - visual DAG renderer with unified grammar.

Unified visual grammar for check / run / status commands.

**Visual grammar:**
- State glyphs: □ unrealized, ■ sealed, ◆ cached, △ stale, ✕ failed, ◉ running
- Kind appears as text column, not glyph
- Target-rooted dependency tree
- Crystalline logo header with right-aligned metadata at column R=60
- Stage headers: check→"design", run→"build", status→"inspect"
- DIM separator lines, BOLD headers, CYAN accents

**Modes:**
- Standard: logo + motif for all commands (check always shows output)
- Verbose: same motif, aperture-3 detail on all nodes
- Explain: separate rendering path (cursor/aperture navigation)
"""

from __future__ import annotations
import re
from husks.cli.residue import CliResidue, CliNode
from husks.utils.console import (
    GREEN, YELLOW, RED, CYAN, DIM, BOLD, RESET, W,
    render_banner, _visible_len,
)


# -- Constants ----------------------------------------------------------------

R = W  # Right bound (column 60)

STAGE_MAP = {
    "check": "design",
    "run": "build",
    "status": "inspect",
}

# State glyphs (leading mark)
STATE_GLYPHS = {
    "unrealized": "\u25a1",
    "sealed": "\u25a0",
    "cached": "\u25c6",
    "stale": "\u25b3",
    "failed": "\u2715",
    "running": "\u25c9",
}

# State colors
STATE_COLORS = {
    "unrealized": DIM,
    "sealed": GREEN,
    "cached": CYAN,
    "stale": YELLOW,
    "failed": RED,
    "running": CYAN,
}


# -- Public API ---------------------------------------------------------------

def render_dag(
    residue: CliResidue,
    *,
    verbose: bool = False,
    cursor: str = None,
    aperture: int = 1,
    controls: bool = False,
    log_lines: dict[str, list[str]] | None = None,
) -> str:
    """Render target-rooted DAG with unified visual grammar.

    Parameters
    ----------
    residue : CliResidue
        Residue from check, run, or status command.
    verbose : bool
        Expand all nodes to aperture 3.
    cursor : str, optional
        Selected node name (explain mode -- separate rendering path).
    aperture : int
        Detail level for selected node in explain mode (0-3).
    controls : bool
        Show keyboard controls footer (explain mode).
    log_lines : dict, optional
        Per-node live log lines from LiveFrameEmitter.  Keys are rule
        names; values are lists of already-formatted strings to render
        below the matching node.

    Returns
    -------
    str
        Formatted visual output with ANSI colors.
    """
    # Explain mode has its own rendering path (unchanged)
    if cursor is not None:
        return _render_explain_mode(
            residue, cursor=cursor, aperture=aperture, controls=controls,
        )

    # -- Motif rendering for check / run / status ----------------------------
    parts: list[str] = []

    # 1. Logo header with right-column metadata
    parts.append(_render_logo_header(residue))

    # 2. Blank line + stage header
    stage = STAGE_MAP.get(residue.command, residue.command)
    parts.append("")
    parts.append(f"  {BOLD}{stage}{RESET}")

    # 3. Separator
    hline = '\u2500' * (R - 2)
    parts.append(f"  {DIM}{hline}{RESET}")

    # 4. Node tree
    tree = _render_motif_tree(
        residue.nodes, verbose=verbose, log_lines=log_lines,
    )
    parts.extend(tree)

    # 5. Separator
    hline = '\u2500' * (R - 2)
    parts.append(f"  {DIM}{hline}{RESET}")

    # 6. Footer
    parts.append(_render_footer(residue))

    return "\n".join(parts)


# -- Logo header --------------------------------------------------------------

def _render_logo_header(residue: CliResidue) -> str:
    """Build morphing diamond banner with left-aligned summary (5 rows).

    Same format as ``husks status`` summary:
      name:  {name}
      state: {state}
      husk:  sha256:{hash}
      root:  sha256:{hash}
      site:  {path}
    """
    # Map residue to diamond stage
    if residue.status == "dry" or residue.command == "check":
        stage = "dry"
    elif residue.status == "hydrating":
        stage = "hydrating"
    else:
        stage = "sealed"

    status_display = _map_visual_status(residue.status, residue.command)

    # Color the state value
    state_colors = {
        "checked": DIM,
        "sealed": CYAN,
        "failed": RED,
        "hydrating": YELLOW,
    }
    sc = state_colors.get(status_display, DIM)
    state_str = f"{sc}{status_display}{RESET}"

    right = [
        f"{BOLD}name{RESET}:  {residue.design_name}",
        f"{BOLD}state{RESET}: {state_str}",
        f"{BOLD}husk{RESET}:  sha256:{residue.husk_hash}" if residue.husk_hash else "",
        f"{BOLD}root{RESET}:  sha256:{residue.root}" if residue.root else "",
        f"{BOLD}site{RESET}:  {residue.site}" if residue.site else "",
    ]

    return render_banner(stage, right)


# -- Motif tree ---------------------------------------------------------------

def _render_motif_tree(
    nodes: list[CliNode],
    *,
    verbose: bool = False,
    log_lines: dict[str, list[str]] | None = None,
) -> list[str]:
    """Render target-rooted tree with right-aligned metadata."""
    if not nodes:
        return []

    nodes_by_name = {n.name: n for n in nodes}
    target = nodes[0]

    lines: list[str] = []
    _render_motif_node(
        target, nodes_by_name, lines, prefix="",
        verbose=verbose, log_lines=log_lines, is_last=True,
    )
    return lines


def _render_motif_node(
    node: CliNode,
    nodes_by_name: dict[str, CliNode],
    lines: list[str],
    prefix: str,
    *,
    verbose: bool,
    log_lines: dict[str, list[str]] | None,
    is_last: bool,
) -> None:
    """Recursively render a node and its children in motif style."""
    glyph = STATE_GLYPHS.get(node.state, "\u25a1")
    color = STATE_COLORS.get(node.state, RESET)

    connector = ""
    if prefix:
        connector = "\u2514\u2500 " if is_last else "\u251c\u2500 "

    full_prefix = prefix + connector

    # Left side: glyph + name + kind
    left = f"    {full_prefix}{color}{glyph}{RESET} {node.name}"
    kind_str = f"{DIM}{node.kind}{RESET}"

    # Visible length of left + gap + kind
    left_vis = 4 + len(full_prefix) + 1 + 1 + len(node.name)
    kind_gap = max(1, 22 - left_vis)
    left_with_kind = f"{left}{' ' * kind_gap}{kind_str}"
    left_vis_total = left_vis + kind_gap + len(node.kind)

    # Right side: metadata (time, cost, fuel budget)
    right_parts = _node_right_parts(node)
    right_str = "  ".join(right_parts)

    if right_str:
        right_vis = _visible_len(right_str)
        gap = max(1, R - left_vis_total - right_vis)
        lines.append(f"{left_with_kind}{' ' * gap}{right_str}")
    else:
        lines.append(left_with_kind.rstrip())

    # Verbose detail lines (aperture 3 for all nodes in verbose mode)
    if verbose:
        detail_indent = "        " + ("   " if prefix else "")
        _render_aperture_details(node, lines, detail_indent, aperture=3)

    # Live log lines (from LiveFrameEmitter during hydration)
    if log_lines and node.name in log_lines:
        # Align with first character of node name (after glyph + space)
        # Node line format: "    {prefix}{glyph} {name}..."
        # So log lines align at: 4 + len(prefix) + 2 (glyph + space)
        log_indent = " " * (4 + len(full_prefix) + 2)

        # Max visible width for log content (enforce right bound at R)
        max_log_width = R - len(log_indent)

        for ll in log_lines[node.name]:
            # Truncate from left if exceeds max_log_width
            ll_vis = _visible_len(ll)
            if ll_vis > max_log_width:
                # Truncate from left, prepend ".."
                # Approximate: remove chars from start until we fit
                # Simple heuristic: truncate string, not perfect for ANSI
                excess = ll_vis - max_log_width + 2  # +2 for ".."
                ll = ".." + ll[excess:]
            lines.append(f"{log_indent}{ll}")

    # Children
    children_names = getattr(node, 'children', [])
    children = [nodes_by_name[name] for name in children_names if name in nodes_by_name]

    if children:
        continuation = "   " if is_last else "\u2502  "
        child_prefix = prefix + continuation
        for i, child in enumerate(children):
            _render_motif_node(
                child, nodes_by_name, lines, child_prefix,
                verbose=verbose, log_lines=log_lines,
                is_last=(i == len(children) - 1),
            )


def _node_right_parts(node: CliNode) -> list[str]:
    """Build right-side metadata parts for a node line."""
    parts: list[str] = []

    # Cached label
    if node.cache:
        parts.append("cached")

    # Duration
    if node.duration is not None and node.duration > 0:
        parts.append(f"{node.duration:.2f}s")

    # Fuel / cost
    if node.cache:
        parts.append("\u26a10")
        parts.append("$0.0000")
    else:
        if node.fuel is not None:
            parts.append(f"\u26a1{node.fuel}")
        if node.cost is not None and node.cost > 0:
            parts.append(f"${node.cost:.4f}")
        if node.fuel_budget is not None and node.state == "unrealized":
            parts.append(f"\u26a1{node.fuel_budget}")

    return parts


def _render_aperture_details(
    node: CliNode,
    lines: list[str],
    indent: str,
    aperture: int,
) -> None:
    """Render aperture-based detail lines for a node (verbose / explain)."""
    if aperture >= 1 and node.outputs:
        outputs_to_show = node.outputs[:1] if aperture == 1 else node.outputs
        for out in outputs_to_show:
            h = out.sha256[:6] if out.sha256 else "??????"
            lines.append(f"{indent}out:{out.path}@{h}")

    if aperture >= 2:
        if node.seal_digest or node.recipe_digest:
            lines.append(f"{indent}seal:")
            if node.seal_digest:
                lines.append(f"{indent}  digest: {node.seal_digest[:6]}")
            if node.recipe_digest:
                lines.append(f"{indent}  recipe: {node.recipe_digest[:6]}")
            if node.input_hashes:
                lines.append(f"{indent}  inputs: {len(node.input_hashes)}")
            if node.output_hashes:
                lines.append(f"{indent}  outputs: {len(node.output_hashes)}")
        if node.trace and node.trace.cache_source:
            lines.append(f"{indent}cache: {node.trace.cache_source}")

    if aperture >= 3:
        if node.trace:
            t = node.trace
            lines.append(f"{indent}trace:")
            if t.backend:
                lines.append(f"{indent}  backend: {t.backend}")
            if t.model:
                lines.append(f"{indent}  model: {t.model}")
            if t.config_hash:
                lines.append(f"{indent}  config: sha256:{t.config_hash[:6]}")
            if t.prompt_hash:
                lines.append(f"{indent}  prompt: sha256:{t.prompt_hash[:6]}")
            if t.input_tokens and t.input_tokens > 0:
                lines.append(f"{indent}  input_tokens: {t.input_tokens}")
            if t.output_tokens and t.output_tokens > 0:
                lines.append(f"{indent}  output_tokens: {t.output_tokens}")
            if t.elapsed_s is not None:
                lines.append(f"{indent}  elapsed: {t.elapsed_s:.2f}s")
            if t.cost_usd and t.cost_usd > 0:
                lines.append(f"{indent}  cost: ${t.cost_usd:.4f}")
            if t.stdout:
                lines.append(f"{indent}stdout:")
                for sl in t.stdout.split('\n')[:5]:
                    lines.append(f"{indent}  {sl}")
            if t.stderr:
                lines.append(f"{indent}stderr:")
                for sl in t.stderr.split('\n')[:5]:
                    lines.append(f"{indent}  {sl}")
        if node.stale_reason:
            lines.append(f"{indent}stale: {node.stale_reason}")
        if node.diagnosis:
            lines.append(f"{indent}error: {node.diagnosis}")


# -- Footer -------------------------------------------------------------------

def _render_footer(residue: CliResidue) -> str:
    """Render footer: passes/fails left, elapsed right, right-aligned to R."""
    has_fails = (
        residue.fails and len(residue.fails) > 0
        if isinstance(residue.fails, list)
        else residue.fails > 0
    )

    if has_fails:
        fail_items = residue.fails if isinstance(residue.fails, list) else []
        left = f"failures in {', '.join(fail_items)}" if fail_items else "failed"
    else:
        pass_items = residue.passes if isinstance(residue.passes, list) else []
        left = f"passes: {', '.join(pass_items)}" if pass_items else "passed"

    # Elapsed time (for run commands)
    right = ""
    # Total elapsed could be computed from node durations
    total_elapsed = sum(
        n.duration for n in residue.nodes
        if n.duration is not None and n.duration > 0
    )
    if total_elapsed > 0:
        right = f"{total_elapsed:.2f}s elapsed"

    return _rpad(f"  {left}", right, R)


# -- Explain mode (unchanged) -------------------------------------------------

def _render_explain_mode(
    residue: CliResidue,
    *,
    cursor: str,
    aperture: int = 1,
    controls: bool = False,
) -> str:
    """Render explain mode with cursor/aperture navigation."""
    lines: list[str] = []

    box_width = 40
    separator = "\u2500" * box_width

    status_display = _map_visual_status(residue.status, residue.command)
    cse_display = residue.cse_path if residue.cse_path else "none"
    root_display = f"root:{residue.root[:7]}" if residue.root else ""
    site_display = residue.site if residue.site else "none"

    lines.append(separator)

    line1 = f" {cse_display}"
    if root_display:
        pad = max(2, box_width - len(line1) - len(root_display) - 1)
        line1 += f"{' ' * pad}{root_display}"
    lines.append(line1)

    cursor_display = f"cursor:{cursor}" if cursor else ""
    line2 = f" site:{site_display}"
    if cursor_display:
        pad = max(2, box_width - len(line2) - len(cursor_display) - 1)
        line2 += f"{' ' * pad}{cursor_display}"
    lines.append(line2)

    lines.append(f" aperture:{aperture}")
    lines.append(separator)

    # Tree
    tree = _render_explain_tree(residue.nodes, cursor, aperture)
    lines.extend(tree)
    lines.append(separator)

    # Footer
    if controls:
        lines.append(" \u2191\u2193 move   \u2190\u2192 aperture   q quit")
    else:
        lines.append(_render_footer_legacy(residue))

    return "\n".join(lines)


def _render_explain_tree(
    nodes: list[CliNode],
    cursor: str,
    aperture: int,
) -> list[str]:
    """Render tree for explain mode (old bounded-box style)."""
    if not nodes:
        return []

    nodes_by_name = {n.name: n for n in nodes}
    target = nodes[0]

    lines: list[str] = []
    _render_explain_node(target, nodes_by_name, lines, "", cursor, aperture, is_last=True)
    return lines


def _render_explain_node(
    node: CliNode,
    nodes_by_name: dict,
    lines: list,
    prefix: str,
    cursor: str,
    aperture: int,
    is_last: bool,
) -> None:
    """Render a node in explain mode (preserves old rendering for explain)."""
    glyph = STATE_GLYPHS.get(node.state, "\u25a1")
    color = STATE_COLORS.get(node.state, RESET)
    is_selected = (cursor == node.name)

    connector = ""
    if prefix:
        connector = "\u2514\u2500 " if is_last else "\u251c\u2500 "

    cursor_mark = "\u25b6" if is_selected else ""
    full_prefix = prefix + connector
    name_field = f"{cursor_mark}{color}{glyph}{RESET} {node.name}"

    cursor_len = 1 if is_selected else 0
    visible_len = len(full_prefix) + cursor_len + 1 + 1 + len(node.name)
    padding = max(1, 22 - visible_len)

    node_line = f" {full_prefix}{name_field}{' ' * padding}{node.kind}"
    lines.append(node_line.rstrip())

    # Aperture details
    node_aperture = aperture if is_selected else 1
    detail_indent = "      " if prefix else "    "

    if node_aperture >= 1 and node.outputs:
        outputs_to_show = node.outputs[:1] if node_aperture == 1 else node.outputs
        for out in outputs_to_show:
            h = out.sha256[:6] if out.sha256 else "??????"
            lines.append(f"{detail_indent}out:{out.path}@{h}")

    if node_aperture >= 2:
        if node.seal_digest or node.recipe_digest:
            lines.append(f"{detail_indent}seal:")
            if node.seal_digest:
                lines.append(f"{detail_indent}  digest: {node.seal_digest[:6]}")
            if node.recipe_digest:
                lines.append(f"{detail_indent}  recipe: {node.recipe_digest[:6]}")
            if node.input_hashes:
                lines.append(f"{detail_indent}  inputs: {len(node.input_hashes)}")
            if node.output_hashes:
                lines.append(f"{detail_indent}  outputs: {len(node.output_hashes)}")
        if node.trace and node.trace.cache_source:
            lines.append(f"{detail_indent}cache: {node.trace.cache_source}")

    if node_aperture >= 3:
        if node.trace:
            t = node.trace
            lines.append(f"{detail_indent}trace:")
            if t.backend:
                lines.append(f"{detail_indent}  backend: {t.backend}")
            if t.model:
                lines.append(f"{detail_indent}  model: {t.model}")
            if t.config_hash:
                lines.append(f"{detail_indent}  config: sha256:{t.config_hash[:6]}")
            if t.prompt_hash:
                lines.append(f"{detail_indent}  prompt: sha256:{t.prompt_hash[:6]}")
            if t.input_tokens and t.input_tokens > 0:
                lines.append(f"{detail_indent}  input_tokens: {t.input_tokens}")
            if t.output_tokens and t.output_tokens > 0:
                lines.append(f"{detail_indent}  output_tokens: {t.output_tokens}")
            if t.elapsed_s is not None:
                lines.append(f"{detail_indent}  elapsed: {t.elapsed_s:.2f}s")
            if t.cost_usd and t.cost_usd > 0:
                lines.append(f"{detail_indent}  cost: ${t.cost_usd:.4f}")
            if t.stdout:
                lines.append(f"{detail_indent}stdout:")
                for sl in t.stdout.split('\n')[:5]:
                    lines.append(f"{detail_indent}  {sl}")
            if t.stderr:
                lines.append(f"{detail_indent}stderr:")
                for sl in t.stderr.split('\n')[:5]:
                    lines.append(f"{detail_indent}  {sl}")
        if node.stale_reason:
            lines.append(f"{detail_indent}stale: {node.stale_reason}")
        if node.diagnosis:
            lines.append(f"{detail_indent}error: {node.diagnosis}")

    # Children
    children_names = getattr(node, 'children', [])
    children = [nodes_by_name[name] for name in children_names if name in nodes_by_name]
    if children:
        continuation = "   " if is_last else "\u2502  "
        child_prefix = prefix + continuation
        for i, child in enumerate(children):
            _render_explain_node(
                child, nodes_by_name, lines, child_prefix,
                cursor, aperture, is_last=(i == len(children) - 1),
            )


# -- Helpers ------------------------------------------------------------------

def _map_visual_status(status: str, command: str) -> str:
    """Map residue status to visual display status."""
    if command == "check":
        return "checked" if status == "dry" else status
    elif status == "committed":
        return "sealed"
    elif status == "halted":
        return "failed"
    return status


def _rpad(left: str, right: str, width: int) -> str:
    """Pad between *left* and *right* so the combined visible width = *width*.

    Both may contain ANSI codes; only visible characters count toward width.
    """
    if not right:
        return left
    lv = _visible_len(left)
    rv = _visible_len(right)
    gap = max(1, width - lv - rv)
    return f"{left}{' ' * gap}{right}"


def _render_footer_legacy(residue: CliResidue) -> str:
    """Legacy footer for explain mode."""
    has_fails = (
        residue.fails and len(residue.fails) > 0
        if isinstance(residue.fails, list)
        else residue.fails > 0
    )
    if has_fails:
        fail_items = residue.fails if isinstance(residue.fails, list) else []
        return f" failures in {', '.join(fail_items)}" if fail_items else " failed"
    pass_items = residue.passes if isinstance(residue.passes, list) else []
    return f" passes: {', '.join(pass_items)}" if pass_items else " passed"
