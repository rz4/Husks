"""
build.py -- Fuel-bounded build evaluator for the Husks calculus.

This module is the runtime layer of Husks.  It takes a compiled
dependency tree of rule nodes (produced by the design layer) and
evaluates them depth-first against a site directory, producing sealed
artifacts and a Merkle-rooted .husk record.

Execution model
---------------
The evaluator walks the node tree depth-first.  For each rule node:

  1. Resolve prerequisites -- recursively evaluate child nodes.
  2. Freshness check -- compare the current state of inputs, outputs,
     and recipe against the stored seal from the previous run.
     If all match, the rule is *sealed* and its outputs are reused.
  3. If stale -- burn one unit of fuel, dispatch the recipe (action,
     oracle, or trial), guard oracle outputs, write a new seal, and
     append a convergence history record.

Fuel is the termination guarantee.  Every stale rule costs one fuel
unit.  When fuel reaches zero the build halts.  Oracle recipes have
an additional per-oracle fuel budget that bounds the number of agentic
steps the kernel may take.

Recipes
-------
  action  -- A deterministic Python callable ``(Store) -> None``.
             The build trusts that actions are pure functions of
             their declared inputs.  Actions never call the oracle
             subsystem.

  oracle  -- A bounded, nondeterministic model call.  The evaluator
             delegates to an oracle backend (a callable matching the
             ``OracleBackend`` signature) and never inspects the
             model's reasoning.  It checks only the residue: the
             output files the oracle was required to produce.

  trial   -- A speculative fork.  Each branch recipe is evaluated in
             an isolated copy of the site.  A verdict function selects
             the winner, and the winner's outputs are copied back to
             the primary site.

Node types
----------
  rule    -- Work node with inputs, outputs, children, and a recipe.
  commit  -- Terminal success: sets status to "committed" and halts.
  halt    -- Terminal failure: sets status to "halted" and halts.
  cond    -- Conditional branch: evaluates a predicate callable
             against the Store and dispatches to exactly one of two
             child nodes (then_node / else_node).  Only the selected
             branch fires; the other is never evaluated.
  let     -- Shared sub-DAG reference.  At the runtime level, let
             nodes are resolved during compilation: the compiler
             emits the bound rule node once and wires it as a child
             everywhere it is referenced.  The evaluator never sees
             a "let" node type -- they are eliminated before
             execution.

Store
-----
The build state is a plain dict (``Store``) threaded through every
function.  Keys:

  site            str     -- absolute path to the site directory
  fuel            int     -- remaining fuel budget
  status          str     -- "running" | "committed" | "halted"
  value           str|None -- terminal value or halt reason
  trace           list    -- append-only event log (dicts)
  oracle-backend  callable|None -- oracle dispatch function
  run-id          str     -- UUID for this build invocation

The store is mutable by design: fuel decrements, status transitions,
and trace appends are side effects that accumulate during evaluation.

Seal format (v1)
----------------
Each rule's seal is a JSON file at ``.traces/<rule>.seal`` containing:

  v               int    -- format version (1)
  seal            str    -- hex SHA-256 of the CSE seal preimage
  recipe_digest   str    -- hex SHA-256 of the CSE-encoded recipe
  inputs          dict   -- {filename: hex content hash} for each
                            declared input

The seal is the staleness oracle: if the current recipe digest and
all input hashes match the stored seal, the rule is fresh and its
outputs are reused without re-execution.

Interface with husks
-------------------------
Imports from:

  core.py     -- CSE encoding, content hashing, seal computation,
                 node digest computation.  All cryptographic operations
                 are delegated to core; build.py never calls hashlib
                 directly except inside recipe_to_cse (which defers
                 to core.recipe_digest for the actual hash).

  utils/      -- Event emission (events.py) and console rendering
                 (console.py).  Currently uses husks.trace as a
                 transitional bridge until the utils/ split lands.

Consumed by:

  designs/    -- The design layer compiles a design IR into node dicts
                 and calls build() with the compiled tree.

  cli.py      -- The CLI's ``run`` command calls build() after design
                 compilation.

Node dict schema
----------------
A rule node is a dict with keys:

  type       "rule"
  name       str          -- unique rule name
  children   list[node]   -- prerequisite rule nodes
  inputs     list[str]    -- declared input filenames (relative to site)
  outputs    list[str]    -- declared output filenames (relative to site)
  recipe     recipe|None  -- action/oracle/trial dict, or None

A commit node:  {"type": "commit", "value": str}
A halt node:    {"type": "halt", "reason": str}
A cond node:    {"type": "cond", "predicate": callable,
                 "then": node, "else": node}

A recipe dict has key ``type`` ("action", "oracle", or "trial") plus
recipe-specific fields.  See the node constructor functions (rule,
action, oracle, trial, cond, commit, halt) for the canonical schemas.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
import time
import uuid
from pathlib import Path
from typing import Any, Callable

from husks.utils import trace as T

from husks.core import (
    ABSENT,
    CSE_VERSION,
    NIL,
    CseValue,
    atom,
    compute_node_digest,
    compute_seal,
    content_hash,
    encode,
    recipe_digest,
)

import inspect

# ── Type aliases ──────────────────────────────────────────────────

Store = dict[str, Any]
Node = dict[str, Any]
Recipe = dict[str, Any] | None
OracleBackend = Callable[[Store, str, dict, list[str]], dict[str, Any] | None]


# ── Stop signal ───────────────────────────────────────────────────

class Stop(Exception):
    """Flow-control exception for commit and halt transitions.

    Raised by eval_node when it encounters a commit or halt node, or
    by burn() when fuel is exhausted.  The build() top-level catches
    Stop and records the final status.
    """

    __slots__ = ("kind", "value")

    def __init__(self, kind: str, value: str) -> None:
        self.kind = kind
        self.value = value
        super().__init__()


# ── Site helpers ──────────────────────────────────────────────────

def site_path(S: Store, name: str) -> str:
    """Resolve *name* relative to the site directory.

    Raises ValueError if the resolved path escapes the site root
    (e.g. via ``..`` components or absolute paths).  Symlinked imports
    (registered as read-only dirs) are permitted to resolve outside.
    """
    site = Path(S["site"]).resolve()
    target = (site / name).resolve()
    if not target.is_relative_to(site):
        # Allow paths that resolve into registered read-only dirs (imports)
        readonly_dirs = S.get("readonly-dirs", [])
        if not any(target.is_relative_to(Path(rd).resolve()) for rd in readonly_dirs):
            raise ValueError(f"path escapes site: {name}")
    return str(target)


def ensure_dir(p: str) -> str:
    """Create directory *p* and all parents.  Returns *p*."""
    Path(p).mkdir(parents=True, exist_ok=True)
    return p


def read_text(p: str) -> str:
    """Read a file as UTF-8 text."""
    return Path(p).read_text()


def write_text(p: str, s: str) -> str:
    """Write UTF-8 text to a file, creating parent directories.  Returns *p*."""
    pp = Path(p)
    ensure_dir(str(pp.parent))
    pp.write_text(str(s))
    return p


def file_exists(p: str) -> bool:
    """True if *p* exists on the filesystem."""
    return Path(p).exists()


def fresh_store(
    site: str,
    fuel: int,
    *,
    oracle_backend: OracleBackend | None = None,
    readonly_dirs: list[str] | None = None,
) -> Store:
    """Create a new build store rooted at *site*."""
    ensure_dir(site)
    return {
        "site": site,
        "fuel": fuel,
        "status": "running",
        "value": None,
        "trace": [],
        "oracle-backend": oracle_backend,
        "readonly-dirs": readonly_dirs or [],
        "run-id": str(uuid.uuid4()),
    }


# ── Fuel ──────────────────────────────────────────────────────────

def burn(S: Store, label: str) -> None:
    """Decrement fuel by one.  Raises Stop if fuel is exhausted."""
    S["fuel"] -= 1
    S["trace"].append({"event": "burn", "label": label, "fuel": S["fuel"]})
    if S["fuel"] < 0:
        S["status"] = "halted"
        S["value"] = f"fuel exhausted: {label}"
        raise Stop("halt", S["value"])


# ── File signatures ───────────────────────────────────────────────

def file_sig(p: str) -> bytes:
    """Return the CSE bytes atom for a file: content hash or ABSENT."""
    path = Path(p)
    if path.exists():
        return content_hash(path.read_bytes())
    return ABSENT


# ── Behavior digest ───────────────────────────────────────────────

def _fn_behavior_digest(fn: Callable) -> str:
    """Compute a behavior-based SHA-256 digest for a Python callable.

    Tries inspect.getsource first (deterministic across runs for
    statically defined functions).  Falls back to bytecode + constants
    if source is unavailable (e.g. for dynamically generated callables).
    """
    try:
        source = inspect.getsource(fn)
        return hashlib.sha256(source.encode()).hexdigest()
    except (OSError, TypeError):
        code = fn.__code__
        data = code.co_code + repr(code.co_consts).encode()
        return hashlib.sha256(data).hexdigest()


def _pred_identity(predicate: Callable) -> str:
    """Return the identity string for a cond predicate (v2).

    Built-in predicates carry _husks_pred_spec (the full spec string).
    Custom Python predicates use a behavior digest.
    """
    spec = getattr(predicate, "_husks_pred_spec", None)
    if spec is not None:
        return spec
    return _fn_behavior_digest(predicate)


# ── Verdict policies ──────────────────────────────────────────────

# Registry of named built-in verdict policies for trial recipes.
# The name is included in the recipe CSE form so that changing the
# verdict changes the recipe digest.
VERDICT_POLICIES: dict[str, Callable] = {}
# Populated after first_valid is defined (see below).


# ── Recipe → CSE ──────────────────────────────────────────────────

def recipe_to_cse(recipe: Recipe) -> CseValue:
    """Convert an engine recipe dict to a CSE-serializable form (v2).

    The CSE form is what participates in the seal preimage.  It must
    be deterministic: the same recipe dict always produces the same
    CSE value.

    v2 recipe identity:
      - Shell actions: (action <cmd>) — command string is the identity.
      - Callable actions: (action <behavior-digest>) — source/bytecode
        digest is the identity.
      - Oracle/trial: unchanged from v1.
    """
    if recipe is None:
        return NIL
    kind: str = recipe["type"]
    if kind == "action":
        fn = recipe["fn"]
        cmd: str = getattr(fn, "_husks_cmd", "")
        if cmd:
            # Shell action — command string is the sole identity
            return [b"action", cmd.encode()]
        else:
            # Callable action — behavior digest
            return [b"action", _fn_behavior_digest(fn).encode()]
    if kind == "oracle":
        name = recipe.get("name")
        return [
            b"oracle",
            name.encode() if name else NIL,
            recipe.get("prompt", "").encode(),
            [t.encode() for t in sorted(recipe.get("tools", []))],
            str(recipe.get("fuel", 8)).encode(),
        ]
    if kind == "trial":
        verdict = recipe.get("verdict")
        if verdict is None or verdict is first_valid:
            policy_name = b"first-valid"
        elif isinstance(verdict, str) and verdict in VERDICT_POLICIES:
            policy_name = verdict.encode()
        else:
            policy_name = b"custom:" + _fn_behavior_digest(verdict).encode()
        return [b"trial", policy_name] + [recipe_to_cse(b) for b in recipe["branches"]]
    return NIL


# ── Seal I/O ──────────────────────────────────────────────────────

def compute_cse_seal(S: Store, inputs: list[str], recipe: Recipe) -> str:
    """Compute the CSE-based seal hash for a rule.  Returns hex string."""
    recipe_form = recipe_to_cse(recipe)
    bindings: list[tuple[bytes, bytes]] = [
        (atom(i), file_sig(site_path(S, i))) for i in inputs
    ]
    return compute_seal(CSE_VERSION, recipe_form, bindings)


def seal_file(S: Store, rule_name: str) -> str:
    """Path to the seal file for *rule_name*."""
    return site_path(S, f".traces/{rule_name}.seal")


def read_seal(S: Store, rule_name: str) -> dict | None:
    """Read the stored seal (v1 JSON).

    Returns None if absent, corrupt, or missing the version field.
    """
    sp = seal_file(S, rule_name)
    if not file_exists(sp):
        return None
    try:
        data = json.loads(read_text(sp))
        if not data.get("v"):
            return None
        return data
    except Exception:
        return None


def output_hashes(S: Store, outputs: list[str]) -> list[str]:
    """Compute content hashes of declared outputs as hex strings."""
    return [file_sig(site_path(S, o)).decode() for o in outputs]


# ── Freshness ─────────────────────────────────────────────────────

def freshness_check(
    S: Store,
    rule_name: str,
    inputs: list[str],
    outputs: list[str],
    recipe: Recipe,
) -> str | None:
    """Determine whether a rule is sealed (fresh) or stale.

    Returns None if the rule is sealed and its outputs can be reused.
    Returns a human-readable reason string if the rule is stale and
    must be re-evaluated.

    Staleness hierarchy (checked in order):
      1. Any declared output file is missing.
      2. No prior seal exists (first build, or corrupt seal file).
      3. Any declared input's content hash differs from the sealed value.
      4. The recipe digest differs from the sealed value.
    """
    # Missing outputs
    for o in outputs:
        if not file_exists(site_path(S, o)):
            return f"{o} missing"

    # No prior seal
    prior = read_seal(S, rule_name)
    if prior is None:
        return "no prior build"

    # Input hash comparison
    prior_inputs: dict[str, str] = prior.get("inputs", {})
    for i in sorted(inputs):
        cur_hash = file_sig(site_path(S, i)).decode()
        old_hash = prior_inputs.get(i, "")
        if cur_hash != old_hash:
            return f"{i} changed"

    # Recipe digest comparison
    recipe_form = recipe_to_cse(recipe)
    cur_rd = recipe_digest(recipe_form)
    if cur_rd != prior.get("recipe_digest", ""):
        return "recipe changed"

    # Output hash comparison (tamper detection)
    if "outputs" not in prior:
        return "seal missing output hashes"
    prior_outputs: dict[str, str] = prior["outputs"]
    for o in sorted(outputs):
        cur_hash = file_sig(site_path(S, o)).decode()
        old_hash = prior_outputs.get(o, "")
        if cur_hash != old_hash:
            return f"{o} tampered"

    return None


def write_seal(
    S: Store,
    rule_name: str,
    inputs: list[str],
    recipe: Recipe,
    outputs: list[str] | None = None,
) -> None:
    """Write the v1 seal: CSE seal + recipe digest + per-input/output hashes."""
    seal = compute_cse_seal(S, inputs, recipe)
    recipe_form = recipe_to_cse(recipe)
    rd = recipe_digest(recipe_form)
    input_sigs = {
        i: file_sig(site_path(S, i)).decode() for i in sorted(inputs)
    }
    seal_data: dict[str, Any] = {
        "v": 1, "seal": seal, "recipe_digest": rd, "inputs": input_sigs,
    }
    if outputs is not None:
        seal_data["outputs"] = {
            o: file_sig(site_path(S, o)).decode() for o in sorted(outputs)
        }
    write_text(
        seal_file(S, rule_name),
        json.dumps(seal_data, indent=2),
    )


# ── Convergence history ───────────────────────────────────────────

def history_file(S: Store, rule_name: str) -> str:
    """Path to the JSONL history log for *rule_name*."""
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
    recipe_digest_hex: str | None = None,
) -> None:
    """Append one convergence record to the rule's history log."""
    prompt_length: int | None = None
    if recipe and recipe.get("type") == "oracle":
        prompt_length = len(recipe.get("prompt", ""))

    # Collect traced reads for this rule from the global trace state.
    traced_reads: list[str] = [
        e[4]["path"] if (isinstance(e[4], dict) and "path" in e[4]) else e[2]
        for e in T._tool_events
        if e[1] == "read-file" and e[0] == rule_name
    ]

    record = {
        "run_id": S["run-id"],
        "ts": time.time(),
        "fuel_consumed": fuel_consumed,
        "prompt_length": prompt_length,
        "satisfaction": satisfaction,
        "traced_reads": traced_reads,
        "output_hashes": output_hashes(S, outputs),
        "cost_usd": cost_usd,
        "recipe_digest": recipe_digest_hex,
    }
    hp = history_file(S, rule_name)
    ensure_dir(str(Path(hp).parent))
    with open(hp, "a") as f:
        f.write(json.dumps(record, default=str) + "\n")


# ── Node constructors ─────────────────────────────────────────────

def rule(
    name: str,
    *children: Node,
    inputs: list[str] | None = None,
    outputs: list[str] | None = None,
    recipe: Recipe = None,
) -> Node:
    """Construct a rule node."""
    return {
        "type": "rule",
        "name": name,
        "children": list(children),
        "inputs": inputs if inputs is not None else [],
        "outputs": outputs if outputs is not None else [],
        "recipe": recipe,
    }


def action(fn: Callable[[Store], None]) -> dict[str, Any]:
    """Construct an action recipe from a deterministic callable."""
    return {"type": "action", "fn": fn}


def oracle(
    name: str | None = None,
    *,
    prompt: str = "",
    tools: list[str] | None = None,
    fuel: int = 8,
) -> dict[str, Any]:
    """Construct an oracle recipe."""
    return {
        "type": "oracle",
        "name": name,
        "prompt": prompt,
        "tools": tools if tools is not None else [],
        "fuel": fuel,
    }


def trial(
    *branches: dict[str, Any],
    verdict: Callable | None = None,
) -> dict[str, Any]:
    """Construct a trial recipe from branch recipes."""
    return {
        "type": "trial",
        "branches": list(branches),
        "verdict": verdict,
    }


def cond(
    predicate: Callable[[Store], bool],
    then_node: Node,
    else_node: Node,
) -> Node:
    """Construct a conditional branch node.

    At evaluation time, *predicate* is called with the current Store.
    If it returns True, *then_node* is evaluated; otherwise *else_node*
    is evaluated.  Only one branch fires.

    The predicate is a Python callable, not serializable to JSON.  At
    the IR level, ``kind: "cond"`` references a named predicate that
    the compiler resolves to a callable.
    """
    return {
        "type": "cond",
        "predicate": predicate,
        "then": then_node,
        "else": else_node,
    }


def commit(value: str) -> Node:
    """Construct a commit node."""
    return {"type": "commit", "value": value}


def halt(reason: str) -> Node:
    """Construct a halt node."""
    return {"type": "halt", "reason": reason}


# ── Output guard ──────────────────────────────────────────────────

def _check_declared_outputs(
    S: Store,
    rule_name: str,
    outputs: list[str],
    recipe: Recipe,
) -> None:
    """Guard: all declared outputs must exist; oracle outputs must be nonempty.

    Raises RuntimeError if the guard fails — preventing the rule from sealing.
    """
    require_nonempty = recipe is not None and recipe.get("type") == "oracle"
    for o in outputs:
        op = Path(site_path(S, o))
        if not op.exists():
            raise RuntimeError(
                f"rule '{rule_name}' did not produce declared output: {o}"
            )
        if require_nonempty and op.stat().st_size == 0:
            raise RuntimeError(
                f"oracle '{rule_name}' produced empty output: {o}"
            )


# ── Evaluator ─────────────────────────────────────────────────────

def eval_node(S: Store, node: Node) -> None:
    """Dispatch evaluation by node type."""
    kind: str = node["type"]
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
    """Evaluate a conditional branch node.

    Calls the predicate with the current Store.  If True, evaluates
    the ``then`` branch; otherwise evaluates the ``else`` branch.
    Only one branch is ever evaluated.
    """
    predicate: Callable[[Store], bool] = node["predicate"]
    result = predicate(S)
    S["trace"].append({
        "event": "cond",
        "result": bool(result),
    })
    if result:
        eval_node(S, node["then"])
    else:
        eval_node(S, node["else"])


def eval_rule(S: Store, node: Node) -> None:
    """Evaluate a rule node: prerequisites, freshness, dispatch."""
    name: str = node["name"]
    inputs: list[str] = node["inputs"]
    outputs: list[str] = node["outputs"]
    recipe: Recipe = node["recipe"]

    # 1. Resolve prerequisites (with parent tracking for diamond annotations)
    T.push_rule(name)
    for child in node["children"]:
        eval_node(S, child)
    T.pop_rule()

    # 2. Freshness check
    reason = freshness_check(S, name, inputs, outputs, recipe)
    if reason is None:
        # Sealed -- reuse outputs
        S["trace"].append({"event": "sealed", "rule": name})
        T.rule_sealed(name, outputs=outputs, output_hashes=output_hashes(S, outputs))
        return

    # 3. Stale -- fire
    burn(S, name)
    T.rule_start(name, stale_reason=reason)
    try:
        usage = eval_recipe(S, name, recipe, inputs, outputs)

        # Output guard: all recipe types require declared outputs to exist.
        # Oracle outputs must additionally be nonempty.
        _check_declared_outputs(S, name, outputs, recipe)

        write_seal(S, name, inputs, recipe, outputs=outputs)

        fuel_consumed = 1
        if usage and usage.get("fuel_steps", 0):
            fuel_consumed = usage["fuel_steps"]

        # Compute recipe digest and extract cost for history record
        rd_hex: str | None = None
        if recipe is not None:
            rd_hex = recipe_digest(recipe_to_cse(recipe))
        cost: float | None = None
        if usage and "cost_usd" in usage:
            cost = usage["cost_usd"]

        append_history(S, name, recipe, outputs, fuel_consumed=fuel_consumed,
                       cost_usd=cost, recipe_digest_hex=rd_hex)
        S["trace"].append({"event": "fired", "rule": name, "outputs": outputs})
        T.rule_done(name, outputs=outputs, output_hashes=output_hashes(S, outputs))
    except Stop:
        raise
    except Exception as e:
        T.rule_halted(name, str(e))
        raise


def eval_recipe(
    S: Store,
    rule_name: str,
    recipe: Recipe,
    inputs: list[str],
    outputs: list[str],
) -> dict[str, Any] | None:
    """Evaluate a recipe.  Returns usage dict with fuel_steps, or None."""
    if recipe is None:
        return None
    kind: str = recipe["type"]
    if kind == "action":
        recipe["fn"](S)
        return None
    if kind == "oracle":
        return eval_oracle(S, rule_name, recipe, outputs)
    if kind == "trial":
        eval_trial(S, rule_name, recipe, outputs)
        return None
    raise ValueError(f"unknown recipe type: {kind}")


# ── Oracle evaluation ─────────────────────────────────────────────

def default_oracle_backend(
    S: Store,
    rule_name: str,
    recipe: dict[str, Any],
    outputs: list[str],
) -> dict[str, Any]:
    """Stub oracle backend that writes placeholder outputs."""
    for o in outputs:
        write_text(
            site_path(S, o),
            f"# oracle output: {rule_name}\n"
            f"# prompt: {recipe.get('prompt', '')}\n",
        )
    return {"tokens_in": 840, "tokens_out": 320, "cost_usd": 0.0008, "fuel_steps": 1}


def eval_oracle(
    S: Store,
    rule_name: str,
    recipe: dict[str, Any],
    outputs: list[str],
) -> dict[str, Any]:
    """Evaluate an oracle recipe.  Returns usage dict."""
    oname: str = recipe.get("name") or "oracle"
    T.oracle_start(rule_name, oname, recipe.get("prompt"))
    t0 = time.time()
    backend: OracleBackend = S.get("oracle-backend") or default_oracle_backend
    usage = backend(S, rule_name, recipe, outputs)
    elapsed = time.time() - t0
    u = usage or {}
    T.oracle_done(
        rule_name,
        oname,
        tokens_in=u.get("tokens_in", 0),
        tokens_out=u.get("tokens_out", 0),
        cost_usd=u.get("cost_usd", 0.0),
        elapsed=elapsed,
    )
    return u


# ── Trial evaluation ──────────────────────────────────────────────

def first_valid(results: list[dict[str, Any]]) -> dict[str, Any]:
    """Default verdict function: pick the first branch without an error."""
    valid = [r for r in results if "error" not in r]
    if not valid:
        raise ValueError("trial: all branches failed")
    if len(valid) > 1:
        rname = valid[0].get("name", "?")
        T.trial_note(
            rname,
            f"first-valid: chose {valid[0]['name']} among {len(valid)} viable branches",
        )
    scores = {r["name"]: r.get("score", 1.0) for r in valid}
    return {"winner": valid[0], "scores": scores}


# Populate the registry now that first_valid is defined.
VERDICT_POLICIES["first-valid"] = first_valid


def eval_trial(
    S: Store,
    rule_name: str,
    recipe: dict[str, Any],
    outputs: list[str],
) -> None:
    """Evaluate a trial recipe: fork, run branches, verdict, merge."""
    branches = recipe["branches"]
    verdict_fn = recipe.get("verdict") or first_valid
    if isinstance(verdict_fn, str):
        verdict_fn = VERDICT_POLICIES[verdict_fn]
    results: list[dict[str, Any]] = []

    for branch in branches:
        if S["fuel"] <= 0:
            break
        bname: str = branch.get("name") or f"branch-{len(results)}"

        # Charge 1 global fuel per branch fired
        burn(S, f"{rule_name}:{bname}")

        tmp = tempfile.mkdtemp(prefix=f"trial-{bname}-")
        t0 = time.time()
        try:
            shutil.copytree(S["site"], tmp, dirs_exist_ok=True)
            BS = fresh_store(tmp, S["fuel"], oracle_backend=S.get("oracle-backend"))

            # Fire branch
            eval_recipe(BS, bname, branch, [], outputs)
            branch_elapsed = time.time() - t0

            # Collect outputs
            out_data: dict[str, str] = {}
            for o in outputs:
                op = site_path(BS, o)
                if file_exists(op):
                    out_data[o] = read_text(op)

            # Collect oracle cost for this branch from trace state
            branch_cost = sum(
                e[4] for e in T._oracle_events if e[1] == bname
            )
            branch_toks_in = sum(
                e[2] for e in T._oracle_events if e[1] == bname
            )
            branch_toks_out = sum(
                e[3] for e in T._oracle_events if e[1] == bname
            )
            results.append({
                "name": bname,
                "outputs": out_data,
                "elapsed": branch_elapsed,
                "tokens_in": branch_toks_in,
                "tokens_out": branch_toks_out,
                "cost_usd": branch_cost,
            })
        except Exception as e:
            results.append({"name": bname, "error": str(e), "outputs": {}})
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    # Verdict (supports both legacy and dict protocol)
    vresult = verdict_fn(results)
    if isinstance(vresult, dict) and "winner" in vresult:
        winner = vresult["winner"]
        scores = vresult.get("scores")
    else:
        winner = vresult
        scores = None

    # Report branches with scores
    for r in results:
        rname = r["name"]
        score = scores.get(rname) if scores else None
        T.trial_branch(
            rule_name,
            rname,
            score=score,
            tokens_in=r.get("tokens_in", 0),
            tokens_out=r.get("tokens_out", 0),
            cost_usd=r.get("cost_usd", 0.0),
            elapsed=r.get("elapsed", 0.0),
        )

    wname: str = winner["name"]
    T.trial_verdict(rule_name, wname, scores=scores)

    # Record convergence history for each branch
    branch_by_name = {b.get("name", ""): b for b in branches}
    for r in results:
        rname = r["name"]
        is_winner = rname == wname
        has_error = "error" in r
        if is_winner:
            satisfaction: bool | None = True
        elif has_error:
            satisfaction = None
        else:
            satisfaction = False

        branch_recipe = branch_by_name.get(rname)
        prompt_length: int | None = None
        if branch_recipe and branch_recipe.get("type", "") == "oracle":
            prompt_length = len(branch_recipe.get("prompt", ""))

        # Compute recipe digest and extract cost for branch history
        branch_rd: str | None = None
        if branch_recipe is not None:
            branch_rd = recipe_digest(recipe_to_cse(branch_recipe))
        branch_cost_val: float | None = r.get("cost_usd") if not has_error else None

        record = {
            "run_id": S["run-id"],
            "ts": time.time(),
            "fuel_consumed": 1,
            "prompt_length": prompt_length,
            "satisfaction": satisfaction,
            "traced_reads": [],
            "output_hashes": [
                hashlib.sha256(r["outputs"][o].encode()).hexdigest()
                for o in outputs
                if o in r.get("outputs", {})
            ],
            "cost_usd": branch_cost_val,
            "recipe_digest": branch_rd,
        }
        hp = history_file(S, f"{rule_name}.{rname}")
        ensure_dir(str(Path(hp).parent))
        with open(hp, "a") as f:
            f.write(json.dumps(record, default=str) + "\n")

    # Copy winner outputs to site
    for o in outputs:
        if o in winner["outputs"]:
            write_text(site_path(S, o), winner["outputs"][o])

    S["trace"].append({"event": "trial", "rule": rule_name, "winner": wname})


# ── CSE husk serialization + Merkle root ──────────────────────────

def node_to_cse(node: Node) -> CseValue:
    """Serialize an engine node tree to its CSE form."""
    ntype = node["type"]
    if ntype == "commit":
        return [b"commit", atom(node["value"])]
    if ntype == "halt":
        return [b"halt", atom(node["reason"])]
    if ntype == "cond":
        return [
            b"cond",
            atom(_pred_identity(node["predicate"])),
            node_to_cse(node["then"]),
            node_to_cse(node["else"]),
        ]
    # rule node
    recipe_form = recipe_to_cse(node["recipe"])
    inp_list: list[bytes] = [atom(i) for i in node["inputs"]]
    out_list: list[bytes] = [atom(o) for o in node["outputs"]]
    children: list[CseValue] = [node_to_cse(c) for c in node["children"]]
    return [b"rule", atom(node["name"]), recipe_form, inp_list, out_list] + children


def compute_build_root(S: Store, node: Node) -> str:
    """Walk the node tree depth-first, computing seals and digests bottom-up.

    Returns the hex digest string for this node (the build-root when
    called on the target node).
    """
    ntype = node["type"]

    # Terminal nodes: digest is just the hash of their CSE form
    if ntype in ("commit", "halt"):
        cse_form = node_to_cse(node)
        return hashlib.sha256(encode(cse_form)).hexdigest()

    if ntype == "cond":
        then_digest = compute_build_root(S, node["then"])
        else_digest = compute_build_root(S, node["else"])
        cse_form = [
            b"cond",
            atom(_pred_identity(node["predicate"])),
            atom(then_digest),
            atom(else_digest),
        ]
        return hashlib.sha256(encode(cse_form)).hexdigest()

    # Rule node
    # Recurse children
    child_digests: list[bytes] = [
        atom(compute_build_root(S, c)) for c in node["children"]
    ]
    # Input bindings
    inp_bindings: list[tuple[bytes, bytes]] = [
        (atom(i), file_sig(site_path(S, i))) for i in node["inputs"]
    ]
    # Seal
    seal = compute_cse_seal(S, node["inputs"], node["recipe"])
    # Output bindings
    out_bindings: list[tuple[bytes, bytes]] = [
        (atom(o), file_sig(site_path(S, o))) for o in node["outputs"]
    ]
    return compute_node_digest(atom(node["name"]), atom(seal), out_bindings, child_digests)


# ── Top-level build ───────────────────────────────────────────────

def build(
    name: str,
    fuel: int,
    *nodes: Node,
    site: str | None = None,
    oracle_backend: OracleBackend | None = None,
    oracle_model: str | None = None,
    readonly_dirs: list[str] | None = None,
    **kwargs: Any,
) -> Store:
    """Execute a build.

    Parameters
    ----------
    name : str
        Build name (used for the .husk filename and trace headers).
    fuel : int
        Global fuel budget.
    *nodes : Node
        One or more root nodes (typically a single target node).
    site : str, optional
        Site directory path.  If not given, a temp directory is created.
    oracle_backend : callable, optional
        Oracle dispatch function.  Defaults to the stub backend.
    oracle_model : str, optional
        Model identifier passed to trace output (advisory only).

    Returns
    -------
    Store
        The final build state dict.
    """
    if site is None:
        site = f"/tmp/mccarthy-{name}-{str(uuid.uuid4())[:8]}"

    # Clear trace state so sequential in-process builds don't accumulate.
    T.clear()

    S = fresh_store(site, fuel, oracle_backend=oracle_backend, readonly_dirs=readonly_dirs)

    S["trace"].append({"event": "build-start", "name": name, "site": site, "fuel": fuel})
    T.build_start(name, fuel, site, oracle_model)

    try:
        last_commit_value = None
        for node in nodes:
            try:
                eval_node(S, node)
            except Stop as stop:
                if stop.kind == "halt":
                    raise  # propagate halts immediately
                # commit: record and continue to next target
                last_commit_value = stop.value
                S["status"] = "running"  # reset for next target
        # All targets processed
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

    # Sealed artifact manifest
    T.sealed_manifest()

    # Compute build-root (Merkle DAG) and write .husk file
    if nodes and S["status"] in ("committed", "halted"):
        try:
            if len(nodes) == 1:
                S["build-root"] = compute_build_root(S, nodes[0])
            else:
                per_roots = {
                    n.get("name", n.get("value", n.get("reason", "?"))): compute_build_root(S, n)
                    for n in nodes
                }
                S["target-roots"] = per_roots
                combined = hashlib.sha256(
                    b"".join(r.encode() for r in sorted(per_roots.values()))
                ).hexdigest()
                S["build-root"] = combined
            build_form: list[CseValue] = [
                b"build", atom(name), atom(str(fuel)),
            ] + [node_to_cse(n) for n in nodes]
            husk_form: CseValue = [b"husk", CSE_VERSION, build_form]
            husk_bytes = encode(husk_form)
            husk_path = site_path(S, f"{name}.husk")
            Path(husk_path).write_bytes(husk_bytes)
        except Exception:
            S["build-root"] = None

    S["trace"].append({"event": "build-end", "status": S["status"]})
    T.build_end(S["status"], S["fuel"], fuel)
    return S
