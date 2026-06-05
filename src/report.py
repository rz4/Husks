"""L6 inspect -- Manifests, reports, convergence analysis, dependency graphs.

Merges manifest.py, report.py, graph.py, residue.py, convergence.py from
the liquid beta into a single hardened module.  Named report.py (not
inspect.py) to avoid shadowing Python's stdlib inspect module.

Dependencies: kernel (L0) + stdlib (json, hashlib, pathlib, dataclasses).
No husks.utils imports.  No ANSI color coupling (plain text only).
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional

from kernel import recompute_root

# ── Type aliases ─────────────────────────────────────────────────

Design = dict[str, Any]
Store = dict[str, Any]

# ── §1 Schema validation ────────────────────────────────────────

SUPPORTED_MANIFEST_SCHEMAS = {"husks.build.manifest.v1"}
SUPPORTED_SEAL_VERSIONS = {1}


def _validate_schema(
    data: dict,
    version_field: str,
    version_name: str,
    supported: set,
    required: list[str],
    type_checks: dict[str, type] | None = None,
) -> tuple[bool, str | None]:
    """Generic schema validation.  Returns (valid, error_msg)."""
    v = data.get(version_field)
    if v is None:
        return False, f"missing required field: {version_field}"
    if version_field == "v" and not isinstance(v, int):
        return False, f"field '{version_field}' must be an integer"
    if v not in supported:
        return False, f"unsupported {version_name}: {v}"
    for f in required:
        if f not in data:
            return False, f"missing required field: {f}"
    if type_checks:
        for f, t in type_checks.items():
            if f in data and not isinstance(data[f], t):
                return False, f"field '{f}' must be a {t.__name__}"
    return True, None


def validate_manifest_schema(data: dict) -> tuple[bool, str | None]:
    """Validate manifest v1 schema.  Returns (valid, error_msg)."""
    return _validate_schema(
        data, "schema", "manifest schema", SUPPORTED_MANIFEST_SCHEMAS,
        ["name", "root", "site", "run_id", "rules"], {"rules": list},
    )


def validate_seal_schema(data: dict) -> tuple[bool, str | None]:
    """Validate seal v1 schema.  Returns (valid, error_msg)."""
    return _validate_schema(
        data, "v", "seal version", SUPPORTED_SEAL_VERSIONS,
        ["seal", "recipe_digest", "inputs"], {"inputs": dict, "outputs": dict},
    )


# ── §2 Manifest I/O ─────────────────────────────────────────────

def read_manifest(site: str) -> dict | None:
    """Read .traces/build.manifest.json.  None if missing/invalid."""
    p = Path(site) / ".traces" / "build.manifest.json"
    if not p.exists():
        return None
    try:
        data = json.loads(p.read_text())
        ok, _ = validate_manifest_schema(data)
        return data if ok else None
    except Exception:
        return None


def read_seal(site: str, rule_name: str) -> dict | None:
    """Read .traces/{rule_name}.seal.  None if missing/invalid."""
    p = Path(site) / ".traces" / f"{rule_name}.seal"
    if not p.exists():
        return None
    try:
        data = json.loads(p.read_text())
        ok, _ = validate_seal_schema(data)
        return data if ok else None
    except Exception:
        return None


def read_trial_report(site: str, rule_name: str) -> dict | None:
    """Read .traces/{rule_name}.trial.json.  None if missing."""
    p = Path(site) / ".traces" / f"{rule_name}.trial.json"
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text())
    except Exception:
        return None


# ── §3 Freshness computation ────────────────────────────────────

def file_hash(path: str) -> str | None:
    """SHA-256 hex of file contents, or None if missing."""
    p = Path(path)
    return hashlib.sha256(p.read_bytes()).hexdigest() if p.is_file() else None


def compute_rule_state(
    site: str, rule: dict, seal: dict | None,
) -> tuple[str, str | None]:
    """Compute freshness state for a rule.

    Returns (state, reason) where state is one of:
    fresh, stale, missing, dirty.
    """
    outputs = rule.get("outputs", [])
    for o in outputs:
        if not (Path(site) / o).exists():
            return "missing", f"output_missing:{o}"
    if seal is None:
        return "stale", "no_seal"
    for inp, sealed_h in seal.get("inputs", {}).items():
        cur = file_hash(str(Path(site) / inp)) or "absent"
        if cur != sealed_h:
            return "stale", f"input_changed:{inp}"
    for o in outputs:
        cur = file_hash(str(Path(site) / o)) or "absent"
        if cur != seal.get("outputs", {}).get(o, ""):
            return "dirty", f"output_hash_changed:{o}"
    return "fresh", None


def compute_rule_states(site: str, manifest: dict) -> list[dict[str, Any]]:
    """Compute freshness for every rule in a manifest."""
    result = []
    for rule in manifest.get("rules", []):
        seal = read_seal(site, rule["name"])
        state, reason = compute_rule_state(site, rule, seal)
        result.append({"name": rule["name"], "kind": rule["kind"],
                        "state": state, "reason": reason})
    return result


def compute_artifact_states(site: str, manifest: dict) -> list[dict[str, Any]]:
    """Compute per-artifact state (fresh, modified, missing)."""
    results = []
    for rule in manifest.get("rules", []):
        seal = read_seal(site, rule["name"])
        prior = seal.get("outputs", {}) if seal else {}
        for o in rule.get("outputs", []):
            cur = file_hash(str(Path(site) / o))
            sealed = prior.get(o)
            if cur is None:
                state = "missing"
            elif sealed is None or cur != sealed:
                state = "modified"
            else:
                state = "fresh"
            results.append({"path": o, "rule": rule["name"], "state": state,
                            "sealed_hash": sealed, "current_hash": cur})
    return results


# ── §4 Artifact comparison ──────────────────────────────────────

def compare_artifacts(
    site_a: str, site_b: str, *,
    check_roots: bool = True, check_hashes: bool = True,
) -> dict[str, Any]:
    """Compare two sites for equivalence.  Returns dict with equivalent, differences, details."""
    diffs: list[str] = []
    details: dict[str, Any] = {}
    ma, mb = read_manifest(site_a), read_manifest(site_b)
    if ma is None:
        diffs.append(f"site A missing manifest: {site_a}")
    if mb is None:
        diffs.append(f"site B missing manifest: {site_b}")
    if ma is None or mb is None:
        return {"equivalent": False, "differences": diffs, "details": {}}

    if check_roots:
        ra, rb = ma.get("root"), mb.get("root")
        details["root_a"], details["root_b"] = ra, rb
        if ra != rb:
            diffs.append(f"build roots differ: {(ra or '')[:16]}... vs {(rb or '')[:16]}...")
        for label, m, site in [("A", ma, site_a), ("B", mb, site_b)]:
            name = m.get("name")
            root = m.get("root")
            if name and root:
                hp = Path(site) / f"{name}.husk"
                if hp.exists():
                    try:
                        recomp = recompute_root(hp.read_bytes(), site)
                        details[f"root_{label.lower()}_valid"] = (recomp == root)
                        if recomp != root:
                            diffs.append(f"site {label} root invalid (recomputed {recomp[:16]}...)")
                    except Exception as e:
                        details[f"root_{label.lower()}_valid"] = False
                        diffs.append(f"site {label} root verification failed: {e}")

    if check_hashes:
        oa, ob = {}, {}
        for m, site, out in [(ma, site_a, oa), (mb, site_b, ob)]:
            for rule in m.get("rules", []):
                seal = read_seal(site, rule["name"])
                if seal and "outputs" in seal:
                    out.update(seal["outputs"])
        details["outputs_a"], details["outputs_b"] = oa, ob
        for o in sorted(set(oa) | set(ob)):
            ha, hb = oa.get(o), ob.get(o)
            if ha != hb:
                diffs.append(
                    f"output '{o}' differs: "
                    f"{(ha or 'missing')[:16]}... vs {(hb or 'missing')[:16]}..."
                )

    return {"equivalent": len(diffs) == 0, "differences": diffs, "details": details}


# ── §5 History & Convergence ────────────────────────────────────

def read_history(site: str, rule_name: str) -> list[dict[str, Any]]:
    """Read JSONL history entries for a rule.  Empty list if none."""
    p = Path(site) / ".traces" / f"{rule_name}.history.jsonl"
    if not p.exists():
        return []
    entries = []
    for line in p.read_text().strip().splitlines():
        if line.strip():
            entries.append(json.loads(line))
    return entries


def _trend(values: list[int | float]) -> str:
    """Classify sequence as 'falling', 'rising', or 'flat'."""
    if len(values) <= 1:
        return "flat"
    diffs = [values[i + 1] - values[i] for i in range(len(values) - 1)]
    if all(d <= 0 for d in diffs):
        return "flat" if all(d == 0 for d in diffs) else "falling"
    if all(d >= 0 for d in diffs):
        return "rising"
    return "flat"


def convergence_summary(
    rule_name: str, site: str, n: int = 5,
) -> dict[str, Any]:
    """Analyze last n history entries.  Returns classification + trends."""
    entries = read_history(site, rule_name)
    if not entries:
        return {"fuel_trend": None, "prompt_trend": None,
                "output_stable": None, "classification": "no-data", "entries": []}
    recent = entries[-n:]
    fuels = [e.get("fuel_consumed", 0) for e in recent]
    fuel_trend = _trend(fuels)
    prompts = [e.get("prompt_length") for e in recent]
    prompt_trend = None if all(p is None for p in prompts) else _trend([p or 0 for p in prompts])
    hashes = [tuple(e.get("output_hashes", [])) for e in recent]
    output_stable = len(set(hashes)) <= 1 if hashes else False
    if output_stable and len(recent) > 1:
        classification = "stable"
    elif fuel_trend in ("falling", "flat") and prompt_trend in ("falling", "flat", None):
        classification = "converging"
    elif fuel_trend in ("falling", "flat") and prompt_trend == "rising":
        classification = "prompt-loading"
    else:
        classification = "volatile"
    return {"fuel_trend": fuel_trend, "prompt_trend": prompt_trend,
            "output_stable": output_stable, "classification": classification,
            "entries": recent}


def declared_vs_traced(design: Design, site: str) -> dict[str, list[str]]:
    """Diff declared inputs vs actual traced reads.  Returns {rule: [undeclared]}."""
    result: dict[str, list[str]] = {}
    for r in design.get("rules", []):
        declared = set(r.get("inputs", []))
        entries = read_history(site, r["name"])
        if not entries:
            continue
        traced = set(entries[-1].get("traced_reads", []))
        undeclared = sorted(traced - declared)
        if undeclared:
            result[r["name"]] = undeclared
    return result


# ── §6 Dependency graph ─────────────────────────────────────────

def extract_edges(design: Design) -> tuple[list[dict], list[tuple[str, str]]]:
    """Extract nodes and edges from design rules.

    Edges inferred from input/output overlap.
    Returns (nodes, edges) where edges are (producer, consumer) tuples.
    """
    rules = design.get("rules", [])
    nodes, edges = [], []
    out_to_rule: dict[str, str] = {}
    for r in rules:
        if r.get("kind", "") in ("action", "oracle", "trial"):
            for o in r.get("outputs", []):
                out_to_rule[o] = r["name"]
    for r in rules:
        kind, name = r.get("kind", ""), r.get("name", "?")
        nodes.append({"name": name, "kind": kind, "fuel": r.get("fuel")})
        if kind in ("action", "oracle", "trial"):
            for inp in r.get("inputs", []):
                producer = out_to_rule.get(inp)
                if producer:
                    edges.append((producer, name))
        if kind == "cond":
            for branch in ("then", "else"):
                ref = r.get(branch)
                if ref:
                    edges.append((name, ref))
        if kind == "let":
            bind = r.get("bind")
            if bind:
                edges.append((bind, name))
    return nodes, edges


def render_graph(
    design: Design, fmt: str = "text",
    site: str | None = None, root_hash: str | None = None,
) -> str:
    """Render dependency graph in requested format (text, mermaid, dot, json)."""
    nodes, edges = extract_edges(design)
    states: dict[str, str] = {}
    if site:
        try:
            m = read_manifest(site)
            if m:
                for rs in compute_rule_states(site, m):
                    states[rs["name"]] = rs["state"]
        except Exception:
            pass
    t = design.get("targets", design.get("target"))
    targets = set(t) if isinstance(t, list) else ({t} if isinstance(t, str) else set())
    if fmt == "mermaid":
        return _render_mermaid(nodes, edges, states, targets)
    if fmt == "dot":
        return _render_dot(nodes, edges, states, targets)
    if fmt == "json":
        return _render_json(nodes, edges, states)
    return _render_text(nodes, edges, states, targets, design, root_hash)


_STATE_SYM = {"fresh": "■", "stale": "▸", "missing": "✗", "dirty": "!", "failed": "✗"}
_DEFAULT_SYM = "□"
_TRIAL_SYM = "◇"


def _state_symbol(state: str | None) -> str:
    return _STATE_SYM.get(state or "", "")


def _render_text(
    nodes: list[dict], edges: list[tuple[str, str]],
    states: dict[str, str], targets: set[str],
    design: Design, root_hash: str | None = None,
) -> str:
    """Bordered DAG tree with connectors."""
    lines: list[str] = []
    name = design.get("name", "?")
    fuel = design.get("fuel", "?")
    hash_label = f"husk:{root_hash[:12]}" if root_hash else "husk:none"
    preamble = f" {name}  \u26a1{fuel}"
    min_w = max(len(preamble) + len(hash_label) + 4, 40)
    gap = max(2, min_w - len(preamble) - len(hash_label) - 1)
    lines.append("\u2500" * (min_w + 1))
    lines.append(f"{preamble}{' ' * gap}{hash_label}")
    lines.append("\u2500" * (min_w + 1))

    node_map = {n["name"]: n for n in nodes}
    deps: dict[str, list[str]] = {}
    for src, dst in edges:
        deps.setdefault(dst, []).append(src)

    targets_list = [t for t in targets if t in node_map]
    if not targets_list:
        has_consumer = {s for s, _ in edges}
        targets_list = [n["name"] for n in nodes if n["name"] not in has_consumer]
    if not targets_list:
        targets_list = [n["name"] for n in nodes]

    # Diamond detection
    parent_count: dict[str, int] = {}
    def _count(n: str, seen: set[str]) -> None:
        if n in seen:
            return
        seen.add(n)
        for c in deps.get(n, []):
            parent_count[c] = parent_count.get(c, 0) + 1
            _count(c, seen)
    for t in targets_list:
        _count(t, set())
    diamonds = {n for n, c in parent_count.items() if c > 1}
    diamond_visits: dict[str, int] = {n: 0 for n in diamonds}
    visited: set[str] = set()

    def _node_line(n: str) -> str:
        nd = node_map.get(n)
        kind = nd["kind"] if nd else "?"
        st = states.get(n, "")
        sym = (_STATE_SYM.get(st, _DEFAULT_SYM) if st
               else (_TRIAL_SYM if kind == "trial" else _DEFAULT_SYM))
        fuel_tag = f"  \u26a1{nd['fuel']}" if nd and nd.get("fuel") is not None and nd["fuel"] != design.get("fuel") else ""
        target_tag = "  \u25c0" if n in targets else ""
        return f"{sym} {n}  ({kind}){fuel_tag}{target_tag}"

    def _walk(n: str, prefix: str, is_last: bool, depth: int) -> None:
        if depth == 0:
            conn, cpfx = "", prefix
        elif is_last:
            conn, cpfx = "\u2514\u2500 ", prefix + "   "
        else:
            conn, cpfx = "\u251c\u2500 ", prefix + "\u2502  "
        lines.append(f" {prefix}{conn}{_node_line(n)}")
        visited.add(n)
        children = deps.get(n, [])
        for i, child in enumerate(children):
            last = (i == len(children) - 1)
            if child in diamonds:
                diamond_visits[child] += 1
                if diamond_visits[child] < parent_count[child]:
                    lines.append(f" {cpfx}{'\u2514\u2500\u2510' if last else '\u251c\u2500\u2510'}")
                    continue
                lines.append(f" {cpfx}{'\u2514\u2500\u2524' if last else '\u251c\u2500\u2524'}")
                _walk(child, cpfx + ("   " if last else "\u2502  "), True, depth + 1)
                continue
            if child in visited:
                lines.append(f" {cpfx}{'\u2514\u2500 ' if last else '\u251c\u2500 '}{child}  (ref)")
                continue
            _walk(child, cpfx, last, depth + 1)

    for t in targets_list:
        _walk(t, "", True, 0)
    for n in nodes:
        if n["name"] not in visited:
            _walk(n["name"], "", True, 0)
    lines.append("\u2500" * (min_w + 1))
    return "\n".join(lines)


def _render_mermaid(
    nodes: list[dict], edges: list[tuple[str, str]],
    states: dict[str, str], targets: set[str],
) -> str:
    lines = ["flowchart TD"]
    for n in nodes:
        name, kind = n["name"], n["kind"]
        sym = _state_symbol(states.get(name, ""))
        label = f"{sym} {name}" if sym else name
        if name in targets:
            lines.append(f'    {name}[["{label} ({kind})"]]')
        elif kind in ("commit", "halt"):
            lines.append(f'    {name}(["{label} ({kind})"])')
        else:
            lines.append(f'    {name}["{label} ({kind})"]')
    for src, dst in edges:
        lines.append(f"    {src} --> {dst}")
    return "\n".join(lines)


def _render_dot(
    nodes: list[dict], edges: list[tuple[str, str]],
    states: dict[str, str], targets: set[str],
) -> str:
    lines = ["digraph husks {", "    rankdir=TB;"]
    for n in nodes:
        name, kind = n["name"], n["kind"]
        sym = _state_symbol(states.get(name, ""))
        label = f"{sym} {name}\\n({kind})" if sym else f"{name}\\n({kind})"
        shape = "doubleoctagon" if name in targets else "box"
        lines.append(f'    "{name}" [label="{label}" shape={shape}];')
    for src, dst in edges:
        lines.append(f'    "{src}" -> "{dst}";')
    lines.append("}")
    return "\n".join(lines)


def _render_json(
    nodes: list[dict], edges: list[tuple[str, str]],
    states: dict[str, str],
) -> str:
    nl = []
    for n in nodes:
        entry: dict[str, Any] = {"name": n["name"], "kind": n["kind"]}
        if n["name"] in states:
            entry["state"] = states[n["name"]]
        nl.append(entry)
    return json.dumps({"nodes": nl, "edges": [{"from": s, "to": d} for s, d in edges]}, indent=2)


# ── §7 CLI data models ──────────────────────────────────────────

@dataclass
class CliOutput:
    """Output artifact from a rule."""
    path: str
    sha256: Optional[str] = None


@dataclass
class CliTrace:
    """Oracle provenance and execution metadata."""
    backend: Optional[str] = None
    model: Optional[str] = None
    config_hash: Optional[str] = None
    prompt_hash: Optional[str] = None
    input_tokens: int = 0
    output_tokens: int = 0
    elapsed_s: Optional[float] = None
    cost_usd: float = 0.0
    cache_source: Optional[str] = None


@dataclass
class CliNode:
    """Rule node in CLI output."""
    name: str
    kind: str
    state: str
    children: list[str] = field(default_factory=list)
    fuel: Optional[int] = None
    fuel_budget: Optional[int] = None
    cost: Optional[float] = None
    cache: bool = False
    diagnosis: Optional[str] = None
    stale_reason: Optional[str] = None
    duration: Optional[float] = None
    outputs: list[CliOutput] = field(default_factory=list)
    trace: Optional[CliTrace] = None


@dataclass
class CliResidue:
    """Intermediate representation of CLI command state."""
    command: str
    design_name: str
    status: str
    site: Optional[str] = None
    cse_path: Optional[str] = None
    root: Optional[str] = None
    husk_hash: Optional[str] = None
    target: Optional[str] = None
    fuel_budget: int = 0
    fuel_used: int = 0
    cost: float = 0.0
    nodes: list[CliNode] = field(default_factory=list)
    passes: list[str] = field(default_factory=list)
    fails: list[str] = field(default_factory=list)
    error_message: Optional[str] = None


# ── §8 State mapping helpers ────────────────────────────────────

def map_manifest_state(manifest_state: str) -> str:
    """Map manifest state to CLI vocabulary.  fresh->sealed, else->stale."""
    return "sealed" if manifest_state == "fresh" else "stale"


def map_display_status(status: str, command: str) -> str:
    """Map residue status to display status."""
    if command == "check" and status == "dry":
        return "checked"
    if status == "committed":
        return "sealed"
    if status == "halted":
        return "failed"
    return status


def map_trace_state(trace_event: str, cached: bool = False, failed: bool = False) -> str:
    """Map trace event to CLI state vocabulary."""
    if failed:
        return "failed"
    if cached or trace_event == "reused":
        return "cached"
    if trace_event == "fired":
        return "sealed"
    return "unrealized"


# ── §9 Report assembly ──────────────────────────────────────────

def assemble(
    store: Store,
    events: list[dict[str, Any]],
    design: Design,
    *,
    elapsed_s: float = 0.0,
) -> dict[str, Any]:
    """Build report from post-build state.

    Unlike liquid beta, accepts plain events list instead of BuildTrace.
    Events are dicts with 'event' key: node_done, rule_start, rule_halted, artifact.

    Parameters
    ----------
    store : dict   -- final Store dict from build
    events : list  -- chronological event dicts
    design : dict  -- design IR
    elapsed_s : float -- build elapsed time
    """
    site = store["site"]
    fuel_start = design.get("fuel", 0)
    usage = store.get("usage", {})

    rules_by_name = {r["name"]: r for r in design.get("rules", [])}

    # Extract node events (name, state, elapsed)
    node_events = [(e["name"], e["state"], e.get("elapsed", 0.0))
                   for e in events if e.get("event") == "node_done"]
    _state_map = {"fired": "fired", "reused": "sealed", "failed": "failed"}

    # Stale/halt reasons
    stale_reasons: dict[str, str] = {}
    halt_reasons: dict[str, str] = {}
    artifacts: dict[str, dict] = {}
    for ev in events:
        evt = ev.get("event")
        if evt == "rule_start" and ev.get("stale_reason"):
            stale_reasons[ev["rule"]] = ev["stale_reason"]
        elif evt == "rule_halted" and ev.get("reason"):
            halt_reasons[ev["rule"]] = ev["reason"]
        elif evt == "artifact":
            artifacts[ev["path"]] = ev

    by_rule = usage.get("by_rule", {})
    nodes: list[dict] = []
    cost_reused = 0.0
    seen: set[str] = set()

    for name, raw_state, _el in node_events:
        if name in seen:
            continue
        seen.add(name)
        state = _state_map.get(raw_state, raw_state)
        rule_ir = rules_by_name.get(name, {})
        kind = rule_ir.get("kind", "action")
        cs = convergence_summary(name, site)
        history = read_history(site, name)
        rule_usage = by_rule.get(name, {})

        prompt_len = len(rule_ir.get("prompt", "")) if kind == "oracle" else None
        fuel_consumed = history[-1].get("fuel_consumed") if history else None

        cur_hashes: list[str] = []
        for o in rule_ir.get("outputs", []):
            art = artifacts.get(o)
            if art:
                cur_hashes.append(art["hash"])
        if not cur_hashes and history:
            cur_hashes = history[-1].get("output_hashes", [])

        output_changed = True
        if len(history) >= 2:
            output_changed = cur_hashes != history[-2].get("output_hashes", [])
        elif state == "sealed":
            output_changed = False

        this_cost = rule_usage.get("cost_usd", 0.0) if state == "fired" and kind == "oracle" else 0.0
        cached = rule_usage.get("cached", False) or (raw_state == "reused")
        first_paid = history[0].get("cost_usd") if history else None
        per_rerun = history[-1].get("cost_usd") if history else None

        if state == "sealed" and history:
            lc = history[-1].get("cost_usd")
            if lc is not None:
                cost_reused += lc

        seal_info = None
        seal_data = read_seal(site, name)
        if seal_data:
            rd = seal_data.get("recipe_digest", "")
            recipe_changed = False
            if len(history) >= 2:
                prev_rd = history[-2].get("recipe_digest")
                if prev_rd is not None and rd:
                    recipe_changed = rd != prev_rd
            seal_info = {"hash": seal_data.get("seal", ""), "recipe_changed": recipe_changed}

        nd: dict[str, Any] = {
            "name": name, "kind": kind, "state": state,
            "classification": cs["classification"],
            "prompt_len": prompt_len,
            "prompt_trend": cs.get("prompt_trend"),
            "fuel_consumed": fuel_consumed,
            "fuel_trend": cs.get("fuel_trend"),
            "output_hashes": cur_hashes,
            "outputs": [{"path": p, "hash": h}
                        for p, h in zip(rule_ir.get("outputs", []), cur_hashes)],
            "output_changed": output_changed,
            "cost": {"this_run": round(this_cost, 6),
                     "first_paid": round(first_paid, 6) if first_paid is not None else None,
                     "per_rerun": round(per_rerun, 6) if per_rerun is not None else None},
            "cached": cached,
            "tokens": {"input": rule_usage.get("input_tokens", 0),
                       "output": rule_usage.get("output_tokens", 0)},
            "seal": seal_info,
            "equivalence": rule_ir.get("equivalence", {}),
        }
        for key in ("backend", "model", "config_hash", "prompt_hash"):
            if rule_usage.get(key) is not None:
                nd[key] = rule_usage[key]
        if state == "failed":
            nd["diagnosis"] = {"error": halt_reasons.get(name, ""),
                               "stale_reason": stale_reasons.get(name, "")}
        nodes.append(nd)

    cost_paid = usage.get("total_cost_usd", 0.0)
    changed, new, unchanged = [], [], []
    for nd in nodes:
        h = read_history(site, nd["name"])
        if len(h) < 2:
            (new if nd["state"] != "sealed" or not h else unchanged).append(nd["name"])
        elif nd["output_changed"]:
            changed.append(nd["name"])
        else:
            unchanged.append(nd["name"])

    oracle_calls = sum(1 for nd in nodes if nd["kind"] == "oracle"
                       and nd["state"] == "fired" and nd["cost"]["this_run"] > 0)
    cache_hits_list = [nd["name"] for nd in nodes
                       if nd["kind"] == "oracle" and nd.get("cached")]

    report: dict[str, Any] = {
        "schema_version": "beta-1",
        "status": store["status"],
        "root": store.get("build-root"),
        "run_id": store.get("run-id", ""),
        "build": design.get("name", ""),
        "site": site,
        "elapsed_s": round(elapsed_s, 3),
        "fuel": {"start": fuel_start, "end": store.get("fuel", 0)},
        "cost": {"paid": round(cost_paid, 6),
                 "reused_estimate": round(cost_reused, 6),
                 "projected_estimate": round(cost_paid + cost_reused, 6)},
        "delta": {"changed": changed, "new": new, "unchanged": unchanged},
        "nodes": nodes,
        "oracle_calls": oracle_calls,
        "cache_hits": len(cache_hits_list),
        "cached_nodes": cache_hits_list,
        "cost_tolerance": design.get("cost_tolerance", {"ratio": [0.5, 2.0]}),
    }
    if store["status"] == "halted":
        report["diagnosis"] = {
            "error": store.get("value", ""),
            "failed_nodes": [nd["name"] for nd in nodes if nd["state"] == "failed"],
        }
    return report


# ── §10 Report rendering ────────────────────────────────────────

def render_text(report: dict) -> str:
    """Structured text rendering of a report."""
    lines: list[str] = []
    root_str = report["root"] if report["root"] else "none"
    lines.append(f"schema:   {report.get('schema_version', 'unknown')}")
    lines.append(f"status:   {report['status']}")
    lines.append(f"root:     {root_str}")
    lines.append(f"run_id:   {report['run_id']}")
    lines.append(f"elapsed:  {report['elapsed_s']}s")
    lines.append(f"fuel:     {report['fuel']['end']} / {report['fuel']['start']}")
    cost = report["cost"]
    reused = cost.get("reused_estimate", cost.get("reused", 0.0))
    projected = cost.get("projected_estimate", cost.get("projected", 0.0))
    lines.append(f"cost:     ${cost['paid']:.4f} paid  ${reused:.4f} reused  ${projected:.4f} projected")

    delta = report["delta"]
    lines.append(f"\ndelta:    {len(delta['changed'])} changed  "
                 f"{len(delta['new'])} new  {len(delta['unchanged'])} unchanged")
    lines.append("")
    lines.append("nodes:")
    hdr = f"  {'NAME':<20s} {'STATE':<9s} {'KIND':<9s} {'CLASS':<16s} {'COST':<10s} {'FUEL':<6s} {'PROMPT':<8s} {'OUTPUT'}"
    sep = f"  {'\u2500' * 80}"
    lines.append(hdr)
    lines.append(sep)
    _arrow = {"falling": "\u2193", "rising": "\u2191", "flat": ""}
    for nd in report["nodes"]:
        cost_s = f"${nd['cost']['this_run']:.4f}" if nd["kind"] == "oracle" and nd["state"] == "fired" else "--"
        if nd["fuel_consumed"] is not None:
            fuel_s = f"{nd['fuel_consumed']}{_arrow.get(nd.get('fuel_trend') or '', '')}"
        else:
            fuel_s = "--"
        if nd["prompt_len"] is not None:
            prompt_s = f"{nd['prompt_len']}{_arrow.get(nd.get('prompt_trend') or '', '')}"
        else:
            prompt_s = "--"
        out_s = "FAILED" if nd["state"] == "failed" else ("changed" if nd["output_changed"] else "unchanged")
        lines.append(f"  {nd['name']:<20s} {nd['state']:<9s} {nd['kind']:<9s} "
                     f"{nd['classification']:<16s} {cost_s:<10s} {fuel_s:<6s} {prompt_s:<8s} {out_s}")
    lines.append(sep)
    if "diagnosis" in report:
        d = report["diagnosis"]
        lines.append("")
        lines.append("diagnosis:")
        lines.append(f"  error:         {d['error']}")
        lines.append(f"  failed_nodes:  {', '.join(d['failed_nodes'])}")
    for nd in report["nodes"]:
        if "diagnosis" in nd:
            lines.append("")
            lines.append(f"  {nd['name']}:")
            lines.append(f"    error:         {nd['diagnosis']['error']}")
            if nd["diagnosis"].get("stale_reason"):
                lines.append(f"    stale_reason:  {nd['diagnosis']['stale_reason']}")
    return "\n".join(lines)


def render_concise(report: dict) -> str:
    """One-line-per-rule summary."""
    lines: list[str] = []
    _sym = {"fired": "\u2713", "sealed": "\u25cf", "failed": "\u2717"}
    for nd in report["nodes"]:
        s = _sym.get(nd["state"], "?")
        c = f"  ${nd['cost']['this_run']:.4f}" if nd["kind"] == "oracle" and nd["state"] == "fired" else ""
        lines.append(f"  {s} {nd['name']}  ({nd['kind']}){c}")
    root = (report.get("root") or "none")[:10]
    fuel, cost = report["fuel"], report["cost"]
    lines.append(f"\n  {report['status']}  root {root}  fuel {fuel['end']}/{fuel['start']}  ${cost['paid']:.4f}")
    return "\n".join(lines)


def render_json(report: dict) -> str:
    """Pretty-printed JSON rendering."""
    return json.dumps(report, indent=2)


# ── §11 Report validation ───────────────────────────────────────

def validate_report_schema(report: dict) -> tuple[bool, list[str]]:
    """Validate report dict against the beta-1 contract.  Returns (valid, errors)."""
    errors: list[str] = []
    required_top = {
        "schema_version": str, "status": str, "root": (str, type(None)),
        "run_id": str, "build": str, "site": str,
        "elapsed_s": (int, float), "fuel": dict, "cost": dict,
        "delta": dict, "nodes": list,
        "oracle_calls": int, "cache_hits": int, "cached_nodes": list,
    }
    for fld, typ in required_top.items():
        if fld not in report:
            errors.append(f"missing required field: {fld}")
        elif not isinstance(report[fld], typ):
            errors.append(f"field '{fld}' has wrong type: expected {typ}, got {type(report[fld])}")
    if report.get("schema_version") and report["schema_version"] != "beta-1":
        errors.append(f"unsupported schema_version: {report['schema_version']}")
    if report.get("status") == "committed":
        r = report.get("root")
        if not r or not isinstance(r, str) or not r.strip():
            errors.append("committed reports must have non-empty root string")

    # Fuel
    if isinstance(report.get("fuel"), dict):
        for f in ("start", "end"):
            if f not in report["fuel"]:
                errors.append(f"fuel.{f} missing")
            elif not isinstance(report["fuel"][f], int):
                errors.append(f"fuel.{f} must be int")
    # Cost
    if isinstance(report.get("cost"), dict):
        c = report["cost"]
        if "paid" not in c:
            errors.append("cost.paid missing")
        elif not isinstance(c["paid"], (int, float)):
            errors.append("cost.paid must be numeric")
        re_key = "reused_estimate" if "reused_estimate" in c else ("reused" if "reused" in c else None)
        if re_key is None:
            errors.append("cost.reused_estimate missing")
        elif not isinstance(c[re_key], (int, float)):
            errors.append("cost.reused_estimate must be numeric")
        pr_key = "projected_estimate" if "projected_estimate" in c else ("projected" if "projected" in c else None)
        if pr_key is None:
            errors.append("cost.projected_estimate missing")
        elif not isinstance(c[pr_key], (int, float)):
            errors.append("cost.projected_estimate must be numeric")
    # Delta
    if isinstance(report.get("delta"), dict):
        for f in ("changed", "new", "unchanged"):
            if f not in report["delta"]:
                errors.append(f"delta.{f} missing")
            elif not isinstance(report["delta"][f], list):
                errors.append(f"delta.{f} must be list")
    # Nodes
    if isinstance(report.get("nodes"), list):
        node_req = {
            "name": str, "kind": str, "state": str, "classification": str,
            "prompt_len": (int, type(None)), "prompt_trend": (str, type(None)),
            "fuel_consumed": (int, type(None)), "fuel_trend": (str, type(None)),
            "output_hashes": list, "output_changed": bool,
            "cost": dict, "cached": bool, "tokens": dict, "seal": (dict, type(None)),
        }
        for i, nd in enumerate(report["nodes"]):
            if not isinstance(nd, dict):
                errors.append(f"nodes[{i}] must be dict")
                continue
            for f, t in node_req.items():
                if f not in nd:
                    errors.append(f"nodes[{i}].{f} missing")
                elif not isinstance(nd[f], t):
                    errors.append(f"nodes[{i}].{f} wrong type")
            if isinstance(nd.get("cost"), dict):
                for f in ("this_run", "first_paid", "per_rerun"):
                    if f not in nd["cost"]:
                        errors.append(f"nodes[{i}].cost.{f} missing")
            if isinstance(nd.get("tokens"), dict):
                for f in ("input", "output"):
                    if f not in nd["tokens"]:
                        errors.append(f"nodes[{i}].tokens.{f} missing")
    # Diagnosis
    if report.get("status") == "halted":
        if "diagnosis" not in report:
            errors.append("status 'halted' but diagnosis missing")
        elif isinstance(report["diagnosis"], dict):
            for f in ("error", "failed_nodes"):
                if f not in report["diagnosis"]:
                    errors.append(f"diagnosis.{f} missing")
    return len(errors) == 0, errors
