# Architecture

Internal reference for the Husks build calculus.  This document
consolidates the technical material previously embedded as module-level
essays in the source.  For the conceptual argument, see
[theory.md](theory.md).  For usage, see [tutorial.md](tutorial.md).

---

## Module map

```text
husks/
  core.py              CSE codec, content hashing, seals, Merkle DAG
  build.py             Fuel-bounded build evaluator
  report.py            Post-build report assembly and rendering
  manifest.py          Manifest/seal/trial-report reader utilities
  graph.py             Dependency graph rendering (text, mermaid, dot, json)
  gate.py              Conformance gate for external CSE readers
  setup.py             husks doctor --selftest and husks init
  cli.py               Argparse CLI (11 commands)

  designs/
    __init__.py         Re-exports from ir, transport, convergence
    ir.py               Design IR: check, compile, run, from_json
    transport.py        CSE <-> JSON bijection, flat-design elaboration
    convergence.py      Post-execution rule history analysis

  oracle/
    __init__.py         Re-exports live_oracle, set_oracle_model
    kernel.py           Agentic loop (fuel-bounded LLM + tool dispatch)
    llm.py              LiteLLM wrapper with cumulative usage tracking
    tools.py            Sandboxed filesystem tools for oracle execution

  utils/
    events.py           Structured event stream (BuildTrace)
    console.py          ANSI terminal renderer (TraceListener)
```

### Dependency flow

```text
core.py           ← no internal imports (stdlib only)
  ↑
build.py          ← core, utils/events
  ↑
designs/ir.py     ← build (node constructors + build entry point)
designs/transport.py ← core (encode, parse)
designs/convergence.py ← stdlib only
  ↑
oracle/kernel.py  ← oracle/llm, oracle/tools, utils/events
oracle/llm.py     ← litellm (lazy import)
oracle/tools.py   ← stdlib only
  ↑
cli.py            ← designs/ir, build, report, manifest, graph, gate, setup
report.py         ← designs/convergence, utils/events
manifest.py       ← husks.core (content_hash)
graph.py          ← manifest (optional, for freshness overlay)
```

`core.py` imports only the standard library.  No other module calls
hashlib directly; all cryptographic operations are centralized in core.

---

## Execution model

The evaluator (`build.py`) walks a compiled node tree depth-first.
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

Defined in `core.py`.  The Canonical S-Expression Encoding is the
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

Defined in `designs/ir.py`.  A design is a JSON-native dict
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

Defined in `designs/transport.py`.  Two services:

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

Defined in `transport.py` because it describes the contract between
the permanent specification layer and the volatile execution layer.
Nothing about the backend's identity participates in the seal.

---

## Oracle kernel

Defined in `oracle/kernel.py`.  A fuel-bounded agentic loop:

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

### live_oracle()

Adapts the kernel to the build's oracle backend signature:

```python
def live_oracle(S, rule_name, recipe, outputs) -> dict
```

Sets site root for sandboxing, constructs system prompt, snapshots
usage before/after, runs `agent()`, returns usage dict.

---

## Tool sandbox

Defined in `oracle/tools.py`.  Four built-in tools:

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

## Event stream

Defined in `utils/events.py`.  The `BuildTrace` class accumulates
structured events for a single build invocation.

### Listener protocol

```python
class TraceListener(Protocol):
    def notify(self, event: dict[str, Any]) -> None: ...
```

After each event is recorded, all registered listeners are notified.
The console renderer (`utils/console.py`) is one such listener.

### Event types

| Event | Additional keys |
| :--- | :--- |
| `build_start` | `name`, `fuel`, `site` |
| `build_end` | `status`, `fuel_left`, `elapsed` |
| `rule_start` | `rule`, `stale_reason` |
| `rule_done` | `rule`, `elapsed` |
| `rule_sealed` | `rule`, `reused_by` |
| `rule_halted` | `rule`, `reason`, `elapsed` |
| `oracle_start` | `rule`, `oracle` |
| `oracle_done` | `rule`, `oracle`, `tokens_in`, `tokens_out`, `cost_usd`, `elapsed` |
| `tool_call` | `rule`, `tool`, `args` |
| `tool_result` | `tool`, `result_preview` |
| `trial_branch` | `rule`, `branch`, `score`, `tokens_in`, `tokens_out`, `cost_usd`, `elapsed` |
| `trial_note` | `rule`, `message` |
| `trial_verdict` | `rule`, `winner`, `scores` |
| `sealed_manifest` | `artifacts` |

Every event dict has at minimum `{"event": str, "ts": float}`.

---

## Console renderer

Defined in `utils/console.py`.  Implements `TraceListener` and
renders events to the terminal with ANSI escapes.

```text
build_start     ═══ header bar with name, site, fuel, model ═══
rule_start      ▸ name  (stale: reason)
rule_done       ✓ name  elapsed
rule_sealed     ● name  reused by parent
rule_halted     ✗ name  reason
oracle_start    → oracle  "prompt preview..."
oracle_done       tokens · cost · elapsed
tool_call       → tool  {args}
trial_branch    ⊢ branch · score · elapsed · cost
trial_verdict   ⊣ verdict → winner
build_end       ─── summary ───
```

ANSI escapes are suppressed when stdout is not a TTY.  The console
module never modifies event data or build state.

---

## Convergence analysis

Defined in `designs/convergence.py`.  Reads JSONL history logs from
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

Written by `build.py` after a successful build to
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

Read by `manifest.py` for the `status`, `diff`, and `explain`
commands.

---

## Trial report

Written by `build.py` after a trial verdict to
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

## CI Pipeline

Three jobs, replacing the earlier `core-tests` and `beta-acceptance` jobs.

| Job | Gate | Trigger | What it proves |
|-----|------|---------|----------------|
| **Wheel Smoke** | Install | push, PR | Wheel builds and imports on Python 3.10-3.13 |
| **Solid Alpha** | Deterministic | push, PR | Full test suite passes with stub oracles |
| **Liquid Beta** | Live | manual dispatch | Three-machine proof with live LLM oracle |

### `.github/workflows/ci.yml`

```yaml
name: CI

on:
  push:
    branches: [main]
  pull_request:
    branches: [main]
  workflow_dispatch:
    inputs:
      trials:
        description: "Liquid Beta: number of live three-machine trials to run"
        required: false
        default: "1"

permissions:
  contents: read

concurrency:
  group: ci-${{ github.ref }}
  cancel-in-progress: true

jobs:
  wheel-smoke:
    name: Wheel Smoke
    runs-on: ubuntu-latest
    strategy:
      fail-fast: false
      matrix:
        python: ["3.10", "3.11", "3.12", "3.13"]
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: ${{ matrix.python }}
          cache: pip
      - run: |
          python -m pip install --upgrade pip build
          python -m build --wheel
          pip install dist/*.whl pytest
      - run: python -m pytest tests/test_wheel_smoke.py -v --tb=short

  solid-alpha:
    name: Solid Alpha
    runs-on: ubuntu-latest
    strategy:
      fail-fast: false
      matrix:
        python: ["3.10", "3.11", "3.12", "3.13"]
    env:
      HUSKS_ENABLE_LIVE_TESTS: ""
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: ${{ matrix.python }}
          cache: pip
      - name: Install
        run: |
          python -m pip install --upgrade pip
          pip install -e . pytest
      - name: Stub three-machine resolution (headline invariant)
        run: |
          python -m pytest -m alpha \
            tests/test_three_machine_proof.py \
            tests/test_three_machine_cli_acceptance.py \
            tests/test_beta_three_machine.py \
            -v --tb=short
      - name: Full deterministic suite
        run: |
          python -m pytest tests/ -m "not beta" \
            --ignore=tests/test_live_oracle_readiness.py \
            -v --tb=short

  liquid-beta:
    name: Liquid Beta (live three-machine)
    if: github.event_name == 'workflow_dispatch'
    runs-on: ubuntu-latest
    environment: live-oracle
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
          cache: pip
      - name: Install (with live oracle extra)
        run: |
          python -m pip install --upgrade pip
          pip install -e ".[llm]" pytest
      - name: Live three-machine demo
        continue-on-error: true
        env:
          ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
          HUSKS_ENABLE_LIVE_TESTS: "1"
          HUSKS_LIVE_TRIALS: ${{ github.event.inputs.trials }}
        run: |
          python -m pytest -m beta tests/test_live_oracle_readiness.py \
            -v --tb=short
```

### Wiring notes

- **Branch protection**: mark every Wheel Smoke and Solid Alpha matrix entry as a required status check. Do **not** require Liquid Beta. The red/green badge reflects deterministic invariants only.
- **Triggers**: Liquid Beta runs only on `workflow_dispatch`. It never runs on push, PR, or schedule, so it costs an API call only when you click run.
- **Fork safety**: `workflow_dispatch` can be triggered only by users with write access, and fork PRs cannot read secrets. The optional `environment: live-oracle` adds a manual-approval gate.
- **`continue-on-error: true`** on the live step: a single live divergence records as a failed step but does not fail the job or turn the repo red.
- **`HUSKS_ENABLE_LIVE_TESTS: ""`** is set explicitly on Solid Alpha so a stray live test can never execute there even if mismarked.

### Assumptions to confirm before merging

- The install extras (`pip install -e .` for alpha, `".[llm]"` for beta) match the project's actual packaging.
- The three stub three-machine files named in the headline step are the right set after any rename.
- `ANTHROPIC_API_KEY` exists as a repo (or `live-oracle` environment) secret.
