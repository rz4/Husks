# Test Suite

74 tests numbered sequentially. File names encode the development phase they belong to.

## Phases

**CSE GENESIS** (test 0) -- Foundation. CSE codec, hashing, seals, Merkle roots.

**SOLID ALPHA** (tests 1-67) -- Stable, tested. Alpha engine regression, gate building blocks, cache trust, CLI contracts, and other functional tests. All deterministic.

**LIQUID BETA** (tests 68-73) -- Current development frontier. Three-machine proof, beta100 contract, CLI acceptance. The cap moves forward as tests solidify.

## File Naming Convention

```
test_{PHASE}_{N}_{name}.py

test_CSE_0_cse_codec.py         # CSE GENESIS
test_SOLID_1_golden_vector.py   # SOLID ALPHA
test_LIQUID_72_beta100.py       # LIQUID BETA
```

## Running Tests

```bash
# Full deterministic suite
pytest tests/ --ignore=tests/test_SOLID_50_live_oracle_readiness.py -v --tb=short

# Alpha engine regression only
pytest -m alpha

# Beta proof boundary only
pytest -m beta

# Specific gate
pytest -m gate_d

# Three-machine proof spine
pytest tests/test_LIQUID_68_beta_three_machine.py \
       tests/test_LIQUID_69_three_machine_proof.py \
       tests/test_LIQUID_70_three_machine_cli_acceptance.py \
       -v --tb=short

# Fast tests only (exclude wheel builds)
pytest -m "not slow"
```

## Sequential Index

### CSE GENESIS (0)

| # | File | Purpose |
|---|------|---------|
| 0 | `test_CSE_0_cse_codec.py` | CSE parse/encode/seal/Merkle |

### SOLID ALPHA: Core Engine (1-15)

| # | File | Markers | Purpose |
|---|------|---------|---------|
| 1 | `test_SOLID_1_golden_vector.py` | alpha | Golden conformance vectors |
| 2 | `test_SOLID_2_json_bijection.py` | alpha | JSON transport round-trip |
| 3 | `test_SOLID_3_flat_elaboration.py` | alpha | Design IR expansion |
| 4 | `test_SOLID_4_layer_isolation.py` | alpha | Module boundary enforcement |
| 5 | `test_SOLID_5_build_verify.py` | alpha | Build + verify pipeline |
| 6 | `test_SOLID_6_oracle_guard.py` | alpha | Oracle guard rails |
| 7 | `test_SOLID_7_skill_pipeline.py` | alpha | Two-form vocabulary, convergence |
| 8 | `test_SOLID_8_cross_language.py` | alpha | JS reader reproduces Python roots |
| 9 | `test_SOLID_9_input_order_invariance.py` | alpha | Input ordering does not affect root |
| 10 | `test_SOLID_10_cli_exit_code.py` | alpha | CLI exit code contract |
| 11 | `test_SOLID_11_output_guard.py` | alpha | Output validation guards |
| 12 | `test_SOLID_12_fuel_batch.py` | alpha | Fuel budget batching |
| 13 | `test_SOLID_13_trial_fuel.py` | alpha | Trial fuel accounting |
| 14 | `test_SOLID_14_recipe_identity.py` | alpha | Recipe identity normalization |
| 15 | `test_SOLID_15_triage_regressions.py` | alpha | Triage regression collection |

### SOLID ALPHA: Gates (16-26)

| # | File | Markers | Gate | Purpose |
|---|------|---------|------|---------|
| 16 | `test_SOLID_16_gate_a_site_inputs.py` | beta, gate_a | A | Site inputs resolution |
| 17 | `test_SOLID_17_gate_a_husks_init.py` | beta, gate_a | A | Project setup and skill install |
| 18 | `test_SOLID_18_gate_b_build_transaction.py` | beta, gate_b | B | Atomic commit/rollback |
| 19 | `test_SOLID_19_gate_b_output_validation.py` | beta, gate_b | B | Output validation before commit |
| 20 | `test_SOLID_20_gate_b_import_hardening.py` | beta, gate_b | B | Safe module import boundary |
| 21 | `test_SOLID_21_gate_b_output_type_policy.py` | beta, gate_b | B | Directory/file type enforcement |
| 22 | `test_SOLID_22_gate_cf_compare_runs.py` | beta, gate_c, gate_f | C,F | Three-machine comparison + cost |
| 23 | `test_SOLID_23_gate_f_report_schema.py` | beta, gate_f | F | Beta-1 report schema contract |
| 24 | `test_SOLID_24_gate_g_root_verification.py` | beta, gate_g | G | Root verification contract |
| 25 | `test_SOLID_25_gate_h_shell_failure_isolation.py` | beta, gate_h | H | Shell failure isolation |
| 26 | `test_SOLID_26_gate_g_wheel_smoke.py` | beta, gate_g, slow | G | Wheel install + three-machine proof |

### SOLID ALPHA: Cache (27-37)

| # | File | Markers | Purpose |
|---|------|---------|---------|
| 27 | `test_SOLID_27_cache_lookup.py` | beta, gate_d | Cache miss then hit |
| 28 | `test_SOLID_28_cache_export_import.py` | beta, gate_d | Export/import round-trip |
| 29 | `test_SOLID_29_cache_reuse_only.py` | beta, gate_d | Reuse-only mode |
| 30 | `test_SOLID_30_cache_ledger.py` | beta, gate_d | Ledger accounting |
| 31 | `test_SOLID_31_cache_provenance.py` | beta, gate_d | Provenance tracking |
| 32 | `test_SOLID_32_cache_import_security.py` | beta, gate_d | Import security (no path traversal) |
| 33 | `test_SOLID_33_cache_layout.py` | beta, gate_d | Key determinism and seal validation |
| 34 | `test_SOLID_34_cache_validation_path.py` | beta, gate_d | Single canonical validation path |
| 35 | `test_SOLID_35_cache_write_failure.py` | beta, gate_d | Write failure semantics |
| 36 | `test_SOLID_36_cache_report_contract.py` | beta, gate_f | oracle_calls, cache_hits fields |
| 37 | `test_SOLID_37_cli_reuse_only.py` | -- | CLI reuse-only flag |

### SOLID ALPHA: CLI (38-50)

| # | File | Purpose |
|---|------|---------|
| 38 | `test_SOLID_38_cli_contract.py` | CLI command contracts |
| 39 | `test_SOLID_39_cli_navigator.py` | Interactive explain navigator |
| 40 | `test_SOLID_40_cli_explain.py` | Explain command output |
| 41 | `test_SOLID_41_cli_compare.py` | Compare command output |
| 42 | `test_SOLID_42_json_error_output.py` | JSON error formatting |
| 43 | `test_SOLID_43_public_beta_cli.py` | Public CLI surface |
| 44 | `test_SOLID_44_unknown_fields.py` | Unknown field detection |
| 45 | `test_SOLID_45_reader_command_parsing.py` | Reader command parsing |
| 46 | `test_SOLID_46_graph_validation.py` | Build graph validation |
| 47 | `test_SOLID_47_manifest_validation.py` | Manifest schema validation |
| 48 | `test_SOLID_48_recipe_identity_audit.py` | Recipe identity audit |
| 49 | `test_SOLID_49_version_terminology.py` | Version/terminology consistency |
| 50 | `test_SOLID_50_live_oracle_readiness.py` | Live oracle readiness (skipped without API key) |

### SOLID ALPHA: Functional (51-67)

| # | File | Purpose |
|---|------|---------|
| 51 | `test_SOLID_51_artifact_equivalence.py` | Artifact identity and equivalence |
| 52 | `test_SOLID_52_file_hashing_semantics.py` | File hashing semantics |
| 53 | `test_SOLID_53_file_sig_directories.py` | File signature for directories |
| 54 | `test_SOLID_54_trial_binary_outputs.py` | Trial binary output handling |
| 55 | `test_SOLID_55_fuel_accounting.py` | Fuel accounting invariants |
| 56 | `test_SOLID_56_conditional_seed_semantics.py` | Conditional seed semantics |
| 57 | `test_SOLID_57_freshness_removed_inputs.py` | Freshness after input removal |
| 58 | `test_SOLID_58_seal_based_freshness.py` | Seal-based freshness detection |
| 59 | `test_SOLID_59_husk_path_security.py` | Husk path traversal security |
| 60 | `test_SOLID_60_usage_in_store.py` | Usage tracking in store |
| 61 | `test_SOLID_61_tree_sandbox_traversal.py` | Tree sandbox traversal |
| 62 | `test_SOLID_62_shell_staging.py` | Shell staging isolation |
| 63 | `test_SOLID_63_shell_failure_symlink_bypass.py` | Symlink bypass prevention |
| 64 | `test_SOLID_64_tool_dispatch_hardening.py` | Tool dispatch hardening |
| 65 | `test_SOLID_65_read_write_path_helpers.py` | Read/write path helpers |
| 66 | `test_SOLID_66_oracle_failure_modes.py` | Oracle failure mode handling |
| 67 | `test_SOLID_67_verification_write_failures.py` | Verification write failure handling |

### LIQUID BETA (68-73)

| # | File | Markers | Purpose |
|---|------|---------|---------|
| 68 | `test_LIQUID_68_beta_three_machine.py` | beta, gate_e | Programmatic three-machine proof |
| 69 | `test_LIQUID_69_three_machine_proof.py` | beta | Three-machine proof validation |
| 70 | `test_LIQUID_70_three_machine_cli_acceptance.py` | beta, gate_g | End-to-end CLI three-machine proof |
| 71 | `test_LIQUID_71_cli_rendering_contract.py` | beta | CLI rendering contract |
| 72 | `test_LIQUID_72_beta100.py` | beta | Beta100 proof contract |
| 73 | `test_LIQUID_73_beta100_public_cli.py` | beta | Beta100 public CLI surface |

## Beta Proof Spine

The minimal set that validates the three-machine proof:

| Test | Gates | Purpose |
|------|-------|---------|
| `test_LIQUID_70_three_machine_cli_acceptance.py` | G | End-to-end three-machine proof via CLI |
| `test_SOLID_22_gate_cf_compare_runs.py` | C, F | Report comparison and cost validation |
| `test_SOLID_26_gate_g_wheel_smoke.py` | G | Clean wheel install runs full proof |

If these three pass, the beta contract holds.

## Gate Reference

| Gate | Focus | Tests |
|------|-------|-------|
| A | Seed portability, site inputs | 16, 17 |
| B | Transaction safety, output validation | 18, 19, 20, 21 |
| C | Artifact identity, comparison | 22 |
| D | Cache reuse and trust | 27-35 |
| E | Independent re-realization | 68 |
| F | Report and cost proof | 22, 23, 36 |
| G | Release smoke | 24, 26, 70 |
| H | Bloat control | 25 |

## CI Jobs

| Job | What it runs |
|-----|-------------|
| **Wheel Smoke** | `test_SOLID_26_gate_g_wheel_smoke.py` across Python 3.10-3.13 |
| **Solid Alpha** | Three-machine proof spine + full `pytest -m "not beta"` suite |
| **Liquid Beta** | Manual dispatch only; live oracle tests with API key |

## Adding New Tests

**Extending SOLID:** Append after the last test in the relevant group. Use the next available number. Mark with appropriate `@pytest.mark` decorators.

**Extending LIQUID:** Add at the end (next number after 73). Mark with `@pytest.mark.beta`. These are the frontier -- they may break and that's expected.

**Promoting LIQUID to SOLID:** When a liquid test stabilizes, renumber it into the SOLID range and shift the LIQUID boundary forward.

## Pytest Markers

Defined in `pyproject.toml`:

| Marker | Purpose |
|--------|---------|
| `alpha` | Core engine regression (tests 0-15) |
| `beta` | Three-machine proof boundary |
| `gate_a` through `gate_h` | Specific verification gates |
| `slow` | Wheel builds or subprocess-heavy tests |
