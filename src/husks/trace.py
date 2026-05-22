"""
trace.py — build-system trace output (v2)

Five-line summary: nodes · artifacts · oracle · fuel
Staleness reasons, diamond annotations, trial scores,
sealed artifact manifest.

Pretty-print is one renderer over a JSONL event stream.
"""

import json
import sys
import time

# ── ANSI ────────────────────────────────────────────────────

DIM    = "\033[2m"
BOLD   = "\033[1m"
RESET  = "\033[0m"
GREEN  = "\033[32m"
YELLOW = "\033[33m"
RED    = "\033[31m"
CYAN   = "\033[36m"

if not sys.stdout.isatty():
    DIM = BOLD = RESET = GREEN = YELLOW = RED = CYAN = ""

W = 60


# ── Formatting ──────────────────────────────────────────────

def _tok(n):
    if n < 1000: return str(n)
    return f"{n / 1000:.1f}k"

def _dur(s):
    if s < 1.0:
        ms = s * 1000
        return "<1ms" if ms < 1 else f"{ms:.0f}ms"
    if s < 60: return f"{s:.2f}s"
    m, sec = divmod(s, 60)
    return f"{int(m)}m{sec:04.1f}s"

def _cost(usd):
    return f"${usd:.4f}"

def _shorthash(h):
    if not h or h.startswith("0:"): return "–"
    return h[:10]


# ── State ───────────────────────────────────────────────────

_build_name  = ""
_build_fuel  = 0
_build_t0    = 0.0

_events        = []     # JSONL backing store
_rule_timers   = {}     # name → start time
_rule_stack    = []     # parent tracking for diamond annotations
_node_events   = []     # (name, status, elapsed)   status: fired|reused|failed
_oracle_events = []     # (rule, name, tok_in, tok_out, cost, elapsed)
_tool_events   = []     # (rule, name, args_str, result_str, raw_args)
_artifacts     = {}     # path → {"hash": str, "rule": str, "status": sealed|produced}


def reset():
    global _build_name, _build_fuel, _build_t0
    _build_name = _build_fuel = ""
    _build_t0 = 0.0
    _events.clear()
    _rule_timers.clear()
    _rule_stack.clear()
    _node_events.clear()
    _oracle_events.clear()
    _tool_events.clear()
    _artifacts.clear()


def _emit(event):
    """Append a structured event to the JSONL stream."""
    event["ts"] = time.time()
    _events.append(event)


# ── Build ───────────────────────────────────────────────────

def build_start(name, fuel, site, oracle_model=None):
    reset()
    global _build_name, _build_fuel, _build_t0
    _build_name = name
    _build_fuel = fuel
    _build_t0   = time.time()

    _emit({"event": "build_start", "name": name, "fuel": fuel, "site": site})

    bar = "═" * W
    print(f"\n{BOLD}{bar}{RESET}")
    print(f"  {BOLD}{name}{RESET}")
    print(f"  {DIM}site{RESET}  {site}")
    ln = f"  {DIM}fuel{RESET}  {fuel}"
    if oracle_model:
        ln += f"    {DIM}oracle{RESET}  {oracle_model}"
    print(ln)
    print(f"{BOLD}{bar}{RESET}\n", flush=True)


def build_end(status, fuel_left, fuel_total):
    elapsed = time.time() - _build_t0
    _emit({"event": "build_end", "status": status,
           "fuel_left": fuel_left, "elapsed": elapsed})

    tag = {"committed": f"{GREEN}{BOLD}committed{RESET}",
           "halted":    f"{RED}{BOLD}halted{RESET}",
           }.get(status, f"{YELLOW}{BOLD}{status}{RESET}")

    ln = "─" * W
    print(f"\n{ln}")
    print(f"  {tag}  {DIM}{_dur(elapsed)}{RESET}")
    print(f"{ln}")

    # nodes
    n_fired  = sum(1 for _, s, _ in _node_events if s == "fired")
    n_reused = sum(1 for _, s, _ in _node_events if s == "reused")
    n_failed = sum(1 for _, s, _ in _node_events if s == "failed")

    parts = []
    if n_fired:  parts.append(f"{n_fired} fired")
    if n_reused: parts.append(f"{n_reused} reused")
    if n_failed: parts.append(f"{n_failed} failed")
    print(f"  {DIM}nodes{RESET}     {(f'{DIM} · {RESET}'.join(parts)) if parts else '–'}")

    # artifacts
    n_sealed = sum(1 for v in _artifacts.values() if v["status"] == "sealed")
    n_produced = sum(1 for v in _artifacts.values() if v["status"] == "produced")
    n_total = n_sealed + n_produced
    if n_total:
        print(f"  {DIM}artifacts{RESET} {n_total} sealed{f' {DIM}·{RESET} {n_produced} new' if n_produced else ''}")

    # oracle
    if _oracle_events:
        nc = len(_oracle_events)
        ti = sum(e[2] for e in _oracle_events)
        to = sum(e[3] for e in _oracle_events)
        tc = sum(e[4] for e in _oracle_events)
        print(
            f"  {DIM}oracle{RESET}    {nc} calls"
            f" {DIM}·{RESET} {_tok(ti)} in"
            f" {DIM}·{RESET} {_tok(to)} out"
            f" {DIM}·{RESET} {_cost(tc)}"
        )

    # tools
    if _tool_events:
        nt = len(_tool_events)
        print(f"  {DIM}tools{RESET}     {nt} calls")

    # fuel
    print(f"  {DIM}fuel{RESET}      {fuel_left}/{fuel_total}")
    print(f"{ln}\n", flush=True)


# ── Rules ───────────────────────────────────────────────────

def push_rule(name):
    """Track parent rule for diamond annotations."""
    _rule_stack.append(name)

def pop_rule():
    if _rule_stack:
        _rule_stack.pop()

def _parent():
    return _rule_stack[-1] if _rule_stack else None


def rule_start(name, stale_reason=None):
    _rule_timers[name] = time.time()
    _emit({"event": "rule_start", "rule": name, "stale_reason": stale_reason})
    print(f"  {YELLOW}▸{RESET} {BOLD}{name}{RESET}", flush=True)
    if stale_reason:
        print(f"    {DIM}stale: {stale_reason}{RESET}", flush=True)


def rule_done(name, outputs=None, output_hashes=None):
    el = time.time() - _rule_timers.pop(name, time.time())
    _node_events.append((name, "fired", el))
    _emit({"event": "rule_done", "rule": name, "elapsed": el})
    # track artifacts
    if outputs and output_hashes:
        for o, h in zip(outputs, output_hashes):
            _artifacts[o] = {"hash": h, "rule": name, "status": "produced"}
    print(f"  {GREEN}✓{RESET} {name}  {DIM}{_dur(el)}{RESET}", flush=True)


def rule_sealed(name, outputs=None, output_hashes=None):
    parent = _parent()
    _node_events.append((name, "reused", 0.0))
    _emit({"event": "rule_sealed", "rule": name, "reused_by": parent})
    # track artifacts as sealed
    if outputs and output_hashes:
        for o, h in zip(outputs, output_hashes):
            if o not in _artifacts:
                _artifacts[o] = {"hash": h, "rule": name, "status": "sealed"}
    if parent:
        print(f"  {DIM}● {name}  reused by {parent}{RESET}", flush=True)
    else:
        print(f"  {DIM}● {name}{RESET}", flush=True)


def rule_halted(name, reason):
    el = time.time() - _rule_timers.pop(name, time.time())
    _node_events.append((name, "failed", el))
    _emit({"event": "rule_halted", "rule": name, "reason": reason, "elapsed": el})
    print(f"  {RED}✗{RESET} {BOLD}{name}{RESET}  {DIM}{reason}{RESET}", flush=True)


# ── Oracle ──────────────────────────────────────────────────

def oracle_start(rule_name, oracle_name=None, prompt=None):
    label = oracle_name or "oracle"
    _emit({"event": "oracle_start", "rule": rule_name, "oracle": label})
    short = ""
    if prompt:
        short = prompt[:50].replace("\n", " ")
        if len(prompt) > 50: short += "…"
    print(
        f"    {CYAN}→{RESET} {DIM}{label}{RESET}"
        + (f"  {DIM}\"{short}\"{RESET}" if short else ""),
        flush=True,
    )

def oracle_done(rule_name, oracle_name=None,
                tokens_in=0, tokens_out=0, cost_usd=0.0, elapsed=0.0):
    label = oracle_name or "oracle"
    _oracle_events.append((rule_name, label, tokens_in, tokens_out, cost_usd, elapsed))
    _emit({"event": "oracle_done", "rule": rule_name, "oracle": label,
           "tokens_in": tokens_in, "tokens_out": tokens_out,
           "cost_usd": cost_usd, "elapsed": elapsed})
    parts = []
    if tokens_in or tokens_out:
        parts.append(f"{_tok(tokens_in)} in")
        parts.append(f"{_tok(tokens_out)} out")
    if cost_usd > 0: parts.append(_cost(cost_usd))
    if elapsed > 0: parts.append(_dur(elapsed))
    if parts:
        print(f"      {DIM}{f' · '.join(parts)}{RESET}", flush=True)


# ── Tools ──────────────────────────────────────────────────

def tool_call(rule_name, name, args):
    args_str = str(args)
    if len(args_str) > 80:
        args_str = args_str[:77] + "..."
    _tool_events.append((rule_name, name, args_str, None, args))
    _emit({"event": "tool_call", "rule": rule_name, "tool": name, "args": args})
    print(f"    {CYAN}→{RESET} {name}  {DIM}{args_str}{RESET}", flush=True)


def tool_result(name, result):
    out_str = str(result)
    if len(out_str) > 120:
        out_str = out_str[:117] + "..."
    # update last matching tool event with result
    for i in range(len(_tool_events) - 1, -1, -1):
        if _tool_events[i][1] == name and _tool_events[i][3] is None:
            _tool_events[i] = (*_tool_events[i][:3], out_str, _tool_events[i][4])
            break
    _emit({"event": "tool_result", "tool": name, "result_preview": out_str})
    print(f"      {DIM}{out_str}{RESET}", flush=True)


# ── Trial ───────────────────────────────────────────────────

def trial_branch(rule_name, branch_name, score=None,
                 tokens_in=0, tokens_out=0, cost_usd=0.0, elapsed=0.0):
    _emit({"event": "trial_branch", "rule": rule_name,
           "branch": branch_name, "score": score,
           "tokens_in": tokens_in, "tokens_out": tokens_out,
           "cost_usd": cost_usd, "elapsed": elapsed})
    parts = [f"⊢ {branch_name}"]
    if score is not None: parts.append(f"score {score:.2f}")
    if elapsed > 0: parts.append(_dur(elapsed))
    if cost_usd > 0: parts.append(_cost(cost_usd))
    print(f"    {DIM}{' · '.join(parts)}{RESET}", flush=True)


def trial_note(rule_name, message):
    """Lightweight informational event for trial-level decisions."""
    _emit({"event": "trial_note", "rule": rule_name, "message": message})
    print(f"    {DIM}{message}{RESET}", flush=True)


def trial_verdict(rule_name, winner_name, scores=None):
    _emit({"event": "trial_verdict", "rule": rule_name,
           "winner": winner_name, "scores": scores})
    print(
        f"    {CYAN}⊣{RESET} {DIM}verdict →{RESET} {BOLD}{winner_name}{RESET}",
        flush=True,
    )


# ── Sealed artifact manifest ────────────────────────────────

def sealed_manifest():
    """Print the final artifact table."""
    if not _artifacts:
        return
    print(f"\n  {DIM}sealed artifacts{RESET}")
    for path in sorted(_artifacts):
        a = _artifacts[path]
        h = _shorthash(a["hash"])
        print(f"    {DIM}{path:<24s} {h}{RESET}", flush=True)
    _emit({"event": "sealed_manifest",
           "artifacts": {p: {"hash": a["hash"], "rule": a["rule"]}
                         for p, a in _artifacts.items()}})


# ── Export ──────────────────────────────────────────────────

def to_jsonl():
    """Return the full event stream as a JSONL string."""
    return "\n".join(json.dumps(e, default=str) for e in _events) + "\n"


def to_dict():
    elapsed = time.time() - _build_t0 if _build_t0 else 0
    return {
        "build": _build_name,
        "fuel_total": _build_fuel,
        "elapsed_s": round(elapsed, 4),
        "events": list(_events),
        "nodes": [
            {"name": n, "status": s, "elapsed_s": round(e, 4)}
            for n, s, e in _node_events
        ],
        "artifacts": dict(_artifacts),
        "totals": {
            "nodes_fired":  sum(1 for _, s, _ in _node_events if s == "fired"),
            "nodes_reused": sum(1 for _, s, _ in _node_events if s == "reused"),
            "nodes_failed": sum(1 for _, s, _ in _node_events if s == "failed"),
            "tool_calls":   len(_tool_events),
            "oracle_calls": len(_oracle_events),
            "tokens_in":  sum(e[2] for e in _oracle_events),
            "tokens_out": sum(e[3] for e in _oracle_events),
            "cost_usd":   round(sum(e[4] for e in _oracle_events), 6),
        },
    }


# ── Convergence diagnostics ──────────────────────────────

def _read_history(site, rule_name):
    """Read JSONL history entries for a rule. Returns list of dicts."""
    from pathlib import Path
    p = Path(site) / ".traces" / f"{rule_name}.history.jsonl"
    if not p.exists():
        return []
    entries = []
    for line in p.read_text().strip().splitlines():
        if line.strip():
            entries.append(json.loads(line))
    return entries


def declared_vs_traced(plan, site):
    """Diff declared inputs against traced_reads from the most recent history.

    Returns a dict: {rule_name: [paths in traces but not in declared inputs]}.
    """
    result = {}
    for r in plan.get("rules", []):
        rname = r["name"]
        declared = set(r.get("inputs", []))
        entries = _read_history(site, rname)
        if not entries:
            continue
        latest = entries[-1]
        traced = set(latest.get("traced_reads", []))
        undeclared = sorted(traced - declared)
        if undeclared:
            result[rname] = undeclared
    return result


def convergence_summary(rule_name, site, n=5):
    """Analyze the last N history entries for a rule.

    Returns a dict with:
      - fuel_trend: "falling", "flat", or "rising"
      - prompt_trend: "falling", "flat", "rising", or null
      - output_stable: bool (all output hashes identical across N runs)
      - classification: "converging", "prompt-loading", "stable", or "volatile"
      - entries: the raw entries used
    """
    entries = _read_history(site, rule_name)
    if not entries:
        return {"fuel_trend": None, "prompt_trend": None,
                "output_stable": None, "classification": "no-data",
                "entries": []}

    recent = entries[-n:]

    # fuel trend
    fuels = [e.get("fuel_consumed", 0) for e in recent]
    fuel_trend = _trend(fuels)

    # prompt length trend
    prompts = [e.get("prompt_length") for e in recent]
    if all(p is None for p in prompts):
        prompt_trend = None
    else:
        prompt_trend = _trend([p or 0 for p in prompts])

    # output stability
    hashes = [tuple(e.get("output_hashes", [])) for e in recent]
    output_stable = len(set(hashes)) <= 1 if hashes else False

    # classification
    if output_stable and len(recent) > 1:
        classification = "stable"
    elif fuel_trend in ("falling", "flat") and prompt_trend in ("falling", "flat", None):
        classification = "converging"
    elif fuel_trend in ("falling", "flat") and prompt_trend == "rising":
        classification = "prompt-loading"
    else:
        classification = "volatile"

    return {
        "fuel_trend": fuel_trend,
        "prompt_trend": prompt_trend,
        "output_stable": output_stable,
        "classification": classification,
        "entries": recent,
    }


def _trend(values):
    """Classify a sequence as 'falling', 'rising', or 'flat'."""
    if len(values) <= 1:
        return "flat"
    diffs = [values[i+1] - values[i] for i in range(len(values) - 1)]
    if all(d <= 0 for d in diffs):
        if all(d == 0 for d in diffs):
            return "flat"
        return "falling"
    if all(d >= 0 for d in diffs):
        return "rising"
    return "flat"  # mixed — no clear direction
