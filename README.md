# @site — Rock-Hard Husks

Hardened, layer-by-layer re-realization of Husks.
Each layer is defined as a Locke design, implemented in source, and verified by tests.
This work proceeds independently of the current liquid beta in `src/husks/`.

## Goal

Harden every layer of the Husks stack (L0-L7) to the point where each
component's contract is expressible as a Locke design, verifiable by Husks
itself. When complete, `@site/` becomes the foundation for the gaseous phase:
Husks bootstraps Husks, and the bootstrap passes the three-machine proof.

## Structure

```
@site/
  src/            — hardened implementation (flat package)
  tests/          — layer-specific verification
    L0-kernel/
    L1-forms/
    L2-seal/
    L3-engine/
    L4-oracle/
    L5-locke/
    L6-inspect/
    L7-cli/
  lockes/         — Locke designs defining each layer's contract
    L0-kernel/
    L1-forms/
    L2-seal/
    L3-engine/
    L4-oracle/
    L5-locke/
    L6-inspect/
    L7-cli/
```

Layers (L0-L7):

| Layer | Name | Scope |
|-------|------|-------|
| L0 | kernel | CSE codec, content hashing, seals, Merkle DAG |
| L1 | forms | Policy identity, recipe-to-CSE, CSE-JSON bijection |
| L2 | seal | Path sandboxing, filesystem ops, seal I/O |
| L3 | engine | Build evaluator, caching, oracle dispatch |
| L4 | oracle | LLM backend, fuel-bounded kernel, tool sandbox |
| L5 | locke | Locke compiler (tokenizer, parser, resolver, executor) |
| L6 | inspect | Reports, manifests, dependency graph rendering |
| L7 | cli | CLI commands, terminal rendering, entry points |

Source lives flat in `src/`. Tests and Locke designs are organized by layer.

## Progress

| Layer | Source | Tests | Locke | Status |
|-------|--------|-------|-------|--------|
| L0 | `src/kernel.py` (287 lines) | 6 files, all pass | done | hardened |
| L1 | `src/forms.py` (195 lines) | 3 files, 70 tests, all pass | done | hardened |
| L2 | `src/seal.py` (504 lines) | 4 files, 84 tests, all pass | done | hardened |
| L3 | `src/engine.py` (1027 lines) | 4 files, 81 tests, all pass | done | hardened |
| L4 | `src/oracle.py` (813 lines) | 4 files, 94 tests, all pass | done | hardened |
| L5 | `src/locke.py` (1002 lines) | 4 files, 106 tests, all pass | done | hardened |
| L6 | `src/report.py` (943 lines) | 4 files, 96 tests, all pass | done | hardened |
| L7 | `src/cli.py` (1284 lines) | 3 files, 133 tests, all pass | done | hardened |

### L1 note

The `unsorted` conformance vector contains an extended action form (engine qualname +
command atoms beyond the `b"action"` tag) that does not round-trip through the JSON
bijection.  This is by design: the JSON bijection covers the standard form schema only.
The wire-level round-trip (`encode(parse(w)) == w`) for unsorted still holds at L0.

### L2 note

Merges `build/site.py` (445 lines) and `build/seal.py` (385 lines) into a single
`seal.py` (499 lines).  Key hardening changes vs. liquid beta: (1) single `_atomic_write`
helper eliminates duplicate atomic-write code; (2) `append_history` accepts `traced_reads`
as an explicit parameter instead of reading `husks.utils.events._tool_events` global state;
(3) `OracleBackend` type alias dropped — L2 accepts `Callable | None` and leaves the typed
Protocol to L4.

### L3 note

Merges `build/nodes.py` (267 lines), `build/eval.py` (892 lines), `build/cache.py`
(750 lines), and `build/run.py` (227 lines) — totaling 2,136 lines — into a single
`engine.py` (1,027 lines, 52% reduction).  Key hardening changes vs. liquid beta:
(1) all trace coupling removed — no `husks.utils.trace` imports, all events go into
`S["trace"]`; (2) `_last_store` global removed — `build()` returns the Store, no side
effects; (3) deprecated `_staged()` and `_check_declared_outputs()` removed — only
`BuildTransaction` with explicit validate+promote; (4) `_cache_write_entry` helper
deduplicates cache_put/cache_put_pending; (5) default_oracle_backend simplified
(bootstrap-specific path removed — that's L4 concern).

### L4 note

Merges `oracle/backend.py` (174 lines), `oracle/tools.py` (405 lines),
`oracle/kernel.py` (396 lines), `oracle/llm.py` (331 lines), `oracle/litellm.py`
(135 lines), `oracle/claude_code.py` (249 lines), and `oracle/__init__.py`
(109 lines) — totaling 1,799 lines — into a single `oracle.py` (813 lines,
55% reduction).  Key hardening changes vs. liquid beta: (1) all `husks.utils.trace`
coupling removed — no `T.oracle_step`, `T.tool_call`, `T.tool_result` imports,
events stay in kernel context trace list; (2) `_site_root`/`_readonly_roots` module
globals removed — sandbox always receives explicit roots; (3) module-level `_usage`
default tracker removed — always explicit `UsageTracker` per invocation;
(4) `set_oracle_model`/`get_oracle_model` globals removed — model comes from config;
(5) `live_oracle` back-compat alias removed.

### L5 note

Merges `design/locke/__init__.py` (135 lines), `_tokenizer.py` (195 lines),
`_parser.py` (366 lines), `_resolver.py` (415 lines), `_validation.py` (522 lines),
`_executor.py` (292 lines), `_compiler.py` (29 lines), `_io.py` (147 lines), and
`_show.py` (85 lines) — totaling 2,186 lines — into a single `locke.py`
(1,002 lines, 54% reduction).  Key hardening changes vs. liquid beta:
(1) tokenizer/parser/resolver/validator import only Python stdlib — executor defers
`engine` (L3) and `seal` (L2) imports to function bodies; (2) `compile`/`compile_bytes`
pipeline skipped — depends on `transport.elaborate` which is not yet hardened;
(3) `show()` returns a string instead of printing directly; (4) no `husks.utils`
coupling — all removed.

### L6 note

Merges `manifest.py` (431 lines), `report.py` (693 lines), `graph.py`
(361 lines), `residue.py` (289 lines), and `design/convergence.py`
(170 lines) — totaling 1,944 lines — into a single `report.py`
(943 lines, 51% reduction).  Named `report.py` instead of `inspect.py`
to avoid shadowing Python's stdlib `inspect` module (used by L5 locke.py).
Key hardening changes vs. liquid beta: (1) `assemble()` accepts plain
`list[dict]` events instead of `BuildTrace` object — no `husks.utils.events`
coupling; (2) all ANSI color imports removed — graph rendering uses plain
Unicode symbols; (3) `recompute_root` imported from hardened L0 kernel
for artifact comparison root verification.

### L7 note

Merges `cli/main.py` (389 lines), `cli/helpers.py` (110 lines),
`cli/console.py` (105 lines), `cli/contract.py` (69 lines),
`cli/surface.py` (666 lines), `cli/view.py` (650 lines),
`cli/navigator.py` (210 lines), and `cli/cmd/` subpackage
(`build.py` 940, `inspect.py` 876, `compare.py` 766,
`validate.py` 259, `cache.py` 96) — totaling 5,136 lines —
into a single `cli.py` (1,095 lines, 79% reduction).
Key hardening changes vs. liquid beta: (1) `LiveFrameEmitter`
(animated terminal during build) dropped — final results only;
(2) all `husks.utils.console` coupling removed — ANSI codes
inlined, suppressed when not TTY; (3) `init` command dropped
(scaffolding not hardened); (4) advanced doctor modes
(`--conformance`, `--live`, `--arch`) dropped — basic import
checks + selftest only; (5) L5/L6 imports deferred to function
bodies — no top-level coupling beyond stdlib + argparse;
(6) all events flow as plain dicts through `S["trace"]` — no
`BuildTrace` object; (7) cache export/import restored via L3
engine's `cache_export`/`cache_import`; (8) `--reuse-only` flag
on `run` restored for cache-only M2 builds.

## Delta: hardened vs liquid beta

The hardened stack (`@site/src/`, 5,762 lines across 8 files) re-realizes
the liquid beta (`src/husks/`, ~16,000 lines) at 64% overall reduction.
L0-L6 are functionally equivalent.  L7 is where the cuts are.

### Commands dropped

| Command | Liquid beta | Why dropped |
|---------|------------|-------------|
| `init` | Scaffold a new project from templates | Scaffolding is not part of the core build contract |

### Flags dropped from surviving commands

| Command | Flag | What it does |
|---------|------|-------------|
| `explain` | `--interactive` | Keyboard-driven cursor navigation |
| `explain` | `--diff` | Unified diff of sealed vs current artifacts |
| `explain` | `--seal <subject>` | Show seal material for a rule/artifact/root |
| `explain` | `--artifact` | Specific artifact to include in diff |
| `doctor` | `--conformance` | Run external reader conformance gate |
| `doctor` | `--live` | Check API keys, litellm, ping oracle |
| `doctor` | `--arch` | Verify module dependency DAG against layers.toml |
| `doctor` | `--reader` | Reader command for conformance |
| `compare` | `--diff` | Unified diff of differing generated files |
| global | `--version-json` | Structured version info (CSE_VERSION, schema) |

### Features dropped or simplified

| Feature | Liquid beta | Hardened |
|---------|------------|---------|
| LiveFrameEmitter | ~350 lines, threaded live terminal with per-node state transitions, token/cost counters, log tail windows | Dropped — final results only |
| Interactive navigator | Arrow-key pilot loop for explain (cursor, aperture, quit) | Static single-frame rendering |
| Help animation | Character-by-character diamond typing effect | Static text |
| Aperture levels 2-3 | Seal digest, recipe digest, input/output hashes, trace logs | Only levels 0-1 (node line + primary output) |
| Three-machine proof | Full M1/M2/M3 role enforcement, cost tolerance, evidence tracking | Pairwise artifact comparison only |
| Console abstraction | `Console` class with quiet/color/ANSI management | Inlined `_IS_TTY` check |
| Subcommand help styling | `_StyledHelpAction`, per-command help sections | Standard argparse |

### Three-machine proof

The hardened CLI supports the full three-machine proof workflow:
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

### What is preserved

All core build operations: `check`, `run`, `verify`, `status`,
`history`, `compare`, `doctor`, `cache export`, `cache import`.
`run --reuse-only` for cache-only M2 builds.  Visual output: diamond banner, motif tree,
state glyphs, footer with token/cost/fuel summary.  JSON output mode on
every command.  Report assembly and validation (beta-1 schema).  Freshness
computation, convergence classification, dependency graph rendering.

## Rules

1. Dependencies point strictly downward. L(n) may only import from L(0..n-1).
2. Each layer's Locke design is the contract. Source must satisfy it. Tests must verify it.
3. No changes to the liquid beta (`src/husks/`). This is a clean re-realization.
4. Work proceeds bottom-up. A layer is not hardened until its Locke design seals.
5. Keep the code as minimal as possible, use functional programming.
