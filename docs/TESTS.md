# Test Suite

The suite is organized by codebase layer. Each directory under `tests/`
exercises one layer of `src/husks/`, plus a small set of cross-layer
integration tests at the top level. The legacy pre-consolidation suite is kept
out of the run (`norecursedirs = ["legacy"]`).

765 tests, all deterministic, run in a few seconds with stub oracles.

## Layer suites

| Suite | Layer | Tests | Covers |
| :-- | :-- | --: | :-- |
| `tests/L0-kernel/` | L0 kernel | 86 | CSE codec, Merkle digest, seals, verify, security |
| `tests/L1-forms/` | L1 forms | 70 | Recipe identity, elaboration, CSE↔JSON bijection |
| `tests/L2-seal/` | L2 seal | 84 | Path sandboxing, filesystem ops, seal I/O, store |
| `tests/L3-engine/` | L3 engine | 81 | Build evaluator, caching, node eval |
| `tests/L4-oracle/` | L3 oracle | 94 | Backend, fuel-bounded kernel, tool sandbox, gate |
| `tests/L5-locke/` | L5 locke | 106 | Tokenizer, parser, validation, executor |
| `tests/L6-inspect/` | L6 report | 96 | Convergence, dependency graph, manifest, report |
| `tests/L7-cli/` | L7 cli | 138 | Command dispatch, config, helpers, rendering |

## Cross-layer integration

| File | Covers |
| :-- | :-- |
| `tests/test_three_machine_stub.py` | The full offline three-machine proof: M1 fresh, cache export/import, M2 reuse-only, M3 fresh, `compare` asserting `proof.satisfied` |
| `tests/test_import_output_rejection.py` | Cache import rejects outputs that do not match their declared seals |
| `tests/test_staging_sandbox.py` | Staging directory containment and path-escape rejection |

## Running tests

```bash
# Full deterministic suite
python -m pytest tests/

# One layer
python -m pytest tests/L0-kernel/

# The three-machine spine
python -m pytest tests/test_three_machine_stub.py

# Fast tests only (exclude slow wheel/subprocess tests)
python -m pytest tests/ -m "not slow"
```

## Markers

| Marker | Meaning |
| :-- | :-- |
| `slow` | Wheel builds or subprocess-heavy tests |

## Adding new tests

Place a test in the directory for the lowest layer it exercises. A test that
drives the CLI belongs in `tests/L7-cli/`; a test of the seal preimage belongs
in `tests/L0-kernel/`. Tests that span the whole stack (the three-machine
proof, sandbox containment) live at the `tests/` top level.

The architecture invariant itself is checked by `husks doctor --arch`, which
validates module imports against [`../layers.toml`](../layers.toml).
