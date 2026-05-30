# Test Organization

This document maps Husks tests to their purpose in the beta proof boundary.

## Test Philosophy

**Alpha tests** (numbered): Chronological engine build-up. Legacy core regression tests that validate the engine was built correctly, layer by layer.

**Beta tests** (semantic): Proof-boundary regressions. Organized by gates A-H to validate the three-machine proof contract.

## Running Tests by Category

```bash
# All beta proof tests
pytest -m beta

# Specific gate
pytest -m gate_d

# Cache trust boundary (Gate D)
pytest -m gate_d

# Three-machine proof spine
pytest tests/test_three_machine_cli_acceptance.py tests/test_compare_runs.py tests/test_wheel_smoke.py

# Fast tests only (exclude slow wheel builds)
pytest -m "not slow"

# Alpha core regression
pytest -m alpha
```

## Beta Proof Spine

The minimal test set that validates the three-machine proof:

| Test | Gates | Purpose |
|------|-------|---------|
| `test_three_machine_cli_acceptance.py` | G | End-to-end three-machine proof via CLI |
| `test_compare_runs.py` | C, F | Report comparison and cost validation |
| `test_wheel_smoke.py` | G | Clean wheel install runs full beta proof |

If these three pass, the beta contract holds.

## Gate Mapping

### Gate A: Seed Portability
- `test_site_inputs.py` - Site inputs resolution
- `test_beta_seed_validator.py` - Canonical seed validation
- `test_husks_init.py` - Project setup and skill installation

### Gate B: Transaction Safety
- `test_build_transaction.py` - Atomic commit/rollback
- `test_output_validation_staging.py` - Output validation before commit
- `test_output_type_policy.py` - Directory/file type enforcement
- `test_import_hardening.py` - Safe module import boundary

### Gate C: Artifact Identity and Comparison
- `test_compare_runs.py` - Three-machine proof validation
- `test_beta_seed_validator.py` - Deterministic output contract
- Cross-check: compare-runs validates root equivalence

### Gate D: Cache Reuse and Trust
- `test_cache_poisoning.py` - Cache tampering detection
- `test_cache_validation_path.py` - Single canonical validation path
- `test_cache_import_security.py` - Safe tar import (no path traversal)
- `test_cache_layout.py` - Cache key determinism and seal validation

### Gate E: Independent Re-realization
- `test_beta_three_machine.py` - Programmatic API three-machine proof
- `test_beta_seed_validator.py` - Validator strengthening
- Cross-check: M1 and M3 costs comparable

### Gate F: Report and Cost Proof
- `test_compare_runs.py` - Oracle evidence validation
- `test_report_schema_version.py` - Beta-1 schema contract
- `test_cache_report_contract.py` - oracle_calls, cache_hits fields

### Gate G: Release Smoke
- `test_wheel_smoke.py` - Clean venv install + three-machine proof
- `test_three_machine_cli_acceptance.py` - Full CLI beta flow
- `test_doctor.py` - doctor --selftest conformance check

### Gate H: Bloat Control
- No dedicated tests yet - manual code review
- Monitor: duplicate dict keys, unnecessary abstractions

## Alpha Tests (Legacy Core)

These validate the engine was built correctly, layer by layer:

| Test | Purpose |
|------|---------|
| `test_1_core.py` | CSE codec, hashing, seals |
| `test_2_transport.py` | JSON bijection |
| `test_3_flat_elaboration.py` | Design IR expansion |
| `test_4_layer_isolation.py` | Module boundary enforcement |
| `test_5_recipe_canonicalization.py` | Recipe normalization |
| `test_6_dependency_resolution.py` | Build graph construction |
| `test_7_fuel_accounting.py` | Fuel budget tracking |
| `test_8_stale_detection.py` | Incremental rebuild logic |
| `test_9_oracle_integration.py` | Oracle backend integration |
| `test_10_cli_exit_code.py` | CLI exit code contract |
| `test_11_output_guard.py` | Output validation |

## Test File Naming Convention

- **Numbered** (`test_N_*.py`): Alpha tests - chronological engine regression
- **Semantic** (`test_*.py`): Beta tests - organized by feature/gate
- **Prefixed** (`test_beta_*.py`): Explicitly beta-focused tests

## Adding New Tests

**For beta proof boundary:**
- Add to semantic tests (no number prefix)
- Mark with `@pytest.mark.beta` and relevant gate(s)
- Update this TESTS.md with gate mapping
- Add to proof spine if critical

**For core engine regression:**
- Add to semantic tests (beta tests can also catch core regressions)
- Mark with `@pytest.mark.alpha` if purely internal engine logic
- Update this TESTS.md

## Maintenance Notes

- **Do not renumber alpha tests** - they are chronological archaeology
- **Beta tests are proof contracts** - changes require gate review
- **Proof spine tests are sacred** - must always pass before release
- **Slow tests** should be marked `@pytest.mark.slow` for CI optimization
