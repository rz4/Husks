# Architecture

Internal reference for the Husks build calculus.  This document
consolidates the technical material previously embedded as module-level
essays in the source.  For the conceptual argument, see
[theory.md](theory.md).  For usage, see [tutorial.md](tutorial.md).

---

## Module map

```text
src/husks/
  kernel.py    L0   CSE codec, content hashing, seals, Merkle DAG
  forms.py     L1   Policy identity, recipe-to-CSE, CSE-JSON bijection
  seal.py      L2   Path sandboxing, filesystem ops, seal I/O
  engine.py    L3   Build evaluator, caching, oracle dispatch
  oracle.py    L3   LLM backend, fuel-bounded kernel, tool sandbox
  config.py    L4   Configuration resolution, env expansion, validation
  locke.py     L5   Locke compiler (tokenizer, parser, resolver, executor)
  report.py    L6   Reports, manifests, dependency graph rendering
  cli.py       L7   CLI commands, terminal rendering, entry points
```

### Dependency flow

Every module imports only from strictly lower layers; `engine` and `oracle`
share L3 and do not import each other. `kernel` imports only the standard
library. No other module calls `hashlib` directly; all cryptographic
operations are centralized in the kernel. The machine-checkable version of the
layer contract is [`../layers.toml`](../layers.toml), enforced by
`husks doctor --arch`.

---

## Execution model

The evaluator (`engine.py`) walks a compiled node tree depth-first.
For each rule node:

1. **Resolve prerequisites** -- recursively evaluate child nodes.
2. **Freshness check** -- compare current inputs, outputs, and recipe
   against the stored seal.  If all match, the rule is *sealed* and
   its outputs are reused.
3. **If stale** -- burn one unit of fuel, dispatch the recipe, guard
   oracle outputs, write a new seal, append a convergence history
   record.

Fuel is the termination guarantee.  Every stale rule costs one unit.
When fuel reaches zero the build halts.

### Recipes

| Type | Behavior |
| :--- | :--- |
| `action` | Deterministic: shell command or Python callable `(Store) -> None`. Never calls the oracle subsystem. |
| `oracle` | Bounded nondeterministic model call.  The evaluator delegates to an oracle backend and checks only the residue (output files). Has a per-oracle fuel budget bounding agentic steps. |
| `trial` | Speculative fork.  Each branch runs in an isolated site copy.  A verdict function picks the winner; its outputs are copied back. |

### Node types

| Type | Role |
| :--- | :--- |
| `rule` | Work node: inputs, outputs, children, recipe. |
| `commit` | Terminal success: sets status to `"committed"`. |
| `halt` | Terminal failure: sets status to `"halted"`. |
| `cond` | Conditional branch: predicate dispatches to one of two children. Only the selected branch fires. |
| `let` | Shared sub-DAG reference.  Eliminated during compilation -- the evaluator never sees `let` nodes. |

### Store

The build state is a mutable dict threaded through every function:

| Key | Type | Description |
| :--- | :--- | :--- |
| `site` | `str` | Absolute path to the site directory |
| `fuel` | `int` | Remaining fuel budget |
| `status` | `str` | `"running"` / `"committed"` / `"halted"` |
| `value` | `str \| None` | Terminal value or halt reason |
| `trace` | `list` | Append-only event log (dicts) |
| `oracle-backend` | `callable \| None` | Oracle dispatch function |
| `run-id` | `str` | UUID for this build invocation |

---

## CSE wire format

Defined in `kernel.py`.  The Canonical S-Expression Encoding is the
byte-level form that gets hashed.  It is the only form that matters
for verification.

### Grammar

```text
atom  ::= <decimal-length> ":" <exactly length bytes>
list  ::= "(" child* ")"
NIL   ::= 0:                          (zero-length atom, empty bytes)
```

Length prefixes are ASCII decimal with no leading zeros except the
literal `"0"` for zero-length atoms.  No whitespace, no escaping, no
comments.  The format is self-delimiting.

### Type representation in Python

```text
atom  -> bytes
list  -> list[CseValue]   (recursive)
NIL   -> b""              (the empty bytes literal)
```

All hash outputs are lowercase ASCII hex.  Functions returning hashes
for CSE embedding return `bytes`; functions returning hashes for JSON
records return `str`.

### Safety bounds

| Constant | Value | Purpose |
| :--- | :--- | :--- |
| `_MAX_PARSE_DEPTH` | 128 | Prevent stack overflow on adversarial input |
| `_MAX_ATOM_LENGTH` | 256 MiB | Prevent unbounded allocation from malicious length prefix |

---

## Seal format

Each rule's seal is a JSON file at `.traces/<rule>.seal`:

```json
{
  "v": 1,
  "seal": "<hex SHA-256 of CSE seal preimage>",
  "recipe_digest": "<hex SHA-256 of CSE-encoded recipe>",
  "inputs": {"<filename>": "<hex content hash>", ...}
}
```

### Seal preimage (CSE)

```text
seal-preimage = (4:seal <version> <recipe-digest> ( (name hash)* ))
seal          = SHA-256( CSE( seal-preimage ) )
recipe-digest = SHA-256( CSE( recipe-form ) )
```

The seal captures recipe identity and input content hashes.  It
excludes model identity, token counts, cost, wall time, and all
other volatile oracle metadata.

### Node digest (Merkle DAG)

```text
node-form = (4:node <name> <seal> ( (name hash)* ) ( digest* ))
digest    = SHA-256( CSE( node-form ) )
```

Each node's digest covers its seal, output file hashes, and child
digests (depth-first, bottom-up).  The root node's digest is the
build-root: one hash over the entire build.

---

## Design IR

Defined in `locke.py`.  A design is a JSON-native dict
specifying a build graph.

### Operations

| Function | Purpose |
| :--- | :--- |
| `check(design)` | Static validation.  Returns `list[str]` of errors (empty = valid). |
| `check_categorized(design)` | Validation with errors grouped by category. Returns dict with `ok`, `categories`, `errors`. |
| `show(design)` | Pretty-print compiled graph to stdout. |
| `compile(design)` | Lower IR to runtime node dicts.  Returns `(name, fuel, terminal_node, kwargs)`. |
| `run(design)` | End-to-end: check, compile, build.  Returns final Store dict. |
| `from_json(path)` | Load design from JSON file. Tags with `_source_path`. |
| `to_json(design, path)` | Serialize design to JSON. |

### Schema

```json
{
  "name":        "str",
  "fuel":        "int (> 0)",
  "target":      "str (terminal rule name)",
  "targets":     ["str", "...  (alternative to target, for multi-root)"],
  "site_inputs": ["str", "...  (pre-existing files, optional)"],
  "imports":     {"name": "path", "...  (external read-only refs, optional)"},
  "predicates":  {"name": "callable", "...  (for cond, optional)"},
  "rules": [
    {"kind": "action",  "name": "str", "inputs": [], "outputs": [],
     "run": "shell command (optional)", "action_fn": "callable (optional)"},

    {"kind": "oracle",  "name": "str", "inputs": [], "outputs": [],
     "prompt": "str", "tools": ["str"], "fuel": "int"},

    {"kind": "trial",   "name": "str", "inputs": [], "outputs": [],
     "branches": ["recipe_dict", "..."], "verdict": "callable (optional)"},

    {"kind": "commit",  "name": "str", "value": "str"},
    {"kind": "halt",    "name": "str", "reason": "str"},
    {"kind": "let",     "name": "str", "bind": "str"},
    {"kind": "cond",    "name": "str", "predicate": "str",
     "then": "str", "else": "str"}
  ]
}
```

Rules are ordered: a rule may only consume inputs produced by rules
that precede it in the list (or listed in `site_inputs`).  This
ordering is the topological sort of the dependency graph.

---

## Transport layer

Defined in `forms.py`.  Two services:

1. **Lossless CSE <-> JSON bijection.**  Round-tripping through JSON
   reproduces the original CSE bytes exactly.

2. **Flat-design elaboration.**  A linear rule list with implicit
   dependencies is deterministically converted into a CSE AST tree.
   Elaboration is input-only and lossy upward: the original flat
   ordering cannot be reconstructed from the tree.

### CSE form tags

| Form | CSE structure |
| :--- | :--- |
| `husk` | `(4:husk <version> <build>)` |
| `build` | `(5:build <name> <fuel> <target-node> ...)` |
| `rule` | `(4:rule <name> <recipe> <inputs> <outputs> children...)` |
| `action` | `(6:action)` |
| `oracle` | `(6:oracle <name> <prompt> <tools> <fuel>)` |
| `trial` | `(5:trial branch...)` |
| `commit` | `(6:commit <value>)` |
| `halt` | `(4:halt <reason>)` |
| `cond` | `(4:cond <predicate-name> <then-node> <else-node>)` |
| `let` | `(3:let <name> <bound-node>)` |

### OracleBackend protocol

```python
class OracleBackend(Protocol):
    def __call__(self, S: Store, rule_name: str,
                 recipe: dict, outputs: list[str]) -> dict | None: ...
```

Nothing about the backend's identity participates in the seal.

---

## Oracle kernel

Defined in `oracle.py`.  A fuel-bounded agentic loop:

1. `agent()` builds initial context: prompt, tool schemas, fuel.
2. `step()` calls the LLM, parses the response.
3. Tool call → validate allowlist, dispatch, append result, loop
   (iteratively, not recursively).
4. Stop response → return result.
5. Fuel exhausted → return halt result.

### Context dict

| Key | Type | Description |
| :--- | :--- | :--- |
| `prompt` | `str` | Initial user prompt |
| `tools` | `list[str]` | Allowed tool names |
| `tool-defs` | `list[dict]` | OpenAI function-calling schemas |
| `system` | `str \| None` | System prompt |
| `model` | `str` | LiteLLM model identifier |
| `max-tokens` | `int` | Max output tokens per LLM call |
| `rule` | `str \| None` | Rule name (for usage tracking) |
| `trace` | `list[dict]` | Conversation memory (tool calls + results) |

### Config resolution

`_resolve_config(config, rule_name)` merges per-rule overrides onto
the base config. One-level deep merge: if both base and override have
a dict value for the same key (e.g. `params`), the dicts are merged
instead of replaced.

`run_oracle()` checks the resolved config for a `backend` key before
dispatching. Per-rule backend selection lets a design route expensive
rules to a different backend (e.g. `claude-code`) while other rules
use the global default.

### live_oracle()

Adapts the kernel to the build's oracle backend signature:

```python
def live_oracle(S, rule_name, recipe, outputs) -> dict
```

Sets site root for sandboxing, constructs system prompt, snapshots
usage before/after, runs `agent()`, returns usage dict.

---

## Tool sandbox

Defined in `oracle.py`.  Four built-in tools:

| Tool | Description |
| :--- | :--- |
| `read-file` | Read a file as UTF-8 text |
| `write-file` | Write content to a file, creating parent dirs |
| `list-dir` | List names in a directory (one level) |
| `tree` | Recursive directory listing up to a given depth |

All paths resolve through a site-root sandbox.  Any path resolving
outside the site root raises `ValueError`.

The `@tool` decorator auto-generates OpenAI function-calling schemas
from type hints.  Tool names derive from `fn.__name__` with
underscores replaced by hyphens.

---

## Convergence analysis

Defined in `report.py`.  Reads JSONL history logs from
`.traces/<rule>.history.jsonl` and classifies rule behavior.

### Classifications

| Classification | Meaning |
| :--- | :--- |
| `stable` | Output hashes identical across all runs.  The oracle produces the same bytes every time. |
| `converging` | Fuel falling or flat, prompt flat.  Settling toward a fixed point. |
| `prompt-loading` | Fuel falling, prompt *rising*.  Migrating signal into the prompt. |
| `volatile` | No clear trend. |
| `no-data` | No history entries. |

### History record schema

Each line of `.traces/<rule>.history.jsonl`:

```json
{
  "run_id":        "str (UUID)",
  "ts":            "float (unix timestamp)",
  "fuel_consumed": "int",
  "prompt_length": "int | null",
  "satisfaction":  "bool | null (trial verdict)",
  "traced_reads":  ["str", "..."],
  "output_hashes": ["str", "..."],
  "cost_usd":      "float"
}
```

---

## Build manifest

Written by `engine.py` after a successful build to
`.traces/build.manifest.json`:

```json
{
  "schema": "husks.build.manifest.v1",
  "name": "build-name",
  "root": "hex build-root hash",
  "rules": [
    {"name": "str", "kind": "str", "inputs": [], "outputs": []}
  ],
  "design_source": "path (optional)",
  "design_kind": "json (optional)"
}
```

Read by `report.py` for the `status`, `diff`, and `explain`
commands.

---

## Trial report

Written by `engine.py` after a trial verdict to
`.traces/<rule>.trial.json`:

```json
{
  "schema": "husks.trial.v1",
  "rule": "rule-name",
  "winner": "branch-name",
  "branches": [
    {
      "name": "str",
      "kind": "str",
      "selected": "bool",
      "elapsed_ms": "float",
      "cost_usd": "float",
      "outputs": [{"path": "str", "hash": "str"}],
      "score": "float | null"
    }
  ]
}
```

---

## Report assembly

Defined in `report.py`.  Consolidates post-build state into a single
dict consumed by all renderers.

### Renderers

| Function | Output |
| :--- | :--- |
| `render_concise(report)` | One line per rule with symbol (default `run` output) |
| `render_text(report)` | Full table with columns: name, state, kind, class, cost, fuel, prompt, output |
| `render_json(report)` | `json.dumps(report, indent=2)` |

### Concise symbols

```text
✓  fired
●  sealed (reused)
✗  failed
```

---

## Three-machine proof

The CLI supports the full three-machine proof workflow:
M1 fresh build, `cache export`, `cache import` to M2,
M2 `run --reuse-only`, M3 fresh build, `compare` across all three sites.

`compare` with 3 sites renders each site as a verbose status card
(diamond + DAG + per-node expense), then runs proof checks.
Proof is satisfied when: (1) husk hash is identical across M1, M2,
and M3, and (2) root hash is identical between M1 and M2.
Evidence checks (informational): M1/M3 fired oracles and paid cost,
M2 zero oracle cost and cache reuse, M1↔M3 outputs equivalent.
JSON mode includes `proof.satisfied` and `proof.checks` with
`required` flag on each.

---

## CI Pipeline

Three jobs, defined in [`../.github/workflows/ci.yml`](../.github/workflows/ci.yml).
That file is the source of truth; this is a summary.

| Job | Trigger | What it proves |
|-----|---------|----------------|
| **Smoke** | push, PR | The full layer test suite (`tests/`) passes on Python 3.12–3.14 |
| **Three-Machine Stub** | push, PR | The offline three-machine proof passes (`tests/test_three_machine_stub.py`) |
| **Live Oracle** | manual dispatch | The three-machine proof passes against a live LLM oracle |

The red/green badge reflects deterministic invariants only. The Smoke and
Three-Machine Stub jobs run on every push and PR and never spend an API call.
The Live Oracle job runs only on `workflow_dispatch`, reads
`ANTHROPIC_API_KEY` from the `live-oracle` environment, takes an optional
`trials` count, and uses `continue-on-error` so a single live divergence
records as a failed step without turning the repo red. A live oracle's pass
rate is below 100% by construction, so live results are evidence that
compounds across runs and models, not a required gate.
