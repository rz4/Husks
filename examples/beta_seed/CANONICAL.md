# Canonical Beta Seed (Task 12)

This directory contains the **CANONICAL** beta seed design for Husks.

## What is the Beta Seed?

The beta seed is a deterministic, minimal design that demonstrates all core beta capabilities:
- Oracle-backed generation with tool use (read-file, write-file)
- Deterministic validation with structured output format
- Cross-machine reproducibility via cache export/import
- Three-machine proof (M1 builds, M2 reuses, M3 rebuilds)

## Why One Canonical Seed?

**Task 12: Keep one canonical beta seed**

Having a single canonical beta seed ensures:
1. **Consistency**: All beta tests validate the same design structure
2. **Maintainability**: Updates to the beta contract update one place
3. **Clarity**: No confusion about which version is "correct"
4. **Reproducibility**: Same design across all machines and environments

## Canonical Seed Contents

```
examples/beta_seed/
├── design.json      - Canonical beta design (2 rules: generate + validate)
├── prompt.txt       - Seed input ("What is the capital of France?")
├── validate.py      - Deterministic validator (Task 5: strengthened)
├── README.md        - Usage documentation
└── CANONICAL.md     - This file
```

## Usage in Tests

### CLI-Based Tests (Preferred)
Use the canonical seed via CLI commands:
```python
beta_seed_dir = Path(__file__).parent.parent / "examples" / "beta_seed"
design_path = beta_seed_dir / "design.json"

result = run_husks_cli("run", str(design_path), "--site", str(site), "--stub", "--json")
```

Tests using canonical seed:
- `test_compare_runs.py` - Validates three-machine proof
- `test_three_machine_cli_acceptance.py` - CLI acceptance tests
- `test_live_oracle_readiness.py` - Live oracle validation
- `test_beta_seed_validator.py` - Validator tests

### Programmatic API Tests (Unit Testing)
`test_beta_three_machine.py` uses a simplified inline design for unit testing
the programmatic API. This is acceptable for low-level testing but **not** a
canonical seed variant. The canonical seed is in `examples/beta_seed/`.

## DO NOT Create Duplicate Seeds

If you need to test a variant:
1. Consider if the canonical seed can be parameterized instead
2. If absolutely necessary, create a clearly-named non-beta example
3. Document why it differs from the canonical seed
4. Reference the canonical seed in comments

## Updating the Canonical Seed

When updating the canonical seed:
1. Update `examples/beta_seed/design.json` and related files
2. Verify all tests still pass: `pytest tests/test_*beta*.py -v`
3. Update this CANONICAL.md to document changes
4. Ensure changes are backward-compatible or version-bumped

## Related Documentation

- `examples/beta_seed/README.md` - Usage guide and testing modes
- `docs/cli.md` - CLI reference for running seeds
- Beta acceptance criteria in project planning docs
