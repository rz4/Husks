"""
CLI View layer - pure section renderers with unified visual grammar.

Exports pure renderers that take explicit data, not residue objects.
No command awareness — all "what to show" decisions live in surface.py.

**Visual grammar:**
- State glyphs: □ unrealized, ■ sealed, ◆ cached, △ stale, ✕ failed, ◉ running
- Kind appears as text column, not glyph
- Target-rooted dependency tree
- Crystalline logo header with right-aligned metadata at column R
- DIM separator lines, BOLD headers, CYAN accents
"""

from __future__ import annotations
from husks.cli.residue import CliResidue, CliNode, LogEntry
from husks.utils.console import (
    GREEN, YELLOW, RED, CYAN, DIM, BOLD, RESET,
    render_banner, _visible_len,
)


# -- Constants ----------------------------------------------------------------

# Right bound: sized so full SHA-256 hashes (64 hex chars) align with dividers.
# Banner right text starts at column 10 (diamond max_vis=8 + gap=2).
# Label "husk:  " is 7 chars → 10 + 7 + 64 = 81.
R = 81

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

# Sub-terminal log grammar: per-stream color + optional leading glyph.
# Kept deliberately spare -- the gutter rule carries the "sub-terminal"
# reading; the prefix only disambiguates stream provenance.
STREAM_STYLE = {
    "stdout": (RESET, ""),
    "stderr": (RED, ""),
    "oracle": (DIM, f"{CYAN}\u2192{RESET} "),
    "tool":   (CYAN, f"{CYAN}\u2192{RESET} "),
    "meta":   (DIM, ""),
}

# The descending gutter that ties a node's log pane to its glyph.
LOG_GUTTER = "\u254e"  # ╎  dashed vertical: subordinate, ephemeral


# -- Public API ---------------------------------------------------------------

def render_output(
    *,
    preamble: str | None = None,
    trace: list[str] | None = None,
    footer: str | None = None,
) -> str:
    """Compose CLI output from three optional sections.

    Parameters
    ----------
    preamble : str, optional
        Logo header + stage header + first divider.  Rendered first as-is.
    trace : list[str], optional
        Body lines (tree, help listings, init steps).  Rendered as-is.
    footer : str, optional
        Footer text rendered after a ``───`` divider with shared indent.

    Returns
    -------
    str
        Composed output string.
    """
    parts: list[str] = []

    if preamble is not None:
        parts.append(preamble)

    if trace is not None:
        parts.extend(trace)

    # Divider placed after the trace.  When trace is None but preamble is
    # present, the preamble already ends with a divider — don't duplicate.
    if trace is not None:
        hline = '\u2500' * (R - 2)
        parts.append(f"  {DIM}{hline}{RESET}")
    elif footer is not None and preamble is None:
        hline = '\u2500' * (R - 2)
        parts.append(f"  {DIM}{hline}{RESET}")

    if footer is not None:
        parts.append(footer)

    return "\n".join(parts)


def render_preamble(
    *,
    design_name: str,
    display_status: str,
    diamond_stage: str,
    husk_hash: str | None = None,
    root: str | None = None,
    site: str | None = None,
    stage_label: str,
    fuel_budget: int = 0,
    prior_stage: str | None = None,
    status_suffix: str = "",
) -> str:
    """Build the preamble section: logo header + stage header + first divider.

    All data is passed explicitly — no residue or command awareness.

    Parameters
    ----------
    prior_stage : str, optional
        If set, renders a ghost banner above the main one to show the
        state that was attempted before the current end-state (e.g.
        "disconnected" hydrating diamond above a failed diamond).
    """
    parts: list[str] = []

    # Ghost banner: prior state rendered as a dim afterimage
    if prior_stage:
        prior_right = [
            f"{DIM}{design_name}{RESET}",
            f"{DIM}{prior_stage}{RESET}",
            "",
            "",
            "",
        ]
        parts.append(render_banner("disconnected", prior_right))

    # Color the state value to match logo colors
    state_colors = {
        "checked": DIM,
        "sealed": YELLOW,
        "failed": RED,
        "hydrating": CYAN,
    }
    sc = state_colors.get(display_status, DIM)
    state_str = f"{sc}{display_status}{RESET}"

    # Color hashes by seal state
    is_sealed = display_status == "sealed"
    husk_color = YELLOW if is_sealed else DIM
    root_color = GREEN if is_sealed else RED

    right = [
        f"{BOLD}public{RESET}: {design_name}",
        f"{BOLD}state{RESET}:  {state_str}{status_suffix}",
        f"{BOLD}husk{RESET}:   {husk_color}{husk_hash}{RESET}" if husk_hash else "",
        f"{BOLD}root{RESET}:   {root_color}{root}{RESET}" if root else "",
        f"{BOLD}site{RESET}:   {site}" if site else "",
    ]

    parts.append(render_banner(diamond_stage, right))

    # Blank line + stage header with right-aligned global fuel
    parts.append("")
    stage_left = f"  {BOLD}{stage_label}{RESET}"
    if fuel_budget and fuel_budget > 0:
        fuel_right = f"\u26a1{fuel_budget}"
        parts.append(_rpad(stage_left, fuel_right, R))
    else:
        parts.append(stage_left)

    # Separator (first divider, part of the preamble)
    hline = '\u2500' * (R - 2)
    parts.append(f"  {DIM}{hline}{RESET}")

    return "\n".join(parts)


def render_motif_tree(
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
        is_root=True,
    )
    return lines


def render_footer(*, left_text: str, right_text: str) -> str:
    """Render footer with pre-computed left and right text.

    Takes pre-computed strings and does _rpad layout.
    """
    return _rpad(f"  {left_text}", right_text, R)


def render_explain_mode(
    residue: CliResidue,
    *,
    cursor: str,
    aperture: int = 1,
    controls: bool = False,
) -> str:
    """Render explain mode with cursor/aperture navigation.

    Quarantined: still takes residue directly because explain mode
    has its own bounded-box rendering path.
    """
    from husks.cli.residue import map_display_status

    lines: list[str] = []

    box_width = 40
    separator = "\u2500" * box_width

    status_display = map_display_status(residue.status, residue.command)
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


# -- Private: motif tree helpers ----------------------------------------------

def _render_motif_node(
    node: CliNode,
    nodes_by_name: dict[str, CliNode],
    lines: list[str],
    prefix: str,
    *,
    verbose: bool,
    log_lines: dict[str, list[str]] | None,
    is_last: bool,
    is_root: bool = False,
) -> None:
    """Recursively render a node and its children in motif style.

    Layout (2-space base indent, pipes align between siblings)::

        ■ validate   action                    0.01s · ⚡1
        └─ ■ generate   oracle   840in · 320out · $0.0032 · 4.52s · ⚡10
    """
    glyph = STATE_GLYPHS.get(node.state, "\u25a1")
    color = STATE_COLORS.get(node.state, RESET)

    connector = ""
    if not is_root:
        connector = "\u2514\u2500 " if is_last else "\u251c\u2500 "

    full_prefix = prefix + connector
    base = "  "  # 2-space base indent (aligns with dividers)

    # Left side: glyph + name + kind
    left = f"{base}{full_prefix}{color}{glyph}{RESET} {node.name}"
    kind_str = f"{DIM}{node.kind}{RESET}"

    # Visible length of left + gap + kind
    left_vis = len(base) + len(full_prefix) + 1 + 1 + len(node.name)
    kind_gap = max(1, 22 - left_vis)
    left_with_kind = f"{left}{' ' * kind_gap}{kind_str}"
    left_vis_total = left_vis + kind_gap + len(node.kind)

    # Right side: metadata (tokens · cost · elapsed · fuel)
    # Right-aligned to column R so summaries align with the footer.
    right_parts = _node_right_parts(node, log_lines=log_lines)
    node_sep = f" {DIM}\u00b7{RESET} "
    right_str = node_sep.join(right_parts)

    if right_str:
        lines.append(_rpad(left_with_kind, right_str, R))
    else:
        lines.append(left_with_kind.rstrip())

    # Continuation prefix for detail lines and children: │ if siblings
    # follow below this node, blank if this is the last sibling.
    if is_root:
        own_continuation = ""
    elif is_last:
        own_continuation = "   "
    else:
        own_continuation = "\u2502  "
    inner_prefix = prefix + own_continuation

    # Verbose detail lines (aperture 3 for all nodes in verbose mode)
    if verbose:
        detail_indent = base + inner_prefix + "  "
        _render_aperture_details(node, lines, detail_indent, aperture=3)

    # Live sub-terminal pane (from LiveFrameEmitter during hydration).
    # Gutter sits at the glyph column under a dim dashed pipe.
    if log_lines and node.name in log_lines and log_lines[node.name]:
        gutter_col = len(base) + len(inner_prefix)
        gutter = f"{' ' * gutter_col}{DIM}{LOG_GUTTER}{RESET} "
        max_log_width = R - (gutter_col + 2)

        for entry in log_lines[node.name]:
            stream, text = _coerce_log_entry(entry)
            color, pfx = STREAM_STYLE.get(stream, (RESET, ""))

            pfx_vis = _visible_len(pfx)
            budget = max(8, max_log_width - pfx_vis)
            text = _truncate_right(text, budget)

            lines.append(f"{gutter}{pfx}{color}{text}{RESET}")

    # Children
    children_names = getattr(node, 'children', [])
    children = [nodes_by_name[name] for name in children_names if name in nodes_by_name]

    if children:
        child_prefix = inner_prefix
        for i, child in enumerate(children):
            _render_motif_node(
                child, nodes_by_name, lines, child_prefix,
                verbose=verbose, log_lines=log_lines,
                is_last=(i == len(children) - 1),
            )


def _node_right_parts(
    node: CliNode,
    log_lines: dict[str, list] | None = None,
) -> list[str]:
    """Build right-side metadata for a node line.

    Format mirrors the footer summary::

        oracle:  840in · 320out · $0.0032 · 4.52s · ⚡1
        action:  0.01s · ⚡1
        cached:  cached · 0in · 0out · $0.0000 · 0.00s · ⚡0
        unrealized:  ⚡10  (budget only)
        running:  write-file · 3.21s  (activity + live elapsed)
    """
    is_oracle = node.kind == "oracle"
    sep = f" {DIM}\u00b7{RESET} "

    # -- Unrealized: just show fuel budget ---------------------------------
    if node.state == "unrealized":
        if node.fuel_budget is not None:
            return [f"\u26a1{node.fuel_budget}"]
        return []

    # -- Running: activity label + live elapsed ----------------------------
    if node.state == "running":
        parts: list[str] = []
        if log_lines and node.name in log_lines:
            activity = _last_activity(log_lines[node.name])
            if activity:
                parts.append(activity)
        if node.duration is not None and node.duration > 0:
            parts.append(f"{node.duration:.2f}s")
        return parts

    # -- Sealed / cached / stale / failed: full summary --------------------
    parts = []

    # Tokens + cost (oracle nodes only — actions are deterministic)
    if is_oracle:
        tok_in = 0
        tok_out = 0
        cost = node.cost or 0.0
        if node.trace:
            tok_in = node.trace.input_tokens or 0
            tok_out = node.trace.output_tokens or 0
        parts.append(f"{_format_tokens(tok_in)}in")
        parts.append(f"{_format_tokens(tok_out)}out")
        parts.append(f"${cost:.4f}")

    # Elapsed
    elapsed = node.duration if node.duration is not None else 0.0
    parts.append(f"{elapsed:.2f}s")

    # Fuel: cached nodes consumed 0 effective fuel
    if node.cache:
        parts.append("\u26a10")
    elif node.fuel is not None:
        parts.append(f"\u26a1{node.fuel}")

    return parts


def _last_activity(entries: list) -> str | None:
    """Extract the last meaningful activity label from a node's log buffer.

    Scans backward for the most recent tool call or oracle action,
    skipping progress counters ("running X.Xs").
    """
    for entry in reversed(entries):
        stream, text = _coerce_log_entry(entry)
        if stream == "tool":
            return text
        if stream == "oracle" and not text.startswith("running "):
            # Truncate long prompts to a short label
            label = text[:24]
            if len(text) > 24:
                label += ".."
            return label
    return None


def _render_aperture_details(
    node: CliNode,
    lines: list[str],
    indent: str,
    aperture: int,
) -> None:
    """Render flat provenance footer for a node (verbose / explain).

    All provenance attributes are collapsed into dim gray lines:
    - outputs with short hashes
    - seal/recipe digests
    - oracle model provenance (backend, model, config, prompt hashes)
    - cache source
    - stale reason / diagnosis
    """
    # Outputs: path@hash
    if aperture >= 1 and node.outputs:
        outputs_to_show = node.outputs[:1] if aperture == 1 else node.outputs
        for out in outputs_to_show:
            h = out.sha256[:6] if out.sha256 else "??????"
            lines.append(f"{indent}{DIM}{out.path}@{h}{RESET}")

    # Seal digests
    if aperture >= 2:
        if node.seal_digest:
            lines.append(f"{indent}{DIM}seal:   {node.seal_digest[:6]}{RESET}")
        if node.recipe_digest:
            lines.append(f"{indent}{DIM}recipe: {node.recipe_digest[:6]}{RESET}")
        if node.trace and node.trace.cache_source:
            lines.append(f"{indent}{DIM}cache:  {node.trace.cache_source}{RESET}")

    # Oracle/action provenance
    if aperture >= 3 and node.trace:
        t = node.trace
        if t.backend:
            lines.append(f"{indent}{DIM}backend: {t.backend}{RESET}")
        if t.model:
            lines.append(f"{indent}{DIM}model:   {t.model}{RESET}")
        if t.tools:
            lines.append(f"{indent}{DIM}tools:   {', '.join(t.tools)}{RESET}")
        if t.fuel is not None:
            lines.append(f"{indent}{DIM}fuel:    {t.fuel}{RESET}")
        if t.config_hash:
            lines.append(f"{indent}{DIM}config:  {t.config_hash[:6]}{RESET}")
        if t.prompt_hash:
            lines.append(f"{indent}{DIM}prompt:  {t.prompt_hash[:6]}{RESET}")

    # Stale / error diagnostics
    if node.stale_reason:
        lines.append(f"{indent}{DIM}stale:  {node.stale_reason}{RESET}")
    if node.diagnosis:
        diag = node.diagnosis
        # Truncate long diagnostics (e.g. API error JSON) to frame width.
        max_diag = max(40, R - _visible_len(indent) - len("error:  "))
        if len(diag) > max_diag:
            diag = diag[:max_diag - 1] + "\u2026"
        lines.append(f"{indent}{RED}error:  {diag}{RESET}")

    # Failed nodes: expand stdout/stderr trace so the cause is visible.
    # Stderr first (errors), then stdout (context), separated from
    # the provenance block above by a blank line.
    if node.state == "failed" and node.trace:
        has_output = node.trace.stderr or node.trace.stdout
        if has_output:
            lines.append("")
        if node.trace.stderr:
            for line in node.trace.stderr.splitlines():
                lines.append(f"{indent}{RED}{line}{RESET}")
        if node.trace.stdout:
            if node.trace.stderr:
                lines.append("")
            for line in node.trace.stdout.splitlines():
                lines.append(f"{indent}{DIM}{line}{RESET}")


# -- Explain mode (quarantined) -----------------------------------------------

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

    # Aperture details (flat provenance footer)
    node_aperture = aperture if is_selected else 1
    detail_indent = "      " if prefix else "    "
    _render_aperture_details(node, lines, detail_indent, node_aperture)

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

def _coerce_log_entry(entry) -> tuple[str, str]:
    """Normalise a log entry to ``(stream, text)``.

    Accepts a :class:`LogEntry`, a plain ``(stream, text)`` tuple, or a bare
    string (treated as stdout), so the renderer is robust to older callers.
    """
    if isinstance(entry, LogEntry):
        return entry.stream, entry.text
    if isinstance(entry, tuple) and len(entry) == 2:
        return entry[0], entry[1]
    return "stdout", str(entry)


def _truncate_right(text: str, max_width: int) -> str:
    """Truncate *text* to *max_width* visible columns, eliding on the right.

    Log lines are plain (colour is applied by the caller), so a simple
    width count is sufficient.  Tabs are expanded so widths stay honest.
    """
    text = text.replace("\t", "    ")
    if _visible_len(text) <= max_width:
        return text
    cut = max(1, max_width - 1)
    return text[:cut] + "\u2026"


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


def _format_tokens(n: int) -> str:
    """Format token count compactly."""
    if n < 1000:
        return str(n)
    return f"{n / 1000:.1f}k"


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
