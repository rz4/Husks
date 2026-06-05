"""L3 engine -- node constructors, evaluator, cache, build orchestration.

Sits on L0 (kernel) + L1 (forms) + L2 (seal) + stdlib.  Single module
merging nodes.py, eval.py, cache.py, and run.py.  No trace coupling:
all events go into S["trace"].  No global mutable state.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import tarfile
import tempfile
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable

from husks.kernel import (
    atom, CseValue, compute_node_digest, encode, recipe_digest, CSE_VERSION,
)
from husks.forms import (
    recipe_to_cse, _pred_identity, _fn_behavior_digest,
    first_valid, VERDICT_POLICIES, DEFAULT_VERDICT,
)
from husks.seal import (
    Store, Node, Recipe, Stop,
    site_path, write_text, read_text, ensure_dir, file_exists, file_sig,
    fresh_store, burn, write_seal, write_build_manifest, write_trial_report,
    compute_cse_seal, output_hashes, freshness_check,
    append_history, history_file, clear_fired_seals,
    write_bytes_atomic, resolve_site_inputs, setup_links,
)

# ── Action arg types ─────────────────────────────────────────────

_ACTION_ARG_TYPES = (str, int, float, bool, bytes, type(None))

# ── Node constructors ────────────────────────────────────────────

def rule(
    *args: Any,
    name: str | None = None,
    inputs: list[str] | None = None,
    outputs: list[str] | None = None,
    recipe: Recipe = None,
    run: str | None = None,
) -> Node:
    """Construct a rule node.  Name may be positional or keyword."""
    if run is not None and recipe is not None:
        raise TypeError("rule() cannot have both 'run' and 'recipe'")
    children: list[Node] = []
    for a in args:
        if isinstance(a, str):
            if name is not None:
                raise TypeError("rule() got multiple values for 'name'")
            name = a
        elif isinstance(a, dict):
            children.append(a)
        else:
            raise TypeError(f"rule() unexpected argument: {a!r}")
    if name is None:
        raise TypeError("rule() missing required argument: 'name'")
    if run is not None:
        recipe = action(_make_shell_action(run, outputs))
        recipe["cmd"] = run
    return {
        "type": "rule", "name": name, "children": children,
        "inputs": inputs or [], "outputs": outputs or [], "recipe": recipe,
    }


def action(fn: Callable[[Store], None], *args: Any) -> dict[str, Any]:
    """Construct an action recipe.  Extra args passed to fn after Store."""
    for i, a in enumerate(args):
        if not isinstance(a, _ACTION_ARG_TYPES):
            raise TypeError(
                f"action() arg {i + 1} has type {type(a).__name__}; "
                f"only {', '.join(t.__name__ for t in _ACTION_ARG_TYPES)} allowed"
            )
    return {"type": "action", "fn": fn, "args": args}


def _make_shell_action(cmd: str, outputs: list[str] | None = None):
    """Create action that runs shell command with staging isolation."""
    _outputs = outputs or []

    def shell_action(S: dict) -> None:
        import subprocess as _sp
        import selectors as _sel

        site = S.get("stage", S["site"])
        live_site = Path(S["site"])
        rule_name = S.get("_active_rule", "")

        # Snapshot live site outputs for rollback
        snapshots = {}
        if "stage" in S:
            for o in _outputs:
                live_out = live_site / o
                if live_out.exists():
                    snapshots[o] = live_out.read_bytes()

        # Break symlinks for declared outputs in staging
        for o in _outputs:
            site_path(S, o, write=True)

        if rule_name:
            S["trace"].append({"event": "shell", "rule": rule_name, "cmd": cmd})

        try:
            proc = _sp.Popen(
                cmd, shell=True, cwd=site,
                stdout=_sp.PIPE, stderr=_sp.PIPE, text=True, bufsize=1,
            )
            out_buf: list[str] = []
            err_buf: list[str] = []
            streams = {
                proc.stdout: ("stdout", out_buf),
                proc.stderr: ("stderr", err_buf),
            }
            selector = _sel.DefaultSelector()
            for pipe in streams:
                selector.register(pipe, _sel.EVENT_READ)

            deadline = time.monotonic() + 120
            timed_out = False
            open_pipes = len(streams)
            while open_pipes > 0:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    timed_out = True
                    break
                for key, _ in selector.select(timeout=min(remaining, 0.5)):
                    pipe = key.fileobj
                    _, buf = streams[pipe]
                    line = pipe.readline()
                    if line == "":
                        selector.unregister(pipe)
                        open_pipes -= 1
                        continue
                    buf.append(line)

            if timed_out:
                proc.kill()
                proc.wait()
                selector.close()
                raise _sp.TimeoutExpired(cmd, 120)

            selector.close()
            returncode = proc.wait()
            stdout_text = "".join(out_buf)
            stderr_text = "".join(err_buf)

            # Guard: detect symlinks created by command to bypass staging
            if "stage" in S:
                stage_dir = Path(S["stage"])
                for o in _outputs:
                    out_path = stage_dir / o
                    if out_path.is_symlink():
                        raise RuntimeError(
                            f"shell command created symlink for output '{o}' "
                            f"(staging isolation violation): {cmd}"
                        )
            if _outputs and not Path(site_path(S, _outputs[0], write=True)).exists():
                content = stdout_text
                if returncode != 0:
                    content += f"\n--- STDERR (exit {returncode}) ---\n{stderr_text}"
                write_text(site_path(S, _outputs[0], write=True), content)
            if returncode != 0:
                raise RuntimeError(f"command failed (exit {returncode}): {cmd}\n{stderr_text}")
        except Exception:
            if "stage" in S:
                for o, content in snapshots.items():
                    (live_site / o).write_bytes(content)
            raise

    shell_action._husks_cmd = cmd
    return shell_action


def oracle(
    name: str | None = None,
    *, prompt: str = "", tools: list[str] | None = None, fuel: int = 8,
) -> dict[str, Any]:
    """Construct an oracle recipe."""
    return {"type": "oracle", "name": name, "prompt": prompt, "tools": tools or [], "fuel": fuel}


def trial(*branches: dict[str, Any], verdict: Callable | None = None) -> dict[str, Any]:
    """Construct a trial recipe from branch recipes."""
    return {"type": "trial", "branches": list(branches), "verdict": verdict}


def cond(predicate: Callable[[Store], bool], then_node: Node, else_node: Node) -> Node:
    """Construct a conditional branch node."""
    return {"type": "cond", "predicate": predicate, "then": then_node, "else": else_node}


def commit(value: str) -> Node:
    """Construct a commit node."""
    return {"type": "commit", "value": value}


def halt(reason: str) -> Node:
    """Construct a halt node."""
    return {"type": "halt", "reason": reason}


# ── Build Transaction ────────────────────────────────────────────

class BuildTransaction:
    """Transactional staging: mirror site, validate outputs, promote atomically."""

    def __init__(self, S: Store, outputs: list[str]):
        self.S, self.outputs = S, outputs
        self.stage_dir: str | None = None
        self.backups: dict[str, str] = {}

    def __enter__(self) -> "BuildTransaction":
        self.stage_dir = tempfile.mkdtemp(prefix="husks-stage-")
        self.S["stage"] = self.stage_dir
        site = Path(self.S["site"]).resolve()
        for item in site.iterdir():
            dst = Path(self.stage_dir) / item.name
            if not dst.exists():
                os.symlink(str(item), str(dst))
        return self

    def validate_outputs(self, rule_name: str, recipe: Recipe) -> None:
        """Validate all declared outputs exist in staging as regular files."""
        require_nonempty = recipe is not None and recipe.get("type") == "oracle"
        stage = Path(self.S["stage"])
        for o in self.outputs:
            op = stage / o
            if op.is_symlink():
                raise RuntimeError(f"rule '{rule_name}' produced symlink output: {o}")
            if not op.exists():
                raise RuntimeError(
                    f"rule '{rule_name}' did not produce declared output: {o} "
                    f"(outputs must be written to staging using write=True)"
                )
            if op.is_dir():
                raise RuntimeError(f"rule '{rule_name}' produced directory output: {o}")
            if not op.is_file():
                raise RuntimeError(f"rule '{rule_name}' produced special file output: {o}")
            if require_nonempty and op.stat().st_size == 0:
                raise RuntimeError(f"oracle '{rule_name}' produced empty output: {o}")

    def promote(self) -> None:
        """Move staged real files to live site with rollback on failure."""
        site = Path(self.S["site"]).resolve()
        stage = Path(self.stage_dir)
        to_promote = [o for o in self.outputs
                      if (stage / o).exists() and not (stage / o).is_symlink()]
        # Backup existing live outputs
        for o in to_promote:
            live = site / o
            if live.exists():
                bp = tempfile.mktemp(prefix=f"husks-backup-{live.name}-")
                shutil.copy2(str(live), bp)
                self.backups[o] = bp
        promoted: list[str] = []
        try:
            for o in to_promote:
                live = site / o
                live.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(stage / o), str(live))
                promoted.append(o)
        except Exception as e:
            for o in promoted:
                live = site / o
                if live.exists():
                    live.unlink()
                if o in self.backups:
                    shutil.move(self.backups.pop(o), str(live))
            raise RuntimeError(f"staged promotion failed: {e}") from e

    def __exit__(self, exc_type, exc_val, exc_tb):
        for bp in self.backups.values():
            if os.path.exists(bp):
                os.unlink(bp)
        self.backups.clear()
        self.S.pop("stage", None)
        if self.stage_dir:
            shutil.rmtree(self.stage_dir, ignore_errors=True)
        return False


# ── Cache ────────────────────────────────────────────────────────

def cache_key(recipe_rd: str, input_sigs: dict[str, str]) -> str:
    """Deterministic cache key from recipe digest + sorted input sigs."""
    sorted_inputs = sorted(input_sigs.items())
    preimage = recipe_rd + "".join(f"{k}:{v}" for k, v in sorted_inputs)
    return hashlib.sha256(preimage.encode()).hexdigest()


def cache_dir(S: Store, key: str) -> str:
    """Path to .cache/{key}."""
    return site_path(S, f".cache/{key}")


def _cache_recipe_key(S: Store, recipe: Recipe, inputs: list[str]) -> tuple[str, dict[str, str], str] | None:
    """Compute (recipe_rd, input_sigs, key) for a cacheable recipe, or None."""
    if recipe is None or recipe.get("type") not in ("oracle", "trial"):
        return None
    recipe_form = recipe_to_cse(recipe)
    recipe_rd = recipe_digest(recipe_form)
    input_sigs = {i: file_sig(site_path(S, i)).decode() for i in sorted(inputs)}
    return recipe_rd, input_sigs, cache_key(recipe_rd, input_sigs)


def cache_get(
    S: Store, recipe: Recipe, inputs: list[str],
    *, declared_outputs: list[str] | None = None,
) -> dict[str, str] | None:
    """Retrieve validated cached outputs.  Single canonical validation path."""
    info = _cache_recipe_key(S, recipe, inputs)
    if info is None:
        return None
    recipe_rd, input_sigs, key = info

    cdir = cache_dir(S, key)
    outputs_file = Path(cdir) / "outputs.json"
    seal_file = Path(cdir) / "seal.json"
    meta_file = Path(cdir) / "meta.json"

    if not outputs_file.exists():
        return None
    try:
        outputs = json.loads(outputs_file.read_text())
        if not seal_file.exists():
            return None
        seal_data = json.loads(seal_file.read_text())
        if seal_data.get("cache_seal_version") != "1.0":
            return None
        if seal_data.get("recipe_digest") != recipe_rd:
            return None
        if seal_data.get("inputs", {}) != input_sigs:
            return None
        cached_names = set(outputs.keys())
        seal_names = set(seal_data.get("outputs", {}).keys())
        if cached_names != seal_names:
            return None
        if declared_outputs is not None and cached_names != set(declared_outputs):
            return None
        seal_outputs = seal_data.get("outputs", {})
        for name, content in outputs.items():
            expected = seal_outputs.get(name)
            if expected is None:
                return None
            if hashlib.sha256(content.encode()).hexdigest() != expected:
                return None
        # Update reuse metadata
        if meta_file.exists():
            meta = json.loads(meta_file.read_text())
            meta["reuse_count"] = meta.get("reuse_count", 0) + 1
            meta["last_reuse_ts"] = time.time()
            meta["last_reuse_run_id"] = S["run-id"]
            meta_file.write_text(json.dumps(meta, indent=2))
        return outputs
    except Exception:
        return None


def _cache_write_entry(base_dir: str, recipe_rd: str, input_sigs: dict[str, str],
                       outputs: dict[str, str], run_id: str) -> None:
    """Write outputs.json, seal.json, meta.json into base_dir."""
    ensure_dir(base_dir)
    output_hashes_map = {n: hashlib.sha256(c.encode()).hexdigest() for n, c in outputs.items()}
    seal_data = {
        "cache_seal_version": "1.0",
        "recipe_digest": recipe_rd,
        "outputs": output_hashes_map,
        "inputs": input_sigs,
    }
    Path(base_dir, "outputs.json").write_text(json.dumps(outputs, indent=2))
    Path(base_dir, "seal.json").write_text(json.dumps(seal_data, indent=2))
    Path(base_dir, "meta.json").write_text(json.dumps({
        "created_ts": time.time(), "created_run_id": run_id,
        "reuse_count": 0, "recipe_digest": recipe_rd,
    }, indent=2))


def cache_put(S: Store, recipe: Recipe, inputs: list[str], outputs: dict[str, str]) -> None:
    """Store outputs in servable cache."""
    info = _cache_recipe_key(S, recipe, inputs)
    if info is None:
        return
    recipe_rd, input_sigs, key = info
    _cache_write_entry(cache_dir(S, key), recipe_rd, input_sigs, outputs, S["run-id"])


def cache_put_pending(S: Store, recipe: Recipe, inputs: list[str], outputs: dict[str, str]) -> None:
    """Stage cache entry in pending area for commit-time promotion."""
    info = _cache_recipe_key(S, recipe, inputs)
    if info is None:
        return
    recipe_rd, input_sigs, key = info
    pending = site_path(S, f".cache/_pending/{key}")
    _cache_write_entry(pending, recipe_rd, input_sigs, outputs, S["run-id"])


def cache_promote_pending(S: Store) -> int:
    """Promote pending entries (matching current run-id) to servable cache."""
    pending_root = Path(site_path(S, ".cache/_pending"))
    if not pending_root.exists():
        return 0
    current_run_id = S.get("run-id")
    promoted = 0
    for entry in pending_root.iterdir():
        if not entry.is_dir():
            continue
        meta_file = entry / "meta.json"
        entry_run_id = None
        if meta_file.exists():
            try:
                entry_run_id = json.loads(meta_file.read_text()).get("created_run_id")
            except Exception:
                pass
        if entry_run_id != current_run_id:
            try: shutil.rmtree(str(entry))
            except Exception: pass
            continue
        servable = Path(cache_dir(S, entry.name))
        if servable.exists():
            shutil.rmtree(servable)
        shutil.move(str(entry), str(servable))
        promoted += 1
    try: shutil.rmtree(str(pending_root))
    except Exception: pass
    return promoted


def cache_discard_pending(S: Store) -> None:
    """Discard all pending cache entries."""
    pending_root = Path(site_path(S, ".cache/_pending"))
    if pending_root.exists():
        try: shutil.rmtree(str(pending_root))
        except Exception: pass


def cache_list(S: Store) -> list[dict[str, Any]]:
    """List servable cache entries with metadata."""
    cache_root = Path(site_path(S, ".cache"))
    if not cache_root.exists():
        return []
    entries = []
    for d in cache_root.iterdir():
        if not d.is_dir():
            continue
        key = d.name
        if not (len(key) == 64 and all(c in "0123456789abcdef" for c in key)):
            continue
        meta_file = d / "meta.json"
        if not meta_file.exists():
            continue
        try:
            meta = json.loads(meta_file.read_text())
            meta["key"] = key
            entries.append(meta)
        except Exception:
            continue
    return sorted(entries, key=lambda e: e.get("created_ts", 0), reverse=True)


def cache_clear(S: Store) -> int:
    """Clear all cache entries.  Returns count removed."""
    cache_root = Path(site_path(S, ".cache"))
    if not cache_root.exists():
        return 0
    count = 0
    for d in cache_root.iterdir():
        if d.is_dir():
            shutil.rmtree(d)
            count += 1
    return count


def _is_hex64(s: str) -> bool:
    return len(s) == 64 and all(c in "0123456789abcdef" for c in s)


def cache_export(S: Store, export_path: str) -> int:
    """Export cache to deterministic .tar.gz with provenance manifest."""
    import io
    cache_root = Path(site_path(S, ".cache"))
    entry_keys = []
    if cache_root.exists():
        entry_keys = sorted(d.name for d in cache_root.iterdir()
                            if d.is_dir() and _is_hex64(d.name))
    manifest = {
        "cache_format_version": "1.0",
        "entry_count": len(entry_keys),
        "entry_keys": entry_keys,
        "source_site_root": S.get("build-root"),
    }

    def _det(info: tarfile.TarInfo) -> tarfile.TarInfo:
        info.mtime = info.uid = info.gid = 0
        info.uname = info.gname = ""
        return info

    count = 0
    with tarfile.open(export_path, "w:gz", compresslevel=9) as tar:
        mdata = json.dumps(manifest, indent=2, sort_keys=True).encode()
        mi = tarfile.TarInfo(name="MANIFEST.json")
        mi.size, mi.mode = len(mdata), 0o644
        tar.addfile(_det(mi), fileobj=io.BytesIO(mdata))
        if cache_root.exists():
            for d in sorted((d for d in cache_root.iterdir()
                             if d.is_dir() and _is_hex64(d.name)), key=lambda p: p.name):
                tar.add(d, arcname=d.name, filter=_det)
                count += 1
    return count


def cache_import(S: Store, import_path: str, *, merge: bool = True) -> int:
    """Import cache from .tar.gz with full security validation."""
    cache_root = Path(site_path(S, ".cache"))
    if not merge and cache_root.exists():
        shutil.rmtree(cache_root)
    ensure_dir(str(cache_root))

    MAX_MEMBER_SIZE = 100 * 1024 * 1024

    with tarfile.open(import_path, "r:gz") as tar:
        # Validate manifest if present
        for member in tar.getmembers():
            if member.name == "MANIFEST.json":
                if member.size > 1024 * 1024:
                    raise ValueError("cache import rejected: manifest too large")
                mf = tar.extractfile(member)
                if mf:
                    try:
                        m = json.loads(mf.read().decode())
                        if m.get("cache_format_version") != "1.0":
                            raise ValueError(
                                f"cache import rejected: unsupported version {m.get('cache_format_version')}")
                    except json.JSONDecodeError as e:
                        raise ValueError(f"cache import rejected: invalid manifest JSON: {e}")
                break

        members_to_extract = []
        for member in tar.getmembers():
            if member.name == "MANIFEST.json":
                continue
            if os.path.isabs(member.name):
                raise ValueError(f"cache import rejected: absolute path '{member.name}'")
            if ".." in Path(member.name).parts:
                raise ValueError(f"cache import rejected: path traversal in '{member.name}'")
            if member.issym() or member.islnk():
                raise ValueError(f"cache import rejected: symlink '{member.name}'")
            if not (member.isfile() or member.isdir()):
                raise ValueError(f"cache import rejected: special file '{member.name}'")
            if member.size > MAX_MEMBER_SIZE:
                raise ValueError(f"cache import rejected: oversized '{member.name}'")
            parts = Path(member.name).parts
            if len(parts) > 2:
                raise ValueError(f"cache import rejected: unexpected nesting '{member.name}'")
            if member.isfile():
                if len(parts) != 2:
                    raise ValueError(f"cache import rejected: file not in entry '{member.name}'")
                ck, fn = parts
                if not _is_hex64(ck):
                    raise ValueError(f"cache import rejected: invalid key '{ck}'")
                if fn not in {"outputs.json", "seal.json", "meta.json"}:
                    raise ValueError(f"cache import rejected: unexpected file '{fn}'")
            elif member.isdir():
                if len(parts) != 1:
                    raise ValueError(f"cache import rejected: unexpected dir '{member.name}'")
                if not _is_hex64(parts[0]):
                    raise ValueError(f"cache import rejected: invalid key '{parts[0]}'")
            members_to_extract.append(member)

        count = 0
        for member in members_to_extract:
            tar.extract(member, path=cache_root, filter='data')
            if member.isdir() and len(Path(member.name).parts) == 1:
                count += 1
    return count


# ── Evaluator ────────────────────────────────────────────────────

def eval_node(S: Store, node: Node) -> None:
    """Dispatch evaluation by node type."""
    kind = node["type"]
    if kind == "rule":
        eval_rule(S, node)
    elif kind == "cond":
        eval_cond(S, node)
    elif kind == "commit":
        S["status"] = "committed"
        S["value"] = node["value"]
        raise Stop("commit", node["value"])
    elif kind == "halt":
        S["status"] = "halted"
        S["value"] = node["reason"]
        raise Stop("halt", node["reason"])
    else:
        raise ValueError(f"unknown node type: {kind}")


def eval_cond(S: Store, node: Node) -> None:
    """Evaluate conditional: call predicate, dispatch to then/else."""
    result = node["predicate"](S)
    S["trace"].append({"event": "cond", "result": bool(result)})
    eval_node(S, node["then"] if result else node["else"])


def eval_rule(S: Store, node: Node) -> None:
    """Evaluate rule: prerequisites, freshness, dispatch, seal."""
    name = node["name"]
    inputs, outputs, recipe = node["inputs"], node["outputs"], node["recipe"]

    # 1. Prerequisites
    for child in node["children"]:
        eval_node(S, child)

    # 2. Freshness
    reason = freshness_check(S, name, inputs, outputs, recipe)
    if reason is None:
        S["trace"].append({"event": "sealed", "rule": name})
        S["trace"].append({"event": "node_done", "name": name, "state": "reused", "elapsed": 0.0})
        return

    # 3. Fire
    burn(S, name)
    # Clean stale outputs
    for o in outputs:
        op = Path(site_path(S, o))
        if op.exists() and not op.is_dir():
            op.unlink()

    t0 = time.time()
    S["trace"].append({"event": "rule-start", "rule": name, "reason": reason})
    S["trace"].append({"event": "rule_start", "rule": name, "stale_reason": reason})
    try:
        with BuildTransaction(S, outputs) as txn:
            usage = eval_recipe(S, name, recipe, inputs, outputs)
            txn.validate_outputs(name, recipe)
            txn.promote()

        write_seal(S, name, inputs, recipe, outputs=outputs)

        # Pending cache for oracle results
        if (recipe is not None and recipe.get("type") == "oracle"
                and not S.get("cache-disabled") and usage and not usage.get("cached")):
            try:
                output_contents = {o: read_text(site_path(S, o)) for o in outputs}
                cache_put_pending(S, recipe, inputs, output_contents)
            except Exception as e:
                S["trace"].append({"event": "cache-stage-failed", "rule": name, "error": str(e)})

        # History
        fuel_consumed = usage.get("fuel_steps", 1) if usage else 1
        rd_hex = recipe_digest(recipe_to_cse(recipe)) if recipe else None
        cost = usage.get("cost_usd") if usage else None
        cached = usage.get("cached", False) if usage else False
        ti = usage.get("tokens_in", 0) if usage else 0
        to_ = usage.get("tokens_out", 0) if usage else 0
        elapsed = time.time() - t0

        append_history(S, name, recipe, outputs, fuel_consumed=fuel_consumed,
                       cost_usd=cost, tokens_in=ti, tokens_out=to_,
                       elapsed_s=elapsed, recipe_digest_hex=rd_hex, cached=cached)

        S["trace"].append({"event": "fired", "rule": name, "outputs": outputs})

        # Emit artifact events for each output
        for o in outputs:
            op = Path(site_path(S, o))
            if op.exists():
                h = hashlib.sha256(op.read_bytes()).hexdigest()
                S["trace"].append({"event": "artifact", "path": o, "hash": h})

        S["trace"].append({"event": "node_done", "name": name, "state": "fired", "elapsed": elapsed})
    except Stop:
        raise
    except Exception as e:
        elapsed_err = time.time() - t0
        S["trace"].append({"event": "rule-halted", "rule": name, "error": str(e)})
        S["trace"].append({"event": "node_done", "name": name, "state": "failed", "elapsed": elapsed_err})
        raise


def eval_recipe(
    S: Store, rule_name: str, recipe: Recipe,
    inputs: list[str], outputs: list[str],
) -> dict[str, Any] | None:
    """Evaluate a recipe.  Returns usage dict or None."""
    if recipe is None:
        return None
    kind = recipe["type"]
    if kind == "action":
        S["_active_rule"] = rule_name
        try:
            recipe["fn"](S, *recipe.get("args", ()))
        finally:
            S.pop("_active_rule", None)
        return None
    if kind == "oracle":
        return eval_oracle(S, rule_name, recipe, inputs, outputs)
    if kind == "trial":
        eval_trial(S, rule_name, recipe, outputs)
        return None
    raise ValueError(f"unknown recipe type: {kind}")


# ── Oracle ───────────────────────────────────────────────────────

def default_oracle_backend(
    S: Store, rule_name: str, recipe: dict[str, Any], outputs: list[str],
) -> dict[str, Any]:
    """Stub oracle backend: writes placeholder outputs."""
    prompt = recipe.get("prompt", "")
    if "ANSWER:" in prompt or ("answer" in prompt.lower() and "format" in prompt.lower()):
        content = "ANSWER: Stub oracle output"
    else:
        content = f"# oracle output: {rule_name}\n# prompt: {prompt}\n"
    for o in outputs:
        write_text(site_path(S, o, write=True), content)
    return {"tokens_in": 0, "tokens_out": 0, "cost_usd": 0.0, "fuel_steps": 1,
            "backend": "stub", "model": "stub"}


def eval_oracle(
    S: Store, rule_name: str, recipe: dict[str, Any],
    inputs: list[str], outputs: list[str],
) -> dict[str, Any]:
    """Evaluate oracle recipe with cache check.  Returns usage dict."""
    t0 = time.time()

    # Cache check
    cached = (cache_get(S, recipe, inputs, declared_outputs=outputs)
              if not S.get("cache-disabled") else None)

    if cached is not None:
        for o, content in cached.items():
            write_text(site_path(S, o, write=True), content)
        u = {"tokens_in": 0, "tokens_out": 0, "cost_usd": 0.0, "fuel_steps": 1, "cached": True}
    else:
        if S.get("cache-reuse-only"):
            raise RuntimeError(
                f"oracle '{rule_name}' requires execution but cache-reuse-only mode is enabled")
        backend = S.get("oracle-backend") or default_oracle_backend
        u = backend(S, rule_name, recipe, outputs) or {}

    # Accumulate usage
    cost = u.get("cost_usd", 0.0)
    ti, to_ = u.get("tokens_in", 0), u.get("tokens_out", 0)
    S["usage"]["total_cost_usd"] += cost
    S["usage"]["total_input_tokens"] += ti
    S["usage"]["total_output_tokens"] += to_

    fuel_steps = u.get("fuel_steps", 1)
    is_cached = u.get("cached", False)
    if rule_name not in S["usage"]["by_rule"]:
        S["usage"]["by_rule"][rule_name] = {
            "cost_usd": 0.0, "input_tokens": 0, "output_tokens": 0,
            "fuel_consumed": 0, "cached": False,
            "backend": None, "model": None,
            "config_hash": None, "prompt_hash": None,
        }
    ru = S["usage"]["by_rule"][rule_name]
    ru["cost_usd"] += cost
    ru["input_tokens"] += ti
    ru["output_tokens"] += to_
    ru["fuel_consumed"] += fuel_steps
    if is_cached:
        ru["cached"] = True
    for k in ("backend", "model", "config_hash", "prompt_hash"):
        if k in u and ru[k] is None:
            ru[k] = u[k]

    elapsed = time.time() - t0
    S["trace"].append({
        "event": "oracle", "rule": rule_name, "cached": is_cached,
        "tokens_in": ti, "tokens_out": to_, "cost_usd": cost,
        "elapsed": elapsed, "fuel_steps": fuel_steps,
    })
    return u


# ── Trial ────────────────────────────────────────────────────────

def eval_trial(
    S: Store, rule_name: str, recipe: dict[str, Any], outputs: list[str],
) -> None:
    """Evaluate trial: fork branches, verdict, merge winner."""
    branches = recipe["branches"]
    verdict_fn = recipe.get("verdict") or first_valid
    if isinstance(verdict_fn, str):
        verdict_fn = VERDICT_POLICIES[verdict_fn]
    results: list[dict[str, Any]] = []

    for branch in branches:
        if S["fuel"] <= 0:
            break
        bname = branch.get("name") or f"branch-{len(results)}"
        burn(S, f"{rule_name}:{bname}")
        tmp = tempfile.mkdtemp(prefix=f"trial-{bname}-")
        t0 = time.time()
        try:
            shutil.copytree(S["site"], tmp, dirs_exist_ok=True)
            BS = fresh_store(tmp, S["fuel"], oracle_backend=S.get("oracle-backend"))
            usage = eval_recipe(BS, bname, branch, [], outputs)
            elapsed = time.time() - t0
            out_data: dict[str, str] = {}
            for o in outputs:
                op = site_path(BS, o)
                if file_exists(op):
                    try:
                        out_data[o] = read_text(op)
                    except UnicodeDecodeError as e:
                        raise RuntimeError(
                            f"trial branch '{bname}' output '{o}' contains binary data") from e
            if usage and usage.get("fuel_steps"):
                bfuel, bti, bto, bcost = (usage.get("fuel_steps", 1), usage.get("tokens_in", 0),
                                          usage.get("tokens_out", 0), usage.get("cost_usd", 0.0))
            else:
                bfuel, bcost = 1, BS["usage"]["total_cost_usd"]
                bti, bto = BS["usage"]["total_input_tokens"], BS["usage"]["total_output_tokens"]
            results.append({
                "name": bname, "outputs": out_data, "elapsed": elapsed,
                "tokens_in": bti, "tokens_out": bto, "cost_usd": bcost, "fuel_steps": bfuel,
            })
        except Exception as e:
            results.append({"name": bname, "error": str(e), "outputs": {}})
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    # Verdict
    vresult = verdict_fn(results)
    if isinstance(vresult, dict) and "winner" in vresult:
        winner, scores = vresult["winner"], vresult.get("scores")
    else:
        winner, scores = vresult, None

    wname = winner["name"]
    if "error" in winner:
        raise RuntimeError(f"trial '{rule_name}' failed: winner '{wname}' error: {winner['error']}")

    # Branch history records
    branch_by_name = {b.get("name", ""): b for b in branches}
    for r in results:
        rname = r["name"]
        has_error = "error" in r
        satisfaction = True if rname == wname else (None if has_error else False)
        branch_recipe = branch_by_name.get(rname)
        prompt_length = (len(branch_recipe.get("prompt", ""))
                         if branch_recipe and branch_recipe.get("type") == "oracle" else None)
        branch_rd = recipe_digest(recipe_to_cse(branch_recipe)) if branch_recipe else None
        record = {
            "run_id": S["run-id"], "ts": time.time(),
            "fuel_consumed": r.get("fuel_steps", 1), "prompt_length": prompt_length,
            "satisfaction": satisfaction, "traced_reads": [],
            "output_hashes": [
                hashlib.sha256(r["outputs"][o].encode()).hexdigest()
                for o in outputs if o in r.get("outputs", {})
            ],
            "cost_usd": r.get("cost_usd") if not has_error else None,
            "recipe_digest": branch_rd,
        }
        hp = history_file(S, f"{rule_name}.{rname}")
        ensure_dir(str(Path(hp).parent))
        with open(hp, "a") as f:
            f.write(json.dumps(record, default=str) + "\n")

    # Merge winner outputs
    for o in outputs:
        if o in winner["outputs"]:
            write_text(site_path(S, o, write=True), winner["outputs"][o])

    write_trial_report(S, rule_name, wname, results, scores, branches, outputs)
    S["trace"].append({"event": "trial", "rule": rule_name, "winner": wname})


# ── CSE serialization + Merkle root ──────────────────────────────

def node_to_cse(node: Node) -> CseValue:
    """Serialize engine node tree to CSE form."""
    ntype = node["type"]
    if ntype == "commit":
        return [b"commit", atom(node["value"])]
    if ntype == "halt":
        return [b"halt", atom(node["reason"])]
    if ntype == "cond":
        return [b"cond", atom(_pred_identity(node["predicate"])),
                node_to_cse(node["then"]), node_to_cse(node["else"])]
    recipe_form = recipe_to_cse(node["recipe"])
    return ([b"rule", atom(node["name"]), recipe_form,
             [atom(i) for i in node["inputs"]], [atom(o) for o in node["outputs"]]]
            + [node_to_cse(c) for c in node["children"]])


def compute_build_root(S: Store, node: Node) -> str:
    """Walk node tree depth-first, computing seals and Merkle digests bottom-up."""
    ntype = node["type"]
    if ntype in ("commit", "halt"):
        return hashlib.sha256(encode(node_to_cse(node))).hexdigest()
    if ntype == "cond":
        td = compute_build_root(S, node["then"])
        ed = compute_build_root(S, node["else"])
        form: CseValue = [b"cond", atom(_pred_identity(node["predicate"])),
                          atom(td), atom(ed)]
        return hashlib.sha256(encode(form)).hexdigest()
    child_digests = [atom(compute_build_root(S, c)) for c in node["children"]]
    seal = compute_cse_seal(S, node["inputs"], node["recipe"])
    out_bindings = [(atom(o), file_sig(site_path(S, o))) for o in node["outputs"]]
    return compute_node_digest(atom(node["name"]), atom(seal), out_bindings, child_digests)


# ── Top-level build ──────────────────────────────────────────────

def build(
    *args: Any,
    name: str | None = None,
    fuel: int | None = None,
    site: str | None = None,
    oracle_backend: Callable | None = None,
    oracle_backend_name: str = "litellm",
    readonly_dirs: list[str] | None = None,
    site_inputs: list[str] | dict[str, str] | None = None,
    **kwargs: Any,
) -> Store:
    """Execute a build.  Name/fuel may be positional or keyword.  Returns final Store."""
    nodes: list[Node] = []
    for a in args:
        if isinstance(a, str):
            if name is not None:
                raise TypeError("build() got multiple values for 'name'")
            name = a
        elif isinstance(a, int) and not isinstance(a, bool):
            if fuel is not None:
                raise TypeError("build() got multiple values for 'fuel'")
            fuel = a
        elif isinstance(a, dict):
            nodes.append(a)
        else:
            raise TypeError(f"build() unexpected argument: {a!r}")
    if name is None:
        raise TypeError("build() missing required argument: 'name'")
    if fuel is None:
        raise TypeError("build() missing required argument: 'fuel'")
    if site is None:
        site = f"/tmp/mccarthy-{name}-{str(uuid.uuid4())[:8]}"

    # Stage site_inputs
    if site_inputs:
        si = resolve_site_inputs(site_inputs)
        if si:
            si_readonly = setup_links(site, si)
            readonly_dirs = list(set((readonly_dirs or []) + si_readonly))

    S = fresh_store(site, fuel, oracle_backend=oracle_backend,
                    oracle_backend_name=oracle_backend_name, readonly_dirs=readonly_dirs)
    if kwargs.get("cache_reuse_only"):
        S["cache-reuse-only"] = True

    S["trace"].append({"event": "build-start", "name": name, "site": site, "fuel": fuel})

    try:
        last_commit_value = None
        for node in nodes:
            try:
                eval_node(S, node)
            except Stop as stop:
                if stop.kind == "halt":
                    raise
                last_commit_value = stop.value
                S["status"] = "running"
        S["status"] = "committed"
        S["value"] = last_commit_value if last_commit_value is not None else "ok"
        if last_commit_value is None:
            S["trace"].append({"event": "auto-commit"})
    except Stop:
        pass
    except Exception as e:
        S["status"] = "halted"
        S["value"] = f"error: {e}"
        S["trace"].append({"event": "error", "message": str(e)})

    # Verification artifacts
    if nodes and S["status"] == "committed":
        try:
            if len(nodes) == 1:
                S["build-root"] = compute_build_root(S, nodes[0])
            else:
                per_roots = {
                    n.get("name", n.get("value", n.get("reason", "?"))): compute_build_root(S, n)
                    for n in nodes
                }
                S["target-roots"] = per_roots
                S["build-root"] = hashlib.sha256(
                    b"".join(r.encode() for r in sorted(per_roots.values()))).hexdigest()
            build_form: list[CseValue] = [
                b"build", atom(name), atom(str(fuel)),
            ] + [node_to_cse(n) for n in nodes]
            husk_bytes = encode([b"husk", CSE_VERSION, build_form])
            write_bytes_atomic(site_path(S, f"{name}.husk"), husk_bytes)
            write_build_manifest(S, name, nodes,
                                 design_source=kwargs.get("design_source"),
                                 design_kind=kwargs.get("design_kind"))
        except Exception as e:
            S["status"] = "halted"
            S["value"] = f"failed to write verification artifacts: {e}"
            S["build-root"] = None
            S["trace"].append({"event": "error", "message": f"verification artifact write failed: {e}"})
    elif nodes and S["status"] == "halted":
        try:
            write_build_manifest(S, name, nodes,
                                 design_source=kwargs.get("design_source"),
                                 design_kind=kwargs.get("design_kind"))
        except Exception:
            pass

    # Pending cache lifecycle
    if S["status"] == "committed":
        try:
            promoted = cache_promote_pending(S)
            if promoted > 0:
                S["trace"].append({"event": "cache-promoted", "count": promoted})
        except Exception as e:
            S["trace"].append({"event": "cache-promotion-failed", "error": str(e)})
    else:
        try: cache_discard_pending(S)
        except Exception: pass
        try:
            cleared = clear_fired_seals(S)
            if cleared > 0:
                S["trace"].append({"event": "seals-cleared", "count": cleared})
        except Exception: pass

    S["trace"].append({"event": "build-end", "status": S["status"]})
    return S
