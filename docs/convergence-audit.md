# Convergence Audit

Full conformance audit of the four sources of truth: `src/`, `tests/`,
`lockes/`, `docs/`.  Performed 2026-06-06 against commit `9b3ead0`
(pre-audit HEAD).  Resolved in commit `b84af7a`.

---

## Scope

Every layer (L0--L7) was cross-referenced across all four surfaces:

| Surface | Role | Files |
| :-- | :-- | --: |
| `src/husks/` | Implementation | 10 modules |
| `tests/` | Verification | 52 test modules + 3 cross-layer |
| `lockes/` | Contracts | 8 `.locke` files |
| `docs/` | Documentation | 8 markdown files |

Each Locke contract was compared function-by-function, field-by-field,
and import-by-import against the corresponding source module.  Each doc
was compared against both source and contract.  Test counts were
verified via `pytest --co` collection against the claims in `TESTS.md`.

---

## Findings: 19 discrepancies

### Critical (structural disagreements)

1. **architecture.md OracleBackend signature wrong.**
   Documented `__call__(S, rule_name, recipe, outputs) -> dict | None`.
   Actual: `run(S, rule_name, recipe, outputs, config) -> RealizedCost`
   with a `name: str` class attribute.  Four differences in a single
   protocol definition.

2. **architecture.md assigned oracle.py to L3.**
   The Locke contract assigns it to L4.  oracle.py imports zero husks
   modules; it is invoked by L3 through callback, not by import.

3. **architecture.md false hashlib centralization claim.**
   Stated: "No other module calls hashlib directly."  In fact six
   modules (`forms.py`, `seal.py`, `engine.py`, `oracle.py`,
   `report.py`, `cli.py`) import and call `hashlib.sha256()` directly.

4. **architecture.md phantom `live_oracle()` function.**
   Documented with signature, purpose, and behavior.  Does not exist
   anywhere in the codebase.

5. **TESTS.md test counts stale.**
   Claimed 765 total (L7: 138).  Actual: 777 total (L7: 150).

6. **TESTS.md L4 layer mislabeled.**
   Table said "L3 oracle" for the `tests/L4-oracle/` suite.

7. **L6-inspect.locke phantom dataclass fields.**
   Listed `CliTrace.stdout`, `CliTrace.stderr`,
   `CliNode.output_hash`, `CliNode.seal_digest`,
   `CliNode.recipe_digest`, `CliNode.input_hashes`,
   `CliNode.output_hashes`, and `CliResidue.run_count`.
   None of these fields exist on the actual dataclasses.

8. **L7-cli.locke phantom `kernel.selftest`.**
   Documented `_cmd_doctor --selftest runs kernel.selftest`.
   No `selftest` function exists in `kernel.py`.

9. **config.py unlayered.**
   architecture.md assigned it to L4.  No Locke contract exists for it.

### Moderate (incomplete or inaccurate documentation)

10. **L0-kernel.locke omitted `typing` from stdlib imports.**
11. **L5-locke.locke falsely listed `inspect` as a top-level import.**
12. **architecture.md `compile(design)` should be `compile_design(design)`.**
13. **architecture.md trial report `outputs` schema showed list-of-objects;
    actual is flat dict `{name: hash}`.**
14. **architecture.md said manifest written by `engine.py`;
    function is defined in `seal.py`.**
15. **architecture.md referenced dropped `explain` command.**
16. **L2-seal.locke `fresh_store` signature incomplete**
    (omitted `oracle_backend_name`, `readonly_dirs`).
17. **engine.py unused import:** `from contextlib import contextmanager`
    (imported, never applied as decorator).
18. **L4-oracle.locke omitted `OracleHaltError` exception class.**
19. **L3-engine.locke listed `contextlib` in imports, omitted `typing`.**

---

## Fixes applied

| File | Change |
| :-- | :-- |
| `docs/TESTS.md` | Total 765->777, L7 138->150, "L3 oracle"->"L4 oracle" |
| `docs/architecture.md` | oracle.py L3->L4; config.py L4->support module; removed false hashlib claim; fixed OracleBackend to `run()` with `name`, `config`, `RealizedCost`; removed phantom `live_oracle()`; `compile`->`compile_design`; fixed manifest/trial-report authorship and schema; removed phantom `explain` reference |
| `lockes/L0-kernel/L0-kernel.locke` | Added `typing` to stdlib imports |
| `lockes/L2-seal/L2-seal.locke` | Expanded `fresh_store` signature |
| `lockes/L3-engine/L3-engine.locke` | Removed `contextlib`, added `typing` |
| `lockes/L4-oracle/L4-oracle.locke` | Added `OracleHaltError` to Types |
| `lockes/L5-locke/L5-locke.locke` | Removed false `inspect` import |
| `lockes/L6-inspect/L6-inspect.locke` | Removed 8 phantom dataclass fields, added actual `site_inputs` field |
| `lockes/L7-cli/L7-cli.locke` | Removed phantom `kernel.selftest`, removed "navigator for explain mode" from header |
| `src/husks/engine.py` | Removed unused `from contextlib import contextmanager` |

10 files changed, 38 insertions, 45 deletions.

---

## Verification

```
$ python -m pytest tests/ -v --tb=short
============================= 777 passed in 2.52s ==============================
```

Zero failures.  Zero new tests required.  The only source change was
removing an unused import in `engine.py`, which is semantically inert.

---

## Method

1. Collected full text of all four surfaces (src, tests, lockes, docs)
   via parallel agents.
2. Ran the complete test suite to establish baseline (777 passed).
3. Cross-referenced every function, class, constant, type alias,
   dataclass field, import statement, and signature across all four
   surfaces for each of the eight layers.
4. Applied fixes to docs, lockes, and one dead import in src.
5. Re-ran the full test suite to confirm no regressions.
