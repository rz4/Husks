"""L2 seal -- path sandbox, atomic FS, Store, fuel, seal I/O, freshness, history, manifests.

Sits on L0 (kernel) + L1 (forms) + stdlib.  Single module merging site.py
and seal.py into a hardened, minimal L2 layer.  No hidden global state:
append_history accepts traced_reads as an explicit parameter.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import time
import uuid
from pathlib import Path
from typing import Any, Callable

from husks.kernel import ABSENT, CSE_VERSION, atom, content_hash, compute_seal, recipe_digest
from husks.forms import recipe_to_cse

# ── Type aliases ──────────────────────────────────────────────────

Store = dict[str, Any]
Node = dict[str, Any]
Recipe = dict[str, Any] | None

# ── Stop signal ───────────────────────────────────────────────────

class Stop(Exception):
    """Flow-control exception for commit/halt transitions and fuel exhaustion."""
    __slots__ = ("kind", "value")

    def __init__(self, kind: str, value: str) -> None:
        self.kind, self.value = kind, value
        super().__init__()

# ── Atomic write helper ──────────────────────────────────────────

def _atomic_write(p: Path, data: bytes) -> None:
    """Write *data* to *p* atomically: tmp + fsync + replace.  Creates parents."""
    p.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(p.parent), prefix=f".{p.name}.", suffix=".tmp")
    closed = False
    try:
        os.write(fd, data)
        os.fsync(fd)
        os.close(fd)
        closed = True
        os.replace(tmp, str(p))
    except BaseException:
        if not closed:
            try: os.close(fd)
            except OSError: pass
        try: os.unlink(tmp)
        except OSError: pass
        raise

# ── Path sandbox ─────────────────────────────────────────────────

def site_path(S: Store, name: str, *, write: bool = False) -> str:
    """Resolve *name* relative to site; raise ValueError on escape.

    Write mode targets staging dir when present and breaks symlinks
    so writes create real files.  Read-only dirs allow external resolution.
    """
    site = Path(S["site"]).resolve()
    base = Path(S["stage"]).resolve() if (write and "stage" in S) else site
    raw = base / name

    if write and "stage" in S:
        # Break parent symlinks so writes go to stage, not through links
        parts = Path(name).parts
        for i in range(len(parts) - 1):
            parent = base / Path(*parts[:i + 1])
            if parent.is_symlink():
                target = parent.resolve()
                parent.unlink()
                parent.mkdir(parents=True, exist_ok=True)
                if target.is_dir():
                    for item in target.iterdir():
                        link = parent / item.name
                        if not link.exists():
                            os.symlink(str(item), str(link))
        if raw.is_symlink():
            raw.unlink()

    target = raw.resolve()
    if not target.is_relative_to(base):
        if write:
            raise ValueError(f"path escapes site (write denied): {name}")
        readonly_dirs = S.get("readonly-dirs", [])
        if not any(target.is_relative_to(Path(rd).resolve()) for rd in readonly_dirs):
            raise ValueError(f"path escapes site: {name}")
    return str(target)


def read_path(S: Store, name: str) -> str:
    """Resolve *name* for reading (read-only, respects readonly-dirs)."""
    return site_path(S, name, write=False)


def write_path(S: Store, name: str) -> str:
    """Resolve *name* for writing (targets staging dir when present)."""
    return site_path(S, name, write=True)

# ── Filesystem ops ───────────────────────────────────────────────

def ensure_dir(p: str) -> str:
    """mkdir -p.  Returns *p*."""
    Path(p).mkdir(parents=True, exist_ok=True)
    return p


def read_text(p: str) -> str:
    """Read UTF-8 text from *p*."""
    return Path(p).read_text()


def write_text(p: str, s: str) -> str:
    """Atomic UTF-8 write with fsync.  Returns *p*."""
    _atomic_write(Path(p), str(s).encode("utf-8"))
    return p


def write_bytes_atomic(p: str, data: bytes) -> str:
    """Atomic binary write with fsync.  Returns *p*."""
    _atomic_write(Path(p), data)
    return p


def file_exists(p: str) -> bool:
    """True if *p* exists."""
    return Path(p).exists()


def file_sig(p: str) -> bytes:
    """Content hash (hex bytes) for a regular file, ABSENT otherwise."""
    path = Path(p)
    return content_hash(path.read_bytes()) if path.is_file() else ABSENT

# ── Store construction ───────────────────────────────────────────

def fresh_store(
    site: str,
    fuel: int,
    *,
    oracle_backend: Callable | None = None,
    oracle_backend_name: str = "litellm",
    readonly_dirs: list[str] | None = None,
) -> Store:
    """Create a new build Store rooted at *site*."""
    ensure_dir(site)
    return {
        "site": site,
        "fuel": fuel,
        "status": "running",
        "value": None,
        "trace": [],
        "oracle-backend": oracle_backend,
        "oracle-backend-name": oracle_backend_name,
        "readonly-dirs": readonly_dirs or [],
        "run-id": str(uuid.uuid4()),
        "usage": {
            "total_cost_usd": 0.0,
            "total_input_tokens": 0,
            "total_output_tokens": 0,
            "by_rule": {},
        },
    }

# ── Fuel ─────────────────────────────────────────────────────────

def burn(S: Store, label: str) -> None:
    """Decrement fuel; raise Stop when exhausted."""
    S["fuel"] -= 1
    S["trace"].append({"event": "burn", "label": label, "fuel": S["fuel"]})
    if S["fuel"] < 0:
        S["status"] = "halted"
        S["value"] = f"fuel exhausted: {label}"
        raise Stop("halt", S["value"])

# ── Site inputs ──────────────────────────────────────────────────

def resolve_site_inputs(site_inputs: list | dict | None) -> dict[str, str]:
    """Normalize None/list/dict site_inputs to canonical {local_name: path} dict."""
    if site_inputs is None:
        return {}
    if isinstance(site_inputs, dict):
        return site_inputs.copy()
    result = {}
    for entry in site_inputs:
        p = Path(entry)
        result[p.name if p.is_absolute() else entry] = entry
    return result

# ── Import links ─────────────────────────────────────────────────

def setup_links(site: str, mapping: dict[str, str]) -> list[str]:
    """Create validated read-only symlinks.  Returns list of readonly-dir paths.

    Rejects dotfiles, path traversal, absolute local names, and collisions.
    """
    readonly_dirs: list[str] = []
    for local_name, ext_path in mapping.items():
        if local_name.startswith("."):
            raise ValueError(f"setup_links: local name cannot start with '.': {local_name}")
        if ".." in Path(local_name).parts:
            raise ValueError(f"setup_links: local name contains path traversal: {local_name}")
        if Path(local_name).is_absolute():
            raise ValueError(f"setup_links: local name must be relative: {local_name}")

        link = Path(site) / local_name
        ext = Path(ext_path).resolve()
        if not ext.exists():
            raise ValueError(f"setup_links: external path does not exist: {ext_path}")

        if link.is_symlink():
            if link.resolve() != ext:
                raise ValueError(
                    f"setup_links: symlink '{local_name}' already exists but "
                    f"points to wrong target (expected {ext}, got {link.resolve()})"
                )
        elif link.exists():
            raise ValueError(
                f"setup_links: cannot create import link '{local_name}' "
                f"(file or directory already exists at that path)"
            )
        else:
            link.parent.mkdir(parents=True, exist_ok=True)
            os.symlink(str(ext), str(link))

        rd = str(ext.parent) if ext.is_file() else str(ext)
        readonly_dirs.append(rd)
    return readonly_dirs

# ── Seal I/O ─────────────────────────────────────────────────────

def compute_cse_seal(S: Store, inputs: list[str], recipe: Recipe) -> str:
    """Compute CSE seal hash.  Returns hex string."""
    recipe_form = recipe_to_cse(recipe)
    bindings = [(atom(i), file_sig(site_path(S, i))) for i in inputs]
    return compute_seal(CSE_VERSION, recipe_form, bindings)


def seal_file(S: Store, rule_name: str) -> str:
    """Path to .traces/{rule_name}.seal."""
    return site_path(S, f".traces/{rule_name}.seal")


def read_seal(S: Store, rule_name: str) -> dict | None:
    """Read stored seal JSON; None if absent or corrupt."""
    sp = seal_file(S, rule_name)
    if not file_exists(sp):
        return None
    try:
        data = json.loads(read_text(sp))
        return data if data.get("v") else None
    except Exception:
        return None


def write_seal(
    S: Store,
    rule_name: str,
    inputs: list[str],
    recipe: Recipe,
    outputs: list[str] | None = None,
) -> None:
    """Write seal v1 JSON: CSE seal + recipe digest + per-input/output hashes."""
    seal = compute_cse_seal(S, inputs, recipe)
    recipe_form = recipe_to_cse(recipe)
    rd = recipe_digest(recipe_form)
    seal_data: dict[str, Any] = {
        "v": 1,
        "seal": seal,
        "recipe_digest": rd,
        "inputs": {i: file_sig(site_path(S, i)).decode() for i in sorted(inputs)},
    }
    if outputs is not None:
        seal_data["outputs"] = {o: file_sig(site_path(S, o)).decode() for o in sorted(outputs)}
    write_text(seal_file(S, rule_name), json.dumps(seal_data, indent=2))

# ── Freshness ────────────────────────────────────────────────────

def freshness_check(
    S: Store,
    rule_name: str,
    inputs: list[str],
    outputs: list[str],
    recipe: Recipe,
) -> str | None:
    """None if sealed (fresh); human-readable reason string if stale.

    Staleness hierarchy: missing output > no prior seal > seal differs > tampered output.
    """
    for o in outputs:
        if not file_exists(site_path(S, o)):
            return f"{o} missing"

    prior = read_seal(S, rule_name)
    if prior is None:
        return "no prior build"

    current_seal = compute_cse_seal(S, inputs, recipe)
    if current_seal != prior.get("seal", ""):
        return _diagnose_staleness(S, inputs, recipe, prior)

    if "outputs" not in prior:
        return "seal missing output hashes"
    prior_outputs = prior["outputs"]
    for o in sorted(outputs):
        if file_sig(site_path(S, o)).decode() != prior_outputs.get(o, ""):
            return f"{o} tampered"
    return None


def _diagnose_staleness(S: Store, inputs: list[str], recipe: Recipe, prior: dict) -> str:
    """Diagnose why seal changed: recipe, added/removed/changed inputs, or unknown."""
    recipe_form = recipe_to_cse(recipe)
    if recipe_digest(recipe_form) != prior.get("recipe_digest", ""):
        return "recipe changed"
    prior_inputs = prior.get("inputs", {})
    cur_set, prior_set = set(inputs), set(prior_inputs)
    removed = prior_set - cur_set
    if removed:
        return f"{sorted(removed)[0]} removed"
    added = cur_set - prior_set
    if added:
        return f"{sorted(added)[0]} changed"
    for i in sorted(inputs):
        if file_sig(site_path(S, i)).decode() != prior_inputs.get(i, ""):
            return f"{i} changed"
    return "dependencies changed"


def clear_fired_seals(S: Store) -> int:
    """Remove seal files for rules that fired during this build.  Returns count removed."""
    removed = 0
    for event in S.get("trace", []):
        if event.get("event") == "fired":
            rule_name = event.get("rule")
            if rule_name:
                sp = seal_file(S, rule_name)
                p = Path(sp)
                if p.exists():
                    p.unlink()
                    removed += 1
    return removed


def output_hashes(S: Store, outputs: list[str]) -> list[str]:
    """Content hashes of declared outputs as hex strings."""
    return [file_sig(site_path(S, o)).decode() for o in outputs]

# ── Convergence history ──────────────────────────────────────────

def history_file(S: Store, rule_name: str) -> str:
    """Path to JSONL history log for *rule_name*."""
    return site_path(S, f".traces/{rule_name}.history.jsonl")


def append_history(
    S: Store,
    rule_name: str,
    recipe: Recipe,
    outputs: list[str],
    *,
    fuel_consumed: int = 1,
    satisfaction: bool | None = None,
    cost_usd: float | None = None,
    tokens_in: int = 0,
    tokens_out: int = 0,
    elapsed_s: float | None = None,
    recipe_digest_hex: str | None = None,
    cached: bool = False,
    traced_reads: list[str] = (),
) -> None:
    """Append one convergence record.  No hidden global state -- traced_reads is explicit."""
    prompt_length = len(recipe.get("prompt", "")) if (recipe and recipe.get("type") == "oracle") else None
    record = {
        "run_id": S["run-id"],
        "ts": time.time(),
        "fuel_consumed": fuel_consumed,
        "prompt_length": prompt_length,
        "satisfaction": satisfaction,
        "traced_reads": list(traced_reads),
        "output_hashes": output_hashes(S, outputs),
        "cost_usd": cost_usd,
        "tokens_in": tokens_in,
        "tokens_out": tokens_out,
        "elapsed_s": elapsed_s,
        "recipe_digest": recipe_digest_hex,
        "cached": cached,
    }
    hp = history_file(S, rule_name)
    ensure_dir(str(Path(hp).parent))
    with open(hp, "a") as f:
        f.write(json.dumps(record, default=str) + "\n")

# ── Trial report ─────────────────────────────────────────────────

def write_trial_report(
    S: Store,
    rule_name: str,
    winner_name: str,
    results: list[dict[str, Any]],
    scores: dict[str, float] | None,
    branches_ir: list[dict[str, Any]],
    outputs: list[str],
) -> None:
    """Write .traces/{rule_name}.trial.json after a trial verdict."""
    branch_by_name = {b.get("name", ""): b for b in branches_ir}
    branch_entries: list[dict[str, Any]] = []
    for r in results:
        bname = r["name"]
        br = branch_by_name.get(bname, {})
        has_error = "error" in r
        entry: dict[str, Any] = {
            "name": bname,
            "kind": br.get("type", "oracle"),
            "selected": bname == winner_name,
            "elapsed_ms": round(r.get("elapsed", 0.0) * 1000, 1),
            "cost_usd": r.get("cost_usd", 0.0) if not has_error else None,
            "outputs": {
                o: hashlib.sha256(r["outputs"][o].encode()).hexdigest()
                for o in outputs if o in r.get("outputs", {})
            },
        }
        if scores and bname in scores:
            entry["score"] = scores[bname]
        if has_error:
            entry["error"] = r["error"]
        branch_entries.append(entry)

    report = {
        "schema": "husks.trial.v1",
        "rule": rule_name,
        "run_id": S["run-id"],
        "winner": winner_name,
        "branches": branch_entries,
    }
    write_text(site_path(S, f".traces/{rule_name}.trial.json"), json.dumps(report, indent=2))

# ── Build manifest ───────────────────────────────────────────────

def _collect_rules(node: Node, seen: set[str] | None = None) -> list[dict[str, Any]]:
    """Walk node tree, collect rule info for manifest."""
    if seen is None:
        seen = set()
    results: list[dict[str, Any]] = []
    ntype = node.get("type", "")
    if ntype == "rule":
        name = node["name"]
        if name not in seen:
            seen.add(name)
            recipe = node.get("recipe")
            children_names = [c["name"] for c in node.get("children", [])
                              if isinstance(c, dict) and c.get("type") == "rule"]
            entry: dict[str, Any] = {
                "name": name,
                "kind": recipe["type"] if recipe else "action",
                "inputs": node.get("inputs", []),
                "outputs": node.get("outputs", []),
            }
            if children_names:
                entry["children"] = children_names
            results.append(entry)
        for child in node.get("children", []):
            results.extend(_collect_rules(child, seen))
    elif ntype == "cond":
        results.extend(_collect_rules(node["then"], seen))
        results.extend(_collect_rules(node["else"], seen))
    return results


def write_build_manifest(
    S: Store,
    name: str,
    nodes: tuple[Node, ...],
    *,
    design_source: str | None = None,
    design_kind: str | None = None,
    design: dict[str, Any] | None = None,
) -> None:
    """Write .traces/build.manifest.json with build status and rule summary."""
    seen: set[str] = set()
    rules: list[dict[str, Any]] = []
    for node in nodes:
        rules.extend(_collect_rules(node, seen))

    # Merge design-level metadata into manifest rules (equivalence, etc.)
    if design:
        design_rules = {r["name"]: r for r in design.get("rules", []) if isinstance(r, dict)}
        for rule in rules:
            dr = design_rules.get(rule["name"], {})
            equiv = dr.get("equivalence")
            if equiv:
                rule["equivalence"] = equiv

    manifest: dict[str, Any] = {
        "schema": "husks.build.manifest.v1",
        "name": name,
        "status": S.get("status", "unknown"),
        "root": S.get("build-root"),
        "site": S["site"],
        "run_id": S["run-id"],
        "rules": rules,
    }
    if design_source:
        manifest["design_source"] = design_source
    if design_kind:
        manifest["design_kind"] = design_kind
    # Preserve cost_tolerance and oracle backend name for compare
    if design:
        ct = design.get("cost_tolerance")
        if ct:
            manifest["cost_tolerance"] = ct
    backend_name = S.get("oracle-backend-name")
    if backend_name:
        manifest["oracle_backend"] = backend_name
    write_text(site_path(S, ".traces/build.manifest.json"), json.dumps(manifest, indent=2))
