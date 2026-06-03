# Husks as a DAG — Rearchitecture Design Plan

**Status:** Draft for execution
**Scope:** `src/husks/**`, `tests/**`, new `layers.toml`, `husks doctor` extension
**Thesis:** Husks models work as a sealed, content-addressed DAG of rules. The codebase that does this should itself be a DAG — in module space and in function space — and its test suite should be the DAG's verification, run in dependency order and sealable as a husk. The architecture becomes falsifiable residue: verifiable from outside, the same property Husks asserts about its outputs.

This plan is dependency-ordered. Each phase has an exit criterion. Nothing in a higher layer is touched until the layer beneath it is acyclic and enforced.

---

## 0. Design principles (the invariants we are buying)

1. **Strict downward dependency.** Every module is assigned a single layer index. An import is legal only if it targets a strictly lower layer, or a declared same-layer sibling on an acyclic intra-layer order. No upward imports. Ever.
2. **Honest dependency surface.** A module's import edges are fully declared at module top level. A deferred (in-function) `husks.*` import is permitted *only* to break a genuinely unavoidable cycle, and every such case is a tracked defect, not a pattern. Today there are ~70 of them; the target is zero.
3. **No shared mutable hubs.** State that crosses function boundaries is passed as a parameter, not reached through a module global. A global mutable singleton is a cycle in the data-flow graph.
4. **One graph, two consumers.** The layer DAG is declared once in `layers.toml`. The import linter reads it to enforce module structure; the test runner reads it to order tests. They never diverge.
5. **The gate is a root.** The conformance reader depends on nothing in `husks` except the CSE spec embodied in `core`. It is deliberately near-isolated and must stay that way.

Non-goals are listed in §10. This plan does not pursue "impenetrability"; it pursues a minimal, enforced, acyclic structure.

---

## 1. Current state (measured)

A static scan of the 48 modules under `src/husks` finds **117 intra-package import edges** and **four module-level cycles**:

| # | Cycle | Back-edge to cut |
|---|-------|------------------|
| 1 | `build.eval → build.cache → build.identity → build.eval` | `identity → eval` |
| 2 | `oracle → oracle.claude_code → oracle` | `claude_code → oracle (pkg)` |
| 3 | `oracle → oracle.litellm → oracle` | `litellm → oracle (pkg)` |
| 4 | `cli.main → cli.cmd.build → cli.surface → cli.main` | `surface → main` |

Plus ~70 deferred `husks.*` imports inside function bodies. The worst offenders are `cli.cmd.build` (nearly all imports local — no honest top-level surface at all) and `designs.ir` (reaches into the whole `husks.build` package at call time, which means `ir` actually sits *above* `build` and should declare it).

A second, non-import obstruction: `husks.utils.trace` is a **module-level mutable `BuildTrace()` singleton**. `seal.append_history` harvests `T._tool_events` filtered only by rule name. The `reset()` helper mutates the instance in place specifically so the `from husks.utils import trace as T` alias survives — an explicit acknowledgement that the global is load-bearing and fragile. This is the function-space cycle: every function that touches the trace shares one mutable node.

These are the only structural defects. Everything else is layering hygiene.

---

## 2. Target layer model

Eight layers, bottom (most depended-upon) to top (depends on all):

| Layer | Name | Modules | May import |
|------:|------|---------|------------|
| L0 | Kernel | `core` | (nothing in husks) |
| L1 | CSE forms (pure) | `identity`, `designs.transport`, **`build.policies`** (new) | L0 |
| L2 | Sealing + FS | `build.site`, `build.seal` | L0–L1 |
| L3 | Engine | `build.eval`, `build.cache`, `build.run`, `build.nodes` | L0–L2 |
| L4 | Oracle | `oracle.backend`, `oracle.kernel`, `oracle.llm`, `oracle.tools`, `oracle.litellm`, `oracle.claude_code` | L0–L3 |
| L5 | Surface → IR | `locke`, `designs.ir`, `designs.convergence` | L0–L4 |
| L6 | Inspection | `report`, `manifest`, `graph` | L0–L5 |
| L7 | Entry / CLI | `cli.main`, `cli.surface`, **`cli.contract`** (new), `cli.cmd.*`, `cli.navigator`, `cli.helpers`, `cli.view`, `cli.residue`, `setup`, `resources` | L0–L6 |
| — | Verifier (root) | `gate` | L0 only |

Two new modules (`build.policies`, `cli.contract`) are introduced to absorb back-edges; both are leaves in their layer. `oracle.backend` is promoted to the base of the oracle subtree so concrete backends and the package init depend down on it.

`utils.*` (`events`, `console`) are cross-cutting infrastructure with **zero `husks.*` imports** and are exempt from the layer index (they sit logically below L0). The linter verifies that exemption — `utils` importing anything from `husks` other than nothing is a hard failure.

---

## 3. Cycle-break specifications

Each cut is stated as: the illegal edge, why it exists, and the exact move.

### Cut 1 — `identity → eval` (the engine spine)

**Where.** `build/identity.py::recipe_to_cse` does a local `from husks.build.eval import first_valid` to (a) recognise the default verdict (`verdict is first_valid → b"first-valid"`) and (b) consult `VERDICT_POLICIES`. Meanwhile `eval.py:23` imports `recipe_to_cse`, `_pred_identity`, `VERDICT_POLICIES` from `identity`, and `eval.py:676` *populates* the registry (`VERDICT_POLICIES["first-valid"] = first_valid`). The registry is declared in one layer and filled from a higher one — the definitional smell behind the cycle.

**Why it's wrong.** Verdict identity is a pure, content-addressing concern (it belongs at L1 with the rest of recipe→CSE). `first_valid` itself is pure: it takes `results: list[dict]` and returns one element, importing nothing heavy.

**The move.** Create `build/policies.py` at L1:

```python
# build/policies.py  — L1, imports core only
from __future__ import annotations
from typing import Any, Callable

def first_valid(results: list[dict[str, Any]]) -> dict[str, Any]:
    """Default verdict: first branch with no error."""
    for r in results:
        if "error" not in r:
            return r
    return results[0]

VERDICT_POLICIES: dict[str, Callable] = {"first-valid": first_valid}
DEFAULT_VERDICT: Callable = first_valid

def verdict_identity(verdict) -> bytes:
    """Canonical policy name for a verdict (str | callable | None)."""
    if verdict is None or verdict is DEFAULT_VERDICT:
        return b"first-valid"
    if isinstance(verdict, str) and verdict in VERDICT_POLICIES:
        return verdict.encode()
    from husks.build.identity import _fn_behavior_digest  # same layer, acyclic
    return b"custom:" + _fn_behavior_digest(verdict).encode()
```

- `identity.recipe_to_cse` calls `policies.verdict_identity(verdict)` instead of importing `eval`. (`identity ↔ policies` is one intra-L1 edge; keep it one-directional — `policies` may call `identity._fn_behavior_digest`, `identity` must not call back into `policies` except through `verdict_identity`. Declare `policies < identity` in the intra-layer order.)
- `eval` imports `first_valid`, `VERDICT_POLICIES`, `DEFAULT_VERDICT` from `policies` (downward, L3→L1).
- The `eval.py:676` registry mutation is **deleted**; the registry is now defined complete at its definition site.

**Result.** `identity` no longer imports `eval`. `cache → identity` and `eval → {identity, policies}` are both downward. Cycle 1 gone.

### Cut 2 — oracle package self-cycle (cuts 2 & 3 together)

**Where.** `oracle/__init__.py` eagerly imports the concrete backends (`from husks.oracle.litellm import LiteLLMBackend`, `…claude_code import ClaudeCodeBackend`). Those modules do `from husks.oracle import backend` / `from husks.oracle import backend, kernel, llm, tools`, which re-enters the package `__init__` → cycle.

**Why it's wrong.** The package root is forcing every concrete backend to load at import time, and the concrete backends reach back through the package namespace rather than the leaf module.

**The move.** Two coordinated changes:

1. **Leaf-base the concrete imports.** In `litellm.py` and `claude_code.py`, replace package-namespace imports with direct submodule imports: `from husks.oracle.backend import RealizedCost`, `from husks.oracle.kernel import …`, etc. Never `from husks.oracle import X`.
2. **Make `__init__` lazy.** The package root re-exports only the ABC and registry from `oracle.backend`, and exposes a `get_backend(name)` that imports the concrete backend on first use:

```python
# oracle/__init__.py
from husks.oracle.backend import OracleBackend, RealizedCost, register, REGISTRY

def get_backend(name: str) -> OracleBackend:
    if name not in REGISTRY:
        if name == "litellm":
            from husks.oracle.litellm import LiteLLMBackend  # lazy
            register("litellm", LiteLLMBackend)
        elif name == "claude-code":
            from husks.oracle.claude_code import ClaudeCodeBackend
            register("claude-code", ClaudeCodeBackend)
    return REGISTRY[name]()
```

The lazy import in `get_backend` is a *permitted* deferred import (it breaks the otherwise-unavoidable plugin cycle and is the one documented exception, recorded in `layers.toml` under `[allow_deferred]`).

**Result.** `oracle.backend` is the L4 base; concrete backends and `__init__` depend down on it; nothing imports the package root at module-load time. Cycles 2 and 3 gone.

### Cut 3 — `surface → main` (the CLI tangle)

**Where.** `cli/surface.py::emit_subcommand_help` does a local `from husks.cli.main import _flag_str, _StyledHelpAction, _NO_VALUE_ACTIONS`. The forward path `main → cmd.build → surface` is legal downward; this back-edge closes the loop.

**Why it's wrong.** The argparse help primitives are shared rendering contract, not dispatcher internals. They are currently defined in `main` only because that's where argparse is wired.

**The move.** Create `cli/contract.py` (L7 leaf, beneath both `main` and `surface`) holding `_flag_str`, `_StyledHelpAction`, `_NO_VALUE_ACTIONS`, and the command-table type. `main` and `surface` both import down from `contract`. Declare `contract < surface < cmd.* < main` in the intra-L7 order.

**Result.** Cycle 4 gone. As a follow-on, `cli.cmd.build`'s ~15 deferred imports are hoisted to top level (they were deferred to dodge the same tangle); any that genuinely can't hoist are defects to file, not to keep.

### The honesty pass

After the four cuts, run the deferred-import detector (§7) and hoist every remaining in-function `husks.*` import to module top level. `designs.ir`'s call-time reach into `husks.build` becomes a top-level `import husks.build` declaring it at L5. The exit state: `[allow_deferred]` in `layers.toml` contains exactly the documented exceptions (the oracle plugin lazy-load), and nothing else.

---

## 4. Function-space DAG

Module acyclicity is necessary but not sufficient for the dogfood claim. Two further moves make the *call/data* graph a DAG.

### 4.1 Retire the trace singleton (the linchpin)

`husks.utils.trace` becomes a constructed object threaded through the build, not a module global.

- `BuildTrace` is instantiated once per build in `build.run.build()` and passed down the call tree as an explicit parameter (`trace: BuildTrace`).
- `seal.append_history` receives the trace as an argument; its `_tool_events` filter is scoped by **`run_id` and rule name**, not rule name alone — closing the cross-build event-bleed.
- The module-level `trace` instance and `reset()` are deleted. Code that wants the console renderer attaches a `Console()` listener to its own instance.
- Headless/test code constructs a bare `BuildTrace()` — which the events module already supports.

This single change converts the densest node in the data-flow graph into an ordinary directed edge, and simultaneously fixes the trace-pollution defect flagged in the wild-hardening review. The two goals share one fix.

### 4.2 Type the stage functions

The architecturally significant pipeline functions — `elaborate` (transport), `encode`/`compute_seal`/`recipe_digest` (core), `recipe_to_cse` (identity), `eval_rule`/`eval_oracle`/`eval_trial` (eval), `verify` (gate-side) — are specified as pure transforms: typed input, typed output, no side channel beyond the explicitly threaded `trace` and `Store`. Once side channels are gone, the stage graph is literally a pipeline DAG and can be rendered from the type signatures. This is the codebase becoming isomorphic to the artifact it produces.

---

## 5. Test suite as a DAG

The 78 test files are currently tagged by epoch (`CSE_*`, `LIQUID_*`, `SOLID_NN_*`) — an implied order, not an enforced dependency graph. The redesign makes the suite a build.

### 5.1 Node declaration

Each test module declares the node it covers and its upstream nodes, via a marker that reads the same identifiers `layers.toml` uses:

```python
# tests/test_core_codec.py
pytestmark = husks_node(covers="core", depends_on=[])          # leaf

# tests/test_eval_trial.py
pytestmark = husks_node(covers="build.eval",
                        depends_on=["core", "build.identity",
                                    "build.policies", "build.site", "build.seal"])
```

### 5.2 Topological execution, leaf-first

A `conftest.py` collector topo-sorts test modules by the declared graph (cross-checked against `layers.toml`) and runs leaf-first: `core` before anything above it.

### 5.3 Halt on leaf failure — `blocked`, not `failed`

When a node's tests fail, its dependents are **skipped and marked `blocked`**, not run-and-failed. This is `halt` + `clear_fired_seals` lifted into the test layer: a dependent only "fires" when its dependencies are "sealed" (green). One broken `core.encode` yields one red leaf and a clear count of blocked downstream nodes — not fifty red dependents pointing at one root cause.

```python
# conftest.py (sketch)
def pytest_collection_modifyitems(config, items):
    graph = load_layers_graph("layers.toml")          # one graph, shared
    order = toposort(graph)
    items.sort(key=lambda it: order.index(node_of(it)))

def pytest_runtest_makereport(item, call):
    if call.when == "call" and call.excinfo is not None:
        mark_subtree_blocked(node_of(item))            # dependents skipped

def pytest_runtest_setup(item):
    if is_blocked(node_of(item)):
        pytest.skip(f"dependency unsealed: {blocking_node(item)}")
```

### 5.4 Seal the suite as a husk

The test run is itself a build: nodes are test targets, residue is `{verdict, coverage_hash}` per node, terminating in a `.husk` that asserts "these nodes verified, in this topological order, against these content hashes." A green suite emits `tests/run.husk`, verifiable by the same independent reader that verifies any other husk. The dogfood is then fully eaten: Husks verifies Husks' own verification.

---

## 6. Enforcement (so it can't regress)

A clean DAG today rots by Friday unless the invariant is machine-checked.

### 6.1 `layers.toml` — the single source of truth

```toml
# layers.toml — module layer assignment + legal-edge contract
[layers]                       # name -> index; imports must target a lower index
"husks.core"               = 0
"husks.build.identity"     = 1
"husks.build.policies"     = 1
"husks.designs.transport"  = 1
"husks.build.site"         = 2
"husks.build.seal"         = 2
"husks.build.eval"         = 3
"husks.build.cache"        = 3
"husks.build.run"          = 3
"husks.build.nodes"        = 3
"husks.oracle.backend"     = 4
# … remaining oracle, surface, inspection, cli …

[intra_layer]                  # acyclic order within a layer (lower runs/loads first)
"husks.build.policies"     = ["husks.build.identity"]   # policies precedes identity
"husks.cli.contract"       = ["husks.cli.surface", "husks.cli.main"]

[isolated]                     # may import core only
"husks.gate"               = 0

[pure_infra]                   # zero husks imports permitted
modules = ["husks.utils.events", "husks.utils.console"]

[allow_deferred]               # the ONLY sanctioned in-function husks imports
"husks.oracle"             = ["husks.oracle.litellm", "husks.oracle.claude_code"]  # plugin lazy-load
```

### 6.2 `husks doctor --arch` — the checker

Fold the cycle/edge detector into the existing `doctor` command. It is dependency-free (stdlib `ast`) and lives near `core` so the checker can't itself violate the contract:

```python
def check_architecture(src_root: str, contract: dict) -> list[str]:
    """Return a list of violations; empty list == pass."""
    edges = parse_import_edges(src_root)          # ast walk, module-level only
    deferred = parse_deferred_edges(src_root)     # in-function husks.* imports
    layer = contract["layers"]
    violations = []

    # 1. no upward edges
    for a, bs in edges.items():
        for b in bs:
            if layer.get(b, 99) >= layer.get(a, -1) and not same_layer_ok(a, b, contract):
                violations.append(f"upward/illegal import: {a} -> {b}")

    # 2. no cycles (Tarjan SCC; any SCC > 1 is a cycle)
    for scc in strongly_connected_components(edges):
        if len(scc) > 1:
            violations.append(f"cycle: {' -> '.join(scc)}")

    # 3. deferred imports must be whitelisted
    allowed = contract.get("allow_deferred", {})
    for a, bs in deferred.items():
        for b in bs:
            if b not in allowed.get(a, []):
                violations.append(f"unsanctioned deferred import: {a} ->(local)-> {b}")

    # 4. pure-infra purity + gate isolation
    for m in contract["pure_infra"]["modules"]:
        if edges.get(m):
            violations.append(f"pure-infra module imports husks: {m}")
    if any(layer.get(b, 99) > 0 for b in edges.get("husks.gate", [])):
        violations.append("gate imports above core")
    return violations
```

`husks doctor --arch` fails the build (non-zero exit) on any violation. CI runs it.

### 6.3 Architecture as a conformance vector

Add the architecture check to the conformance set. A frozen expected output ("0 violations against `layers.toml`") makes the acyclicity of Husks itself falsifiable residue — checkable by anyone, no engine internals required. This is the philosophy applied to the codebase rather than its outputs.

---

## 7. Migration plan (dependency-ordered)

Phases run in order; each is independently shippable and has an exit criterion. Phases 2a/2b are parallelizable (disjoint subtrees).

| Phase | Work | Exit criterion |
|------:|------|----------------|
| **0** | Land `layers.toml` (current reality, cycles marked `# KNOWN`) + `husks doctor --arch` in **report-only** mode. | `doctor --arch` runs in CI, prints the 4 cycles, exits 0 (report-only). |
| **1** | **Cut 1.** Create `build.policies`; move `first_valid` + registry; rewrite `identity.recipe_to_cse` and `eval`; delete the registry mutation. | Cycle 1 absent from `doctor --arch`. `test_recipe_identity`, `test_trial_*` green. Recipe digests for existing vectors **unchanged** (identity must be byte-stable across the move — verify against frozen conformance roots). |
| **2a** | **Cut 2/3.** Leaf-base oracle imports; lazy `__init__`; record plugin exception in `[allow_deferred]`. | Cycles 2 & 3 absent. Three-machine proof (`--stub`) still passes. |
| **2b** | **Cut 4.** Create `cli.contract`; rewire `main`/`surface`; hoist `cli.cmd.build` deferred imports. | Cycle 4 absent. CLI acceptance + rendering-contract tests green. |
| **3** | **Honesty pass.** Hoist all remaining deferred imports; fix `designs.ir → build` layering. Flip `doctor --arch` to **enforcing** (non-zero exit on violation). | `doctor --arch` exits non-zero on any cycle/upward/unsanctioned-deferred edge; passes on `main`. |
| **4** | **Function-space.** Thread `BuildTrace`; delete the global + `reset()`; scope `_tool_events` by `run_id`. | No module-level mutable trace. Two in-process builds in one test produce disjoint histories (new regression test). |
| **5** | **Test DAG.** Add `husks_node` markers + topo collector + blocked-not-failed semantics. | Suite runs leaf-first; a forced `core` failure blocks (not fails) its dependents. |
| **6** | **Seal the suite.** Emit `tests/run.husk`; verify with the independent reader; add architecture conformance vector. | Green suite produces a reader-verifiable `run.husk`; `doctor --selftest` includes the arch vector. |

**Stability gate across every phase:** the frozen conformance roots and the three-machine proof must pass unchanged. Refactors that alter a recipe digest or a husk root are bugs, not refactors — the whole point is that internal restructuring leaves the residue byte-identical.

---

## 8. Concrete first artifacts (Phase 0 deliverables)

To start, three files land together:

1. `layers.toml` — §6.1, with the four cycles annotated `# KNOWN, removed in phase N`.
2. `src/husks/_arch/check.py` — §6.2, the stdlib-`ast` checker (placed under a new `_arch` leaf with zero husks deps, so it can never violate the contract it enforces).
3. `tests/test_architecture.py` — asserts `check_architecture(...)` returns only the known-cycle violations in Phase 0, then tightens to empty at Phase 3.

These three give immediate, regression-proof visibility before any production module moves.

---

## 9. Non-goals & risks

**Non-goals.**
- This is not a security boundary and not "impenetrability." It is structural acyclicity and enforced layering.
- Intra-module mutual recursion is allowed; the DAG constraint is on *module* and *cross-module function* edges.
- `gate`'s deliberate duplication of reader logic (to stay zero-cross-dependency) is preserved, not deduplicated. Its isolation is the feature.

**Risks and mitigations.**
- *Identity drift (Phase 1).* Moving `first_valid`/verdict naming could change a recipe digest. Mitigation: byte-compare against frozen conformance roots as a phase-1 gate; the digest is the contract.
- *Lazy oracle load hiding errors (Phase 2a).* A mistyped backend name now fails at `get_backend` call time, not import time. Mitigation: `doctor` enumerates and imports all registered backends in `--selftest`.
- *Behavior-digest non-determinism (orthogonal, worth folding in).* `_fn_behavior_digest` via `inspect.getsource` is environment-dependent. Out of scope for the cycle work, but Phase 1 touches `policies`/identity — a good moment to push opaque-callable recipes toward declared identity (stable name + version), matching the shell-action model already in place.
- *Test-DAG overhead (Phase 5).* Topo collection adds collection-time cost. Mitigation: cache the sorted order keyed by `layers.toml` hash.

---

## 10. One-line summary

Cut three back-edges, introduce two leaf modules, thread one trace, declare one graph, and check it forever — and Husks becomes what it builds: a sealed, acyclic, externally-verifiable DAG.



## 11. Target Tree
Here's the target tree. Structurally it's a light touch — three new modules, one new contract file, and a checker package. The heavy lifting is content moving between existing files, not new files appearing. New marked +, changed-internally marked ~:
Husks/
├── layers.toml                       + the layer contract — single source of truth (§6.1)
├── pyproject.toml                    ~ register husks-gate/doctor unchanged; add layers.toml to sdist
├── README.md
├── docs/
├── skills/husks/SKILL.md
├── spec/                               conformance vectors (+ architecture vector, Phase 6)
│   └── conformance/…
├── examples/
├── scripts/
│
├── src/husks/
│   ├── __init__.py
│   ├── __main__.py
│   │
│   ├── core.py                         L0  kernel — encode, compute_seal, digests, Merkle
│   │
│   ├── _arch/                        + L0-adjacent — zero husks deps, can't violate the contract it checks
│   │   ├── __init__.py               +
│   │   └── check.py                  + ast-based cycle/edge/deferred detector (§6.2)
│   │
│   ├── build/
│   │   ├── __init__.py
│   │   ├── policies.py               + L1  first_valid + VERDICT_POLICIES + verdict_identity (Cut 1)
│   │   ├── identity.py               ~ L1  recipe→CSE; now calls policies, no longer imports eval
│   │   ├── site.py                     L2  path sandbox + fs
│   │   ├── seal.py                   ~ L2  append_history takes trace as arg; _tool_events scoped by run_id
│   │   ├── eval.py                   ~ L3  first_valid/registry removed (moved to policies)
│   │   ├── cache.py                    L3
│   │   ├── nodes.py                    L3
│   │   └── run.py                    ~ L3  constructs the per-build BuildTrace, threads it down
│   │
│   ├── oracle/
│   │   ├── __init__.py               ~ L4  lazy get_backend(); no eager concrete-backend imports (Cut 2/3)
│   │   ├── backend.py                  L4  ABC + registry — base of the oracle subtree
│   │   ├── kernel.py                   L4
│   │   ├── llm.py                      L4
│   │   ├── tools.py                    L4
│   │   ├── litellm.py                ~ L4  imports husks.oracle.backend directly, not the package
│   │   └── claude_code.py            ~ L4  same leaf-base fix
│   │
│   ├── locke.py                        L5  surface language
│   ├── designs/
│   │   ├── __init__.py
│   │   ├── transport.py                L1  (CSE↔JSON bijection — pure, sits low despite living here)
│   │   ├── ir.py                     ~ L5  husks.build reach hoisted to a top-level import
│   │   └── convergence.py              L5
│   │
│   ├── report.py                       L6  inspection
│   ├── manifest.py                     L6
│   ├── graph.py                        L6
│   │
│   ├── cli/
│   │   ├── __init__.py
│   │   ├── __main__.py
│   │   ├── contract.py               + L7 leaf — argparse help primitives (Cut 4)
│   │   ├── surface.py                ~ L7  imports contract, not main
│   │   ├── main.py                   ~ L7  help primitives moved out to contract
│   │   ├── console.py                  L7
│   │   ├── helpers.py                  L7
│   │   ├── navigator.py                L7
│   │   ├── residue.py                  L7
│   │   ├── view.py                     L7
│   │   └── cmd/
│   │       ├── __init__.py
│   │       ├── build.py              ~ L7  ~15 deferred imports hoisted to top level
│   │       ├── cache.py                L7
│   │       ├── compare.py              L7
│   │       ├── inspect.py              L7
│   │       └── validate.py             L7
│   │
│   ├── gate.py                         ROOT  independent reader — imports core only, stays isolated
│   ├── setup.py                        L7
│   ├── resources.py                    L7
│   ├── _resources/
│   │   └── bootstrap_reader.py
│   └── utils/                          pure infra — zero husks imports (exempt from layer index)
│       ├── __init__.py               ~ module-global `trace` singleton + reset() deleted (§4.1)
│       ├── events.py                   BuildTrace class (now constructed per-build, not global)
│       └── console.py
│
└── tests/
    ├── conftest.py                   ~ topo collector + blocked-not-failed semantics (§5)
    ├── test_architecture.py          + asserts check_architecture() against layers.toml
    ├── test_core_codec.py              (renamed from test_CSE_0…) — leaf node, husks_node(covers="core")
    ├── test_*.py                     ~ 78 files gain husks_node(covers=…, depends_on=[…]) markers
    └── run.husk                      + Phase 6 — sealed test residue, verifiable by the gate reader
Net change: four new source files (build/policies.py, cli/contract.py, _arch/__init__.py, _arch/check.py), one root layers.toml, one new test plus a sealed run.husk output. Everything else is content moving downward into its proper layer or losing a side channel — no module is deleted, and the public package surface (husks.* imports your designs depend on) is unchanged.
Two things deliberately not moved. designs/transport.py lives under designs/ for cohesion with ir.py but is logically L1 (pure CSE↔JSON) — layers.toml assigns it index 1 regardless of directory, since the layer index is the contract, not the folder. And gate.py stays a single self-contained file with its intentional logic duplication; its isolation from the rest of husks is the feature, so it doesn't get refactored into shared helpers.
