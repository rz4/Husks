# CLI Beta 95 - Unified Architecture

**Status**: Beta 95 Implementation Complete

This document describes the unified CLI architecture implemented for the Beta 95 release.

## Overview

The CLI now uses a **Command → Residue → Surface** architecture that provides:
- One shared state model (CliResidue + CliNode)
- One visual DAG renderer with unified grammar
- One JSON surface with shared vocabulary across all commands

## Visual Grammar

### Symbols
- **◆** Oracle (LLM-powered generative rule)
- **▫** Action (deterministic shell command)
- **◇** Trial (non-committing exploration)

### States
- **dry**: Node exists in design but hasn't run (dim color)
- **sealed**: Previously built, inputs unchanged, outputs fresh (green)
- **cached**: Reused from cache with explicit evidence (cyan + ⚡)
- **stale**: Recipe/inputs changed, or outputs missing (yellow)
- **failed**: Execution failed with diagnosis (red)

### Format
```
◆ rule-name oracle sealed ⚡8 $0.0012
▫ action-name action failed
◆ cached-rule oracle cached ⚡
```

## Commands

### check

Validate a design without execution.

```bash
# Dry conformance (design validation)
husks check design.json

# With site overlay (shows freshness states)
husks check design.json --site .husk

# Verbose mode (detailed output)
husks check design.json --verbose

# JSON output
husks check design.json --json
```

**Output (visual)**:
```
  design: my-project
  ──────────────────────────────────────────────────

  ◆ generate-code oracle dry
  ▫ run-tests action dry

  dry  fuel 0/12
```

**Output (JSON)**:
```json
{
  "command": "check",
  "status": "dry",
  "design": "my-project",
  "site": null,
  "root": null,
  "fuel": {"budget": 12, "used": 0},
  "cost": 0.0,
  "nodes": [
    {"name": "generate-code", "kind": "oracle", "state": "dry"},
    {"name": "run-tests", "kind": "action", "state": "dry"}
  ],
  "summary": {"passes": 0, "fails": 0}
}
```

### run

Execute a design with oracle backend.

```bash
# Run with stub oracle (no LLM calls)
husks run design.json --stub --site .husk

# Run with live oracle
husks run design.json --site .husk

# Verbose mode
husks run design.json --stub --site .husk --verbose

# JSON output
husks run design.json --stub --site .husk --json
```

**Output (visual)**:
```
  design: my-project
  site:   .husk
  ──────────────────────────────────────────────────

  ◆ generate-code oracle sealed ⚡8 $0.0012
  ▫ run-tests action sealed

  committed  root c97c95be96  fuel 10/12  $0.0012  (2 pass)
```

**Output (cached rerun)**:
```
  ◆ generate-code oracle cached ⚡
  ▫ run-tests action cached ⚡

  committed  root c97c95be96  fuel 2/12  (2 pass)
```

### status

Show site conformance state.

```bash
# Check site freshness
husks status design.json --site .husk

# JSON output
husks status design.json --site .husk --json

# Exit with error if stale
husks status --site .husk --fail-if-stale
```

**Output (visual)**:
```
  design: my-project
  site:   .husk
  ──────────────────────────────────────────────────

  ◆ generate-code oracle sealed
  ▫ run-tests action stale

  committed  root c97c95be96  (1 pass, 1 fail)
```

## JSON Vocabulary

All commands (`check`, `run`, `status`) output the same JSON structure:

### Top-Level Fields
- **command**: Command that produced output (`check`|`run`|`status`)
- **status**: Build status (`dry`|`committed`|`halted`)
- **design**: Design name
- **site**: Site directory path (null for check without --site)
- **root**: Build root hash (null if not committed)
- **fuel**: `{"budget": int, "used": int}`
- **cost**: Total USD cost of oracle calls
- **nodes**: Array of node objects
- **summary**: `{"passes": int, "fails": int}`

### Node Fields
- **name**: Rule name
- **kind**: Rule kind (`oracle`|`action`|`trial`)
- **state**: Node state (`dry`|`sealed`|`cached`|`stale`|`failed`)
- **fuel**: Fuel consumed (optional)
- **cost**: USD cost (optional)
- **cache**: True if reused from cache (optional)
- **output_hash**: Content hash of outputs (optional)
- **diagnosis**: Error message for failed nodes (optional)
- **stale_reason**: Reason for staleness (optional)

## Flags

### Common Flags
- **--json**: Output as pure JSON (no ANSI codes, machine-readable)
- **--verbose**: Show detailed output (mutually exclusive with --json)

### Command-Specific Flags

**check**:
- **--site**: Overlay site conformance states from manifest

**run**:
- **--stub**: Use stub oracle (no LLM calls, placeholder outputs)
- **--site**: Site directory
- **--model**: LLM model (default: claude-haiku-4-5-20251001)
- **--reuse-only**: Only use cached results, never call oracle
- **--soft-fail**: Exit 0 even when build halts

**status**:
- **--fail-if-dirty**: Exit 4 if any artifact is modified
- **--fail-if-stale**: Exit 4 if any rule is stale

## Examples

### Complete Workflow

```bash
# 1. Initialize project
husks init my-project
cd my-project

# 2. Check design
husks check design.json

# 3. Run with stub oracle
husks run design.json --stub --site .husk

# 4. Check site status
husks status design.json --site .husk

# 5. Rerun (will use cache)
husks run design.json --stub --site .husk
# Output: ◆ oracle-rule oracle cached ⚡
```

### JSON Workflow

```bash
# Check and parse JSON
husks check design.json --json | jq '.nodes[] | {name, state}'

# Run and capture result
husks run design.json --stub --site .husk --json > report.json

# Verify all nodes sealed
jq '.nodes[] | select(.state != "sealed" and .state != "cached")' report.json

# Get build root
jq -r '.root' report.json
```

### Cache Evidence

```bash
# First run
husks run design.json --stub --site .husk --json
# → {"nodes": [{"name": "rule", "state": "sealed", ...}]}

# Second run (cached)
husks run design.json --stub --site .husk --json
# → {"nodes": [{"name": "rule", "state": "cached", "cache": true, ...}]}
```

## Architecture

```
Commands (check, run, status)
    ↓
Collect facts into CliResidue
    ↓
Surface dispatcher (--json or --verbose)
    ↓
JSON output | Visual DAG renderer
```

### State Mapping

**From manifest (status, check --site)**:
- manifest "fresh" → CLI "sealed"
- manifest "stale" → CLI "stale"

**From trace (run)**:
- trace "fired" + not cached → CLI "sealed"
- trace "fired" + cached → CLI "cached"
- trace "reused" → CLI "cached"
- trace "failed" → CLI "failed"

## Migration Notes

### For Existing Scripts

The new CLI is backward compatible:
- All commands accept the same flags
- JSON structure is a superset of old output (new fields added, old fields preserved where applicable)
- Exit codes unchanged

### Deprecated Patterns

Old pattern:
```bash
husks check design.json | grep "ok"
```

New pattern (more robust):
```bash
husks check design.json --json | jq -e '.status == "dry"'
```

## Testing

Contract tests validate:
- JSON purity (no ANSI codes)
- Shared vocabulary across commands
- State consistency
- Cache evidence

See `tests/test_cli_contract.py` and `tests/test_public_beta_cli.py`.
