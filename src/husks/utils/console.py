"""
console.py -- ANSI terminal renderer for Husks build events.

Implements TraceListener: receives event dicts and renders to stdout
with color and alignment.  Pure side effect -- never modifies build
state.  ANSI suppressed when stdout is not a TTY.

See docs/architecture.md for the event layout table.
"""

from __future__ import annotations

import sys
from typing import Any


# -- ANSI codes ---------------------------------------------------------------

DIM    = "\033[2m"
BOLD   = "\033[1m"
RESET  = "\033[0m"
GREEN  = "\033[32m"
YELLOW = "\033[33m"
RED    = "\033[31m"
CYAN   = "\033[36m"

_IS_TTY = sys.stdout.isatty()

if not _IS_TTY:
    DIM = BOLD = RESET = GREEN = YELLOW = RED = CYAN = ""

W = 60

# -- Cursor control (suppressed when not TTY) ---------------------------------

SAVE_CUR    = "\033[s"   if _IS_TTY else ""
RESTORE_CUR = "\033[u"   if _IS_TTY else ""
CLEAR_DOWN  = "\033[J"   if _IS_TTY else ""


def is_tty() -> bool:
    """Return True when stdout is a real terminal."""
    return _IS_TTY


def cursor_up(n: int) -> str:
    """Return ANSI sequence to move cursor up *n* lines (empty when piped)."""
    if not _IS_TTY or n <= 0:
        return ""
    return f"\033[{n}A"


# -- Morphing diamond art -----------------------------------------------------

_DIAMOND = {
    "dry": [
        f"     {DIM}\u25c7{RESET}",
        f"    {DIM}\u2571 \u2572{RESET}",
        f"   {DIM}\u25c7   \u25c7{RESET}",
        f"    {DIM}\u2572 \u2571{RESET}",
        f"     {DIM}\u25c7{RESET}",
    ],
    "hydrating": [
        f"     {CYAN}\u2b20{RESET}",
        f"    {CYAN}\u2571\u00b7\u2572{RESET}",
        f"   {CYAN}\u25c6 \u00b7 \u25c6{RESET}",
        f"    {CYAN}\u2572\u00b7\u2571{RESET}",
        f"     {CYAN}\u2b21{RESET}",
    ],
    "sealed": [
        f"     {YELLOW}\u25c6{RESET}",
        f"    {YELLOW}\u2571 \u2572{RESET}",
        f"   {YELLOW}\u25c6 \u25c6 \u25c6{RESET}",
        f"    {YELLOW}\u2572 \u2571{RESET}",
        f"     {YELLOW}\u25c6{RESET}",
    ],
    "failed": [
        f"     {RED}\u25c6{RESET}",
        f"    {RED}\u2571 \u2572{RESET}",
        f"   {RED}\u25c6 \u25c6 \u25c6{RESET}",
        f"    {RED}\u2572 \u2571{RESET}",
        f"     {RED}\u25c6{RESET}",
    ],
    "disconnected": [
        f"     {DIM}\u2b20{RESET}",
        f"    {DIM}\u2571\u00b7\u2572{RESET}",
        f"   {DIM}\u25c6 \u00b7 \u25c6{RESET}",
        f"    {DIM}\u2572\u00b7\u2571{RESET}",
        f"     {DIM}\u25c6{RESET}",
    ],
    "white": [
        f"     {BOLD}\u25c6{RESET}",
        f"    {BOLD}\u2571 \u2572{RESET}",
        f"   {BOLD}\u25c6 \u25c6 \u25c6{RESET}",
        f"    {BOLD}\u2572 \u2571{RESET}",
        f"     {BOLD}\u25c6{RESET}",
    ],
}

_DIAMOND_VIS = [6, 7, 8, 7, 6]


# -- Shared banner renderer ---------------------------------------------------

def render_banner(stage: str, right_lines: list[str] | None = None) -> str:
    r"""Return the 5-line morphing diamond banner with left-aligned metadata.

    *stage* selects the diamond variant: ``"dry"``, ``"hydrating"``, or
    ``"sealed"``.  Falls back to ``"hydrating"`` for unknown stages.

    *right_lines* is a list of up to 5 strings, one per diamond row,
    left-aligned after the diamond art with a fixed gap.

    Used by both ``main.py`` (help screen) and ``view.py`` (command output).
    """
    art = _DIAMOND.get(stage, _DIAMOND["hydrating"])
    right = (right_lines or []) + [""] * 5  # pad to at least 5 entries
    max_vis = max(_DIAMOND_VIS)

    lines: list[str] = []
    for i, (diamond_line, vis) in enumerate(zip(art, _DIAMOND_VIS)):
        rtxt = right[i]
        if rtxt:
            # Pad diamond to max width + 2 spaces, then left-align text
            gap = max_vis - vis + 2
            lines.append(f"{diamond_line}{' ' * gap}{rtxt}")
        else:
            lines.append(diamond_line)

    return "\n".join(lines)


def render_logo(right_lines: list[str] | None = None) -> str:
    r"""Legacy wrapper — renders the hydrating diamond.

    Kept for backward compatibility.  Prefer :func:`render_banner`.
    """
    # Old API: right_lines aligned with rows 2-4.  Remap to 5-row layout.
    old = (right_lines or []) + [""] * 3
    five = ["", "", old[0], old[1], old[2]]
    return render_banner("hydrating", five)


def _visible_len(s: str) -> int:
    """Return the visible terminal-column width of *s* (ANSI-safe).

    Strips ANSI escape sequences, then counts each character according to
    its East Asian Width: ``W`` (Wide) and ``F`` (Fullwidth) occupy 2
    columns; everything else occupies 1.
    """
    import re
    import unicodedata
    stripped = re.sub(r'\x1B\[[0-?]*[ -/]*[@-~]', '', s)
    w = 0
    for ch in stripped:
        eaw = unicodedata.east_asian_width(ch)
        w += 2 if eaw in ("W", "F") else 1
    return w


# -- Formatting helpers -------------------------------------------------------

def _tok(n: int) -> str:
    if n < 1000:
        return str(n)
    return f"{n / 1000:.1f}k"


def _dur(s: float) -> str:
    if s < 1.0:
        ms = s * 1000
        return "<1ms" if ms < 1 else f"{ms:.0f}ms"
    if s < 60:
        return f"{s:.2f}s"
    m, sec = divmod(s, 60)
    return f"{int(m)}m{sec:04.1f}s"


def _cost(usd: float) -> str:
    return f"${usd:.4f}"


def _shorthash(h: str | None) -> str:
    if not h or h.startswith("0:"):
        return "\u2013"
    return h[:10]


# -- Console renderer ---------------------------------------------------------

class Console:
    """ANSI renderer that implements the TraceListener protocol.

    Instantiate and register with a BuildTrace::

        trace = BuildTrace()
        trace.add_listener(Console())
    """

    def notify(self, event: dict[str, Any]) -> None:
        """Dispatch an event to the appropriate renderer."""
        handler = _HANDLERS.get(event.get("event", ""))
        if handler is not None:
            handler(event)


# -- Event handlers -----------------------------------------------------------

def _on_build_start(e: dict[str, Any]) -> None:
    bar = "\u2550" * W
    print(f"\n{BOLD}{bar}{RESET}")
    print(f"  {BOLD}{e['name']}{RESET}")
    print(f"  {DIM}site{RESET}  {e['site']}")
    ln = f"  {DIM}fuel{RESET}  {e['fuel']}"
    model = e.get("oracle_model")
    if model:
        ln += f"    {DIM}oracle{RESET}  {model}"
    print(ln)
    print(f"{BOLD}{bar}{RESET}\n", flush=True)


def _on_build_end(e: dict[str, Any]) -> None:
    status = e["status"]
    elapsed = e.get("elapsed", 0.0)
    fuel_left = e.get("fuel_left", 0)
    fuel_total = e.get("fuel_total", 0)

    tag = {
        "committed": f"{GREEN}{BOLD}committed{RESET}",
        "halted": f"{RED}{BOLD}halted{RESET}",
    }.get(status, f"{YELLOW}{BOLD}{status}{RESET}")

    ln = "\u2500" * W
    print(f"\n{ln}")
    print(f"  {tag}  {DIM}{_dur(elapsed)}{RESET}")
    print(f"{ln}")

    # Nodes
    node_events = e.get("node_events", [])
    n_fired = sum(1 for _, s, _ in node_events if s == "fired")
    n_reused = sum(1 for _, s, _ in node_events if s == "reused")
    n_failed = sum(1 for _, s, _ in node_events if s == "failed")
    parts: list[str] = []
    if n_fired:
        parts.append(f"{n_fired} fired")
    if n_reused:
        parts.append(f"{n_reused} reused")
    if n_failed:
        parts.append(f"{n_failed} failed")
    sep = f"{DIM} \u00b7 {RESET}"
    node_summary = sep.join(parts) if parts else "\u2013"
    print(f"  {DIM}nodes{RESET}     {node_summary}")

    # Artifacts
    artifacts = e.get("artifacts", {})
    n_sealed = sum(1 for v in artifacts.values() if v.get("status") == "sealed")
    n_produced = sum(
        1 for v in artifacts.values() if v.get("status") == "produced"
    )
    n_total = n_sealed + n_produced
    if n_total:
        extra = f" {DIM}\u00b7{RESET} {n_produced} new" if n_produced else ""
        print(f"  {DIM}artifacts{RESET} {n_total} sealed{extra}")

    # Oracle
    oracle_events = e.get("oracle_events", [])
    if oracle_events:
        nc = len(oracle_events)
        ti = sum(ev[2] for ev in oracle_events)
        to = sum(ev[3] for ev in oracle_events)
        tc = sum(ev[4] for ev in oracle_events)
        print(
            f"  {DIM}oracle{RESET}    {nc} calls"
            f" {DIM}\u00b7{RESET} {_tok(ti)} in"
            f" {DIM}\u00b7{RESET} {_tok(to)} out"
            f" {DIM}\u00b7{RESET} {_cost(tc)}"
        )

    # Tools
    tool_count = e.get("tool_events_count", 0)
    if tool_count:
        print(f"  {DIM}tools{RESET}     {tool_count} calls")

    # Fuel
    print(f"  {DIM}fuel{RESET}      {fuel_left}/{fuel_total}")
    print(f"{ln}\n", flush=True)


def _on_rule_start(e: dict[str, Any]) -> None:
    print(f"  {YELLOW}\u25b8{RESET} {BOLD}{e['rule']}{RESET}", flush=True)
    reason = e.get("stale_reason")
    if reason:
        print(f"    {DIM}stale: {reason}{RESET}", flush=True)


def _on_rule_done(e: dict[str, Any]) -> None:
    el = e.get("elapsed", 0.0)
    print(
        f"  {GREEN}\u2713{RESET} {e['rule']}  {DIM}{_dur(el)}{RESET}",
        flush=True,
    )


def _on_rule_sealed(e: dict[str, Any]) -> None:
    parent = e.get("reused_by")
    if parent:
        print(
            f"  {DIM}\u25cf {e['rule']}  reused by {parent}{RESET}",
            flush=True,
        )
    else:
        print(f"  {DIM}\u25cf {e['rule']}{RESET}", flush=True)


def _on_rule_halted(e: dict[str, Any]) -> None:
    reason = e.get("reason", "")
    print(
        f"  {RED}\u2717{RESET} {BOLD}{e['rule']}{RESET}  {DIM}{reason}{RESET}",
        flush=True,
    )


def _on_oracle_start(e: dict[str, Any]) -> None:
    label = e.get("oracle", "oracle")
    prompt = e.get("prompt_preview", "")
    short = ""
    if prompt:
        short = prompt.replace("\n", " ")
        if len(short) > 50:
            short = short[:50] + "\u2026"
    print(
        f"    {CYAN}\u2192{RESET} {DIM}{label}{RESET}"
        + (f'  {DIM}"{short}"{RESET}' if short else ""),
        flush=True,
    )


def _on_oracle_done(e: dict[str, Any]) -> None:
    parts: list[str] = []
    ti = e.get("tokens_in", 0)
    to = e.get("tokens_out", 0)
    if ti or to:
        parts.append(f"{_tok(ti)} in")
        parts.append(f"{_tok(to)} out")
    cost = e.get("cost_usd", 0.0)
    if cost > 0:
        parts.append(_cost(cost))
    elapsed = e.get("elapsed", 0.0)
    if elapsed > 0:
        parts.append(_dur(elapsed))
    if parts:
        sep = " \u00b7 "
        print(f"      {DIM}{sep.join(parts)}{RESET}", flush=True)


def _on_tool_call(e: dict[str, Any]) -> None:
    args_str = str(e.get("args", {}))
    if len(args_str) > 80:
        args_str = args_str[:77] + "..."
    print(
        f"    {CYAN}\u2192{RESET} {e['tool']}  {DIM}{args_str}{RESET}",
        flush=True,
    )


def _on_tool_result(e: dict[str, Any]) -> None:
    out = e.get("result_preview", "")
    elapsed = e.get("elapsed", 0.0)
    parts: list[str] = []
    if out:
        parts.append(out)
    if elapsed > 0:
        parts.append(_dur(elapsed))
    if parts:
        sep = "  " if len(parts) > 1 else ""
        print(f"      {DIM}{sep.join(parts)}{RESET}", flush=True)


def _on_trial_branch(e: dict[str, Any]) -> None:
    parts = [f"\u22a2 {e['branch']}"]
    score = e.get("score")
    if score is not None:
        parts.append(f"score {score:.2f}")
    elapsed = e.get("elapsed", 0.0)
    if elapsed > 0:
        parts.append(_dur(elapsed))
    cost = e.get("cost_usd", 0.0)
    if cost > 0:
        parts.append(_cost(cost))
    sep = " \u00b7 "
    print(f"    {DIM}{sep.join(parts)}{RESET}", flush=True)


def _on_trial_note(e: dict[str, Any]) -> None:
    print(f"    {DIM}{e.get('message', '')}{RESET}", flush=True)


def _on_trial_verdict(e: dict[str, Any]) -> None:
    print(
        f"    {CYAN}\u22a3{RESET} {DIM}verdict \u2192{RESET} "
        f"{BOLD}{e['winner']}{RESET}",
        flush=True,
    )


def _on_sealed_manifest(e: dict[str, Any]) -> None:
    artifacts = e.get("artifacts", {})
    if not artifacts:
        return
    print(f"\n  {DIM}sealed artifacts{RESET}")
    for path in sorted(artifacts):
        a = artifacts[path]
        h = _shorthash(a.get("hash"))
        print(f"    {DIM}{path:<24s} {h}{RESET}", flush=True)


# -- Handler dispatch table ---------------------------------------------------

_HANDLERS: dict[str, Any] = {
    "build_start": _on_build_start,
    "build_end": _on_build_end,
    "rule_start": _on_rule_start,
    "rule_done": _on_rule_done,
    "rule_sealed": _on_rule_sealed,
    "rule_halted": _on_rule_halted,
    "oracle_start": _on_oracle_start,
    "oracle_done": _on_oracle_done,
    "tool_call": _on_tool_call,
    "tool_result": _on_tool_result,
    "trial_branch": _on_trial_branch,
    "trial_note": _on_trial_note,
    "trial_verdict": _on_trial_verdict,
    "sealed_manifest": _on_sealed_manifest,
}
