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

**generate**: Oracle uses read-file and write-file tools to answer the question in prompt.txt

**validate**: Python action checks response contains "Paris" (live mode) or is valid stub output (stub mode)

## Usage

### Machine 1: Original realization
```bash
husks run design.json --site m1-site --json > m1-report.json
```

### Machine 2: Cache reuse
```bash
# Export cache from Machine 1
husks cache export m1-site/.cache cache.tar.gz

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
Different oracle models may phrase differently, but validation checks basic structure.
Cross-machine equivalence compares output hashes and seal validity.
