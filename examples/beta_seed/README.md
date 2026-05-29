# Beta Seed Example

Deterministic seed design for three-machine beta testing.

## Purpose

This example demonstrates Husks beta capabilities:
- Portable seed design with relative site_inputs
- Oracle-backed generation with read-file and write-file tools
- Deterministic validation (checks for "Paris" in live mode)
- Cross-machine reproducibility via cache export/import

## Design Structure

```
prompt.txt → [generate] → response.txt → [validate] → validation.txt
```

**generate**: Oracle uses read-file and write-file tools to answer the question in prompt.txt. Output must follow structured format: `ANSWER: <answer>`

**validate**: Python action enforces deterministic output contract (Task 5):
- MUST start with `ANSWER: `
- Live mode: answer should be `Paris`
- Stub mode: answer should be stub placeholder
- Rejects malformed output (no prefix, wrong format, empty response)

## Usage

### Machine 1: Original realization
```bash
husks run design.json --site m1-site --json > m1-report.json
```

### Machine 2: Cache reuse
```bash
# Export cache from Machine 1
husks cache export cache.tar.gz --site m1-site

# Import and reuse
husks cache import cache.tar.gz --site m2-site
husks run design.json --site m2-site --reuse-only --json > m2-report.json
```

### Machine 3: Independent re-realization
```bash
husks run design.json --site m3-site --json > m3-report.json
```

## Expected Behavior

**Machine 1**: Executes oracle, pays cost C1, produces valid artifact
**Machine 2**: Reuses cache, zero oracle cost, equivalent artifact
**Machine 3**: Executes oracle independently, cost C3 ≈ C1, valid artifact

## Determinism

The prompt ("What is the capital of France?") has a factual, stable answer.
The strengthened validator (Task 5) enforces structured output format:
- Required format: `ANSWER: <answer>`
- Valid answers: `Paris` (case-insensitive) or stub placeholders
- Rejects unstructured responses

Cross-machine equivalence compares output hashes and seal validity.

## Testing Modes

### Stub Mode (Default for CI)
```bash
husks run design.json --site ./site --stub --json
```
- No API calls, zero cost
- Produces: `ANSWER: Stub oracle output`
- Passes deterministic validator
- Three-machine proof tested in CI

### Live Mode (Task 6 - Manual/Optional)
```bash
export ANTHROPIC_API_KEY=sk-...
husks run design.json --site ./site --json
```
- Uses live Claude API
- Produces: `ANSWER: Paris` (or similar structured response)
- Costs ~$0.0008 per run
- Validates same report schema as stub mode

**Live readiness tests** (skipped by default):
```bash
# Run live tests (requires API key and explicit opt-in)
export ANTHROPIC_API_KEY=sk-...
export HUSKS_ENABLE_LIVE_TESTS=1
pytest tests/test_live_oracle_readiness.py -v
```

These tests verify:
- Live oracle produces valid structured output
- Report schema matches stub mode
- Cache reuse works with live oracle
- Three-machine proof works end-to-end

**Note:** Live tests are skipped in CI to avoid API costs. They serve as manual
validation that the live path is structurally sound.
