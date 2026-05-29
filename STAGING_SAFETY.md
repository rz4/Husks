# Staging Safety: read_path() and write_path() Helpers

## Overview

New explicit helpers prevent accidental live-site mutation during staged builds:
- `read_path(S, name)` - for reading files
- `write_path(S, name)` - for writing files (automatically uses staging)

## Why This Matters

Previously, Python actions could accidentally bypass staging by calling `site_path(S, "output.txt")` without `write=True`. This led to:

1. **Atomicity violations** - partial writes to live site during staging
2. **Failed rollbacks** - actions that fail after writing couldn't be rolled back
3. **Race conditions** - concurrent builds could interfere with each other

## Migration Guide

### Old Pattern (Risky)

```python
def my_action(S):
    # Reads from live site
    data = Path(site_path(S, "input.txt")).read_text()

    # DANGER: Bypasses staging, writes directly to live site!
    result_path = site_path(S, "output.txt")
    Path(result_path).write_text(f"Processed: {data}")
```

### New Pattern (Safe)

```python
def my_action(S):
    # Explicitly read from site
    data = Path(read_path(S, "input.txt")).read_text()

    # SAFE: Automatically uses staging during staged builds
    result_path = write_path(S, "output.txt")
    Path(result_path).write_text(f"Processed: {data}")
```

## Key Benefits

### 1. Deterministic Actions
Actions using `write_path()` automatically respect staging:
- Writes go to staging directory during staged builds
- Outputs promoted atomically on success
- Live site protected from partial writes

### 2. Clear Intent
Code is more readable:
- `read_path()` - "I'm reading this file"
- `write_path()` - "I'm writing this file"
- No need to remember `write=True` parameter

### 3. Backward Compatibility
Legacy actions using `site_path()` still work:
- Framework code uses `site_path(..., write=True)` internally
- Action recipes get fallback to live site (for compatibility)
- Oracle/trial recipes must use staging correctly (no fallback)

## Validation Rules

After introducing `write_path()`, the framework validates outputs:

1. **During staging:**
   - Check staged outputs first
   - For action recipes only: fall back to live site (legacy support)
   - For oracle/trial recipes: no fallback (must use staging)

2. **Outside staging:**
   - Check live site directly

3. **Failed builds:**
   - Actions that raise exceptions never reach output validation
   - Outputs not sealed, staging cleaned up
   - Live site remains untouched

## Examples

### Simple Transform

```python
from husks.build import rule, action, read_path, write_path
from pathlib import Path

def transform_action(S):
    input_text = Path(read_path(S, "input.txt")).read_text()
    output_text = input_text.upper()
    Path(write_path(S, "output.txt")).write_text(output_text)

node = rule(
    "uppercase",
    inputs=["input.txt"],
    outputs=["output.txt"],
    recipe=action(transform_action),
)
```

### Multiple Inputs/Outputs

```python
def combiner_action(S):
    # Read multiple inputs
    data1 = Path(read_path(S, "data1.txt")).read_text()
    data2 = Path(read_path(S, "data2.txt")).read_text()

    # Write multiple outputs (all staged automatically)
    Path(write_path(S, "combined.txt")).write_text(f"{data1}{data2}")
    Path(write_path(S, "reversed.txt")).write_text(f"{data2}{data1}")
```

### Nested Paths

```python
def nested_action(S):
    output_path = write_path(S, "reports/2024/summary.txt")
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    Path(output_path).write_text("Report content")
```

## Testing

New test suite: `tests/test_read_write_path_helpers.py`
- Verifies staging isolation during staged builds
- Confirms live-site writes when staging not active
- Tests nested paths and multiple inputs/outputs
- Proves live-site protection during staging

## Implementation Details

### Location
- `src/husks/build/site.py` - Helper definitions
- `src/husks/build/__init__.py` - Public exports
- `src/husks/build/eval.py` - Output validation with fallback logic

### Helper Functions

```python
def read_path(S: Store, name: str) -> str:
    """Resolve name for reading from the site."""
    return site_path(S, name, write=False)

def write_path(S: Store, name: str) -> str:
    """Resolve name for writing to the site (staging-aware)."""
    return site_path(S, name, write=True)
```

### Legacy site_path()
Still available but marked deprecated:
```python
# Deprecated - use read_path() or write_path()
site_path(S, name, write=False)
```

## Summary

- **Added:** `read_path()` and `write_path()` helpers
- **Updated:** Output validation with recipe-specific fallback
- **Migrated:** Example action to use new helpers
- **Tested:** 228 passing tests (6 new tests for helpers)
- **Compatible:** Legacy `site_path()` still works
- **Safe:** Prevents accidental live-site mutation during staging
