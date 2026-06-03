# Husks CLI Beta 100

**Status:** Beta 100 sealed
**Date:** 2026-05-31

## Overview

Beta 100 marks the first public-ready release of Husks, a deterministic build system for nondeterministic (LLM-powered) work. This release demonstrates **computational state equivalence** through a three-machine proof: independent realizations of the same design produce verifiably equivalent build artifacts under the design's declared acceptance relation.

## Quick Start

```bash
# Initialize a new Husks project
husks init

# Check design validity
husks check core-bootstrap.locke

# Run the build with stub oracle (zero API cost)
husks run core-bootstrap.locke --site m1 --stub

# Verify outputs
ls m1/readers/

# Explore the build residue interactively
husks explain --site m1 --interactive
```

## The Three-Machine Proof

Beta 100 enables cross-machine verification of computational equivalence:

```bash
# Machine 1: Original realization with oracle cost
husks run core-bootstrap.locke --site m1 --stub --json > m1.json

# Export cache from M1
husks cache export cache.tar.gz --site m1

# Machine 2: Import cache and reuse at zero cost
mkdir m2
husks cache import cache.tar.gz --site m2
husks run core-bootstrap.locke --site m2 --reuse-only --json > m2.json

# Machine 3: Independent re-realization
husks run core-bootstrap.locke --site m3 --stub --json > m3.json

# Verify computational equivalence
husks compare-runs m1.json m2.json m3.json

# Inspect individual machines (optional)
husks explain --site m1 --node generate --aperture 3  # M1: paid oracle cost
husks explain --site m2 --node generate --aperture 3  # M2: cached reuse
husks explain --site m3 --node generate --aperture 3  # M3: independent realization
```

**Expected result (stub path — deterministic identity):**
```
✓ Three-machine proof validated

M1: oracle_calls=1, cost=$0.000800 (paid oracle cost)
M2: oracle_calls=0, cost=$0.000000, cache_hits=1 (zero-cost reuse)
M3: oracle_calls=1, cost=$0.000800 (independent re-realization)

All three: same root (deterministic identity via stub oracle)
```

**Expected result (live path — validator-bounded acceptance):**
```
✓ Three-machine proof validated

M1: oracle_calls=1, cost=$0.0330, root=7e32a9...
M2: oracle_calls=0, cost=$0.0000, cache_hits=1, root=7e32a9... (same as M1)
M3: oracle_calls=1, cost=$0.0307, root=4d175e... (differs from M1)

M1/M2: root identical (cache determinism)
M3: VERIFIED digest matches M1 (behavioral acceptance)
     generated_reader.py differs (free output, expected)
     cost ratio 0.93 within tolerance [0.5, 2.0]

equivalent: true
```

## Core Commands

### `husks init`

Initialize a new Husks project with the core-bootstrap template.

**Creates:**
- `core-bootstrap.locke` - Build design (Locke source)
- `spec/` - CSE specification documents
- `.gitignore` - Git ignore rules
- `CLAUDE.md` - Project stance documentation

**Example:**
```bash
husks init
cd .
husks check core-bootstrap.locke
```

### `husks check <design>`

Validate design structure and dependencies.

**Behavior:**
- Silent on success (exit code 0)
- Reports errors to stderr on failure (exit code 1)

**Options:**
- `--json` - JSON output with validation details
- `--verbose` - Show full validation report
- `--site <dir>` - Overlay freshness states from site manifest

**Example:**
```bash
# Silent validation
husks check core-bootstrap.locke

# JSON output
husks check core-bootstrap.locke --json

# Check with site overlay
husks check core-bootstrap.locke --site m1
```

### `husks run <design>`

Execute a build design, running oracles and actions.

**Required:**
- `--site <dir>` - Site directory for inputs and outputs

**Options:**
- `--stub` - Use stub oracle (zero API cost, deterministic)
- `--model <name>` - LLM model (default: anthropic/claude-haiku-4-5)
- `--reuse-only` - Fail if cache miss (requires prior cache import)
- `--json` - JSON report output (compare-runs compatible)
- `--verbose` - Detailed execution trace
- `--soft-fail` - Exit 0 even on build failure

**Examples:**
```bash
# Run with stub oracle
husks run core-bootstrap.locke --site m1 --stub

# Run with live oracle
husks run core-bootstrap.locke --site m1 --model anthropic/claude-haiku-4-5

# Cache-only run (M2 scenario)
husks run core-bootstrap.locke --site m2 --reuse-only

# JSON output for comparison
husks run core-bootstrap.locke --site m1 --stub --json > m1.json
```

### `husks cache export <file>`

Export build cache to a portable tarball.

**Required:**
- `--site <dir>` - Site with cache to export

**Options:**
- `--json` - JSON status output

**Example:**
```bash
husks cache export cache.tar.gz --site m1 --json
```

**Output:**
```json
{
  "status": "exported",
  "site": "m1",
  "file": "cache.tar.gz",
  "entries": 1
}
```

### `husks cache import <file>`

Import cache from a tarball into a site.

**Required:**
- `--site <dir>` - Target site for import

**Options:**
- `--json` - JSON status output
- `--replace` - Replace existing cache (default: merge)

**Example:**
```bash
husks cache import cache.tar.gz --site m2 --json
```

**Output:**
```json
{
  "status": "imported",
  "site": "m2",
  "file": "cache.tar.gz",
  "entries": 1,
  "merge": true
}
```

### `husks compare-runs <reports...>`

Validate three-machine proof by comparing JSON reports.

**Arguments:**
- `<reports...>` - Two or more JSON report files

**Options:**
- `--json` - Machine-readable JSON output

**Example:**
```bash
husks compare-runs m1.json m2.json m3.json
```

**Checks:**
- M1: `oracle_calls > 0`, `cost > 0`
- M2: `oracle_calls = 0`, `cost = 0`, `cache_hits > 0`
- M3: `oracle_calls > 0`, comparable cost to M1 (within declared `cost_tolerance`)
- M1/M2: Same `root` (cache determinism)
- M3: Validator-bounded acceptance — `exact` outputs (conformance digest) match M1; `free` outputs (generated source, gate report) may differ
- Cost: M3/M1 ratio within seed-declared tolerance (default `[0.5, 2.0]`)

### `husks explain --site <dir>`

Explore and navigate a built site's residue tree.

**Purpose:** Inspect sealed builds without requiring a design file. Navigate through the dependency tree with adjustable detail levels.

**Required:**
- `--site <dir>` - Site directory with manifest and build state

**Options:**
- `--node <name>` - Select specific node (default: target)
- `--aperture <0-3>` - Detail level (default: 1)
  - `0` - Node only (name, kind, state)
  - `1` - Node + outputs (primary output with hash)
  - `2` - Node + outputs + seal (recipe, input/output hashes)
  - `3` - Node + outputs + seal + trace (backend, model, tokens, cost, logs)
- `--interactive` - Enable interactive navigation (requires TTY)
- `--json` - JSON output with cursor/aperture metadata

**Examples:**

```bash
# Inspect site residue at target node
husks explain --site m1

# Select specific node with full trace
husks explain --site m1 --node generate --aperture 3

# Interactive navigation
husks explain --site m1 --interactive

# JSON output for programmatic access
husks explain --site m1 --node generate --aperture 2 --json
```

**Interactive Controls:**

When `--interactive` is specified in a TTY environment, explain enters interactive pilot mode:

- `↑/↓` - Move cursor up/down through nodes
- `←/→` - Decrease/increase aperture (0-3)
- `q` - Quit

**Non-TTY fallback:** When run in non-TTY environments (pipes, CI), explain renders once deterministically, even if `--interactive` is specified.

**Example Output (aperture 1):**

```
────────────────────────────────────────
 core-bootstrap.husk              root:36a407c
 site:m1                   cursor:validate
 aperture:1
────────────────────────────────────────
▶■ validate                  action
      out:readers/gate-report.txt@7f6aec
      out:readers/VERIFIED@e3b0c4
    └─ ■ generate            oracle
      out:readers/generated_reader.py@09e95b
────────────────────────────────────────
 ↑↓ move   ←→ aperture   q quit
```

**Example Output (aperture 3):**

```
────────────────────────────────────────
 core-bootstrap.husk              root:36a407c
 site:m1                   cursor:generate
 aperture:3
────────────────────────────────────────
 □ validate                  action
    └─ ▶■ generate           oracle     ⚡10     $0.0008
      out:readers/generated_reader.py@09e95b
      seal:
        digest: 36a407
        recipe: f5e2a1
        inputs: 2
        outputs: 1
      trace:
        backend: stub
        model: stub
        input_tokens: 840
        output_tokens: 320
        elapsed: 0.01s
        cost: $0.0008
────────────────────────────────────────
 ↑↓ move   ←→ aperture   q quit
```

**Cached nodes (M2 scenario):**

When exploring a site with cache reuse, cached nodes show the `◆` glyph and cache provenance:

```bash
husks explain --site m2 --node generate --aperture 3
```

```
────────────────────────────────────────
 core-bootstrap.husk              root:36a407c
 site:m2                   cursor:generate
 aperture:3
────────────────────────────────────────
 □ validate                  action
    └─ ▶◆ generate           oracle     cached     ⚡0     $0.0000
      out:readers/generated_reader.py@09e95b
      seal:
        digest: 36a407
        recipe: f5e2a1
        inputs: 2
        outputs: 1
      cache: local
────────────────────────────────────────
 ↑↓ move   ←→ aperture   q quit
```

**JSON Output:**

With `--json`, explain outputs structured data including cursor and aperture state:

```json
{
  "command": "status",
  "design_name": "core-bootstrap",
  "status": "sealed",
  "site": "m1",
  "cse_path": "core-bootstrap.husk",
  "root": "36a407c...",
  "cursor": "generate",
  "aperture": 2,
  "order": ["validate", "generate"],
  "nodes": [
    {
      "name": "generate",
      "kind": "oracle",
      "state": "sealed",
      "outputs": [
        {
          "path": "readers/generated_reader.py",
          "sha256": "09e95b..."
        }
      ],
      "seal_digest": "36a407...",
      "recipe_digest": "f5e2a1...",
      "fuel": 10,
      "cost": 0.0008
    }
  ]
}
```

**Use Cases:**

1. **Post-build inspection:** Explore what was built without needing the design file
2. **Cache verification:** Inspect cached nodes to verify reuse
3. **Seal debugging:** Examine recipe and input hashes to understand staleness
4. **Provenance audit:** Review oracle traces (backend, model, tokens, cost)
5. **Interactive debugging:** Navigate dependency tree to find failed or stale nodes

**Comparison with other commands:**

| Command | Purpose | Requires design file? |
|---------|---------|----------------------|
| `check` | Validate design structure | Yes |
| `run` | Execute build | Yes |
| `status` | Show freshness states | No (--site mode) |
| `explain` | Navigate residue tree | No (--site mode) |

## Visual Output Format (Beta 100)

Husks beta 100 introduces a bounded CSE block rendering:

```
────────────────────────────────────────────────────────────
 core-bootstrap      sealed             ⚡2/20
 cse:core-bootstrap.husk
 site:m1
────────────────────────────────────────────────────────────
 ■ validate                  action          0.05s
      out:readers/gate-report.txt@7f6aec
      out:readers/VERIFIED@e3b0c4
    └─ ■ generate            oracle          0.01s     $0.0008     ⚡10
      out:readers/generated_reader.py@09e95b
────────────────────────────────────────────────────────────
 passes: run
```

### Header (3 lines)

**Line 1:** Name, status, fuel
- Design name (left-aligned)
- Status (sealed/failed/stale)
- Fuel budget (right-aligned): ⚡consumed/total

**Line 2:** CSE artifact and root
- `cse:<filename>` - CSE husk path
- `root:<hash>` - Build root (if committed)

**Line 3:** Site
- `site:<name>` - Site directory name

### Node Records

Each node shows:
- **Glyph:** State indicator
  - `□` unrealized (exists but not executed)
  - `■` sealed (executed, fresh)
  - `◆` cached (reused from cache)
  - `△` stale (inputs changed, needs rebuild)
  - `✕` failed (execution error)
  - `◉` running (in progress, verbose mode only)

- **Name:** Rule name
- **Kind:** oracle/action/trial
- **Duration:** Execution time (if measured)
- **Fuel:** ⚡consumed (oracles only)
- **Cost:** USD cost (oracles only)
- **Fuel budget:** ⚡N (oracle budget, right-aligned)

### Output Records

Each output shows:
```
      out:<path>@<hash-prefix>
```
- `<path>` - Relative output path
- `<hash-prefix>` - First 6 chars of SHA-256 hash
- `??????` if output missing/failed

### Summary

Bottom line shows pass/fail categories:
```
 passes: run, cache
 failures in run
```

## JSON Report Schema (beta-1)

The JSON report follows the beta-1 schema for compare-runs compatibility:

```json
{
  "schema_version": "beta-1",
  "status": "committed",
  "root": "<64-char-hex>",
  "run_id": "<uuid>",
  "build": "core-bootstrap",
  "site": "m1",
  "elapsed_s": 0.063,
  "fuel": {
    "start": 20,
    "end": 18
  },
  "cost": {
    "paid": 0.0008,
    "reused_estimate": 0.0,
    "projected_estimate": 0.0
  },
  "delta": {
    "changed": [],
    "new": ["generate", "validate"],
    "unchanged": []
  },
  "nodes": [
    {
      "name": "generate",
      "kind": "oracle",
      "state": "fired",
      "classification": "converging",
      "prompt_len": 1235,
      "fuel_consumed": 1,
      "output_hashes": ["09e95b..."],
      "cached": false,
      "tokens": {
        "input": 840,
        "output": 320
      },
      "cost": {
        "this_run": 0.0008,
        "first_paid": 0.0008,
        "per_rerun": 0.0008
      },
      "seal": {
        "hash": "36a407...",
        "recipe_changed": false
      }
    }
  ],
  "oracle_calls": 1,
  "cache_hits": 0,
  "cached_nodes": []
}
```

### Key Fields for Three-Machine Proof

**Authoritative evidence:**
- `oracle_calls` - Number of oracle executions
- `cache_hits` - Number of cache reuses
- `cached_nodes` - Names of nodes reused from cache
- `cost.paid` - Actual USD cost paid this run
- `cost_tolerance` - Declared cost comparability bounds (from seed design)
- `root` - Build root hash (M1/M2 must match; M3 may differ on live path)
- `nodes[].outputs` - Named output hashes (path + hash for per-output comparison)
- `nodes[].equivalence` - Per-output equivalence relation (`exact` or `free`)

**Node-level evidence:**
- `nodes[].cached` - Explicit cache reuse flag
- `nodes[].cost.this_run` - Cost incurred this run
- `nodes[].state` - Execution state (fired/sealed/failed)

## Core-Bootstrap Design

The default `husks init` template demonstrates CSE bootstrapping:

**Goal:** Generate a CSE reader from specs, then validate it compiles.

**Rules:**

1. **generate** (oracle)
   - Inputs: `CSE-v1.md`, `CSE-v2.md`
   - Output: `readers/generated_reader.py`
   - Prompt: Read CSE specs, implement byte-level CSE reader
   - Tools: read-file, write-file
   - Fuel: 10

2. **validate** (action)
   - Input: `readers/generated_reader.py`
   - Outputs: `readers/gate-report.txt`, `readers/VERIFIED`
   - Command: Compile reader, write validation proof
   - Fuel: N/A (actions don't consume fuel)

**Design principles:**
- Minimal: 2 rules, 1 oracle, 1 action
- Self-verifying: Generated code must compile
- Deterministic: Stub oracle produces reference implementation
- Portable: Works on any machine with Python 3

## Stub Oracle Mode

The `--stub` flag uses a deterministic oracle backend for testing:

**Behavior:**
- Zero API cost
- Deterministic outputs (reproducible builds)
- Reports synthetic token/cost metrics
- Special handling for core-bootstrap's `generate` rule

**Core-bootstrap stub:**
```python
if rule_name == "generate":
    # Copy reference reader from package resources
    ref_reader = pkg_root / "_resources" / "bootstrap_reader.py"
    write_text(output_path, ref_reader.read_text())
    return {
        "tokens_in": 840,
        "tokens_out": 320,
        "cost_usd": 0.0008,
        "fuel_steps": 10,
        "backend": "stub",
        "model": "stub"
    }
```

This enables:
- **M1/M3 equivalence:** Both use stub, get identical outputs
- **Zero-cost testing:** No API keys needed
- **Reproducible proofs:** Same inputs → same outputs

## Cache Mechanics

### Cache Structure

Husks stores oracle outputs in a content-addressed cache:

```
site/
  .cache/
    <seal-hash>/          # Unique per recipe+inputs
      outputs/
        <output-path>     # Cached output files
      metadata.json       # Provenance: tokens, cost, backend
  <output-path>           # Materialized outputs
  manifest.json           # Build state tracking
  <design-name>.husk      # CSE proof artifact
```

### Cache Lookup

Cache key = `seal(recipe, input_hashes)`

**Lookup process:**
1. Compute recipe digest: `sha256(prompt + tools + fuel)`
2. Hash inputs: For each input, read file and compute SHA-256
3. Compute seal: `sha256(recipe_digest + sorted(input_hashes))`
4. Check `.cache/<seal>/` exists
5. If hit: Copy cached outputs, skip oracle execution
6. If miss: Execute oracle, populate cache

### Cache Import/Export

**Export:**
```bash
husks cache export cache.tar.gz --site m1
```
Creates tarball with:
- `.cache/` directory structure
- All cached outputs and metadata
- Preserves seal hashes for lookup

**Import:**
```bash
husks cache import cache.tar.gz --site m2
```
Merges imported cache into target site:
- Existing entries: Kept (merge mode) or replaced (--replace)
- New entries: Added to cache
- No validation: Trust imported content

**Security note:** Only import caches from trusted sources. Imported cache entries are used verbatim without re-validation.

## State Vocabulary

Husks uses a unified state model across all commands (check, run, status):

| State | Glyph | Meaning |
|-------|-------|---------|
| `unrealized` | □ | Node exists in design, not executed |
| `sealed` | ■ | Executed and fresh (inputs unchanged) |
| `cached` | ◆ | Reused from cache with explicit evidence |
| `stale` | △ | Recipe/inputs changed or outputs missing |
| `failed` | ✕ | Execution failed with diagnosis |
| `running` | ◉ | Currently executing (verbose frames only) |

**Kind vocabulary:**
- `oracle` - LLM-powered generative rule
- `action` - Deterministic shell command
- `trial` - Non-committing exploration (not in beta 100)

## Exit Codes

| Code | Meaning |
|------|---------|
| 0 | Success (check passed, build committed, comparison valid) |
| 1 | Build failure (halted, failed rules, validation errors) |
| 2 | Usage error (invalid arguments, missing files) |
| 3 | Missing dependency (litellm not installed) |

## Environment Variables

- `ANTHROPIC_API_KEY` - Required for live oracle calls (not stub)
- `PYTHONPATH` - May be needed if running from source

## FAQ

### Why does M2 run the validate action?

Actions are **not cached** in beta 100. Only oracle outputs are cached. The validate action runs on M2, but the generate oracle is cached, so M2 pays zero oracle cost.

### Why do M1 and M3 have the same root in stub mode but different roots in live mode?

The stub oracle is **deterministic**: same inputs → same outputs. M1 and M3 both use stub mode with identical inputs, so they produce byte-identical outputs, resulting in the same build root hash. This proves **deterministic identity**.

With live oracles, M1 and M3 produce different generated source code (non-deterministic), resulting in different roots. This is expected and correct — Section 4 of the white paper states the seed/cache split prevents "independent re-realization from being mistaken for deterministic identity." Equivalence on the live path is proved via **validator-bounded acceptance**: both readers pass the conformance gate and produce identical `VERIFIED` digests, proving behavioral equivalence without requiring identical source.

### Can I run beta 100 without an API key?

Yes! Use `--stub` mode:
```bash
husks run core-bootstrap.locke --site m1 --stub
```

This uses a deterministic stub oracle with zero API cost.

### How do I verify computational equivalence with live oracles?

Live oracles are non-deterministic, so M1 and M3 will have different `root` hashes. Equivalence is proved via **validator-bounded acceptance**, not root identity:

1. The seed design declares per-output equivalence: `exact` (must match) or `free` (may differ)
2. The conformance gate (`husks.gate`) stamps `VERIFIED` with a behavioral digest — a SHA-256 of the reader's correct outputs on frozen vectors
3. `compare-runs` enforces: M1/M2 root identity (cache determinism), M3 `exact` outputs match M1 (acceptance), cost within declared tolerance
4. The `convergence` block reports M1/M3 root divergence observationally — it never fails the proof

### What's the difference between --stub and live oracles?

| Aspect | --stub | Live Oracle |
|--------|--------|-------------|
| API Cost | $0 | Real cost (e.g., $0.0008) |
| Determinism | Always identical | Non-deterministic |
| API Key | Not required | Required |
| Use Case | Testing, proofs | Production builds |
| Outputs | Reference implementation | LLM-generated |

### Can I use my own design instead of core-bootstrap?

Yes! Core-bootstrap is the default template for testing and proofs, but you can create custom designs:

```json
{
  "name": "my-design",
  "fuel": 50,
  "target": "my-target",
  "site_inputs": {
    "input.txt": "path/to/input.txt"
  },
  "rules": [
    {
      "name": "my-rule",
      "kind": "oracle",
      "inputs": ["input.txt"],
      "outputs": ["output.txt"],
      "prompt": "Your prompt here",
      "tools": ["read-file", "write-file"],
      "fuel": 20
    }
  ]
}
```

See `examples/json_designs/` for more examples.

### How do I inspect a built site without the design file?

Use `husks explain` with the `--site` flag:

```bash
husks explain --site m1
```

This loads the site manifest directly and renders the dependency tree with cursor at the target node. You can navigate interactively:

```bash
husks explain --site m1 --interactive
```

Or select a specific node with full trace details:

```bash
husks explain --site m1 --node generate --aperture 3
```

### What are aperture levels in explain?

Aperture controls the detail level for the selected node:

- **Aperture 0:** Node only (name, kind, state) - minimal view
- **Aperture 1:** Node + outputs (primary output with hash) - default view
- **Aperture 2:** Node + outputs + seal (recipe digest, input/output hashes)
- **Aperture 3:** Node + outputs + seal + trace (backend, model, tokens, cost, logs)

Use `←/→` arrow keys in interactive mode to adjust aperture on the fly.

### When should I use explain vs status?

Both commands can inspect built sites, but they serve different purposes:

| Use Case | Command |
|----------|---------|
| Check freshness states (stale detection) | `status` |
| Navigate dependency tree | `explain` |
| Inspect seal/trace details | `explain --aperture 2-3` |
| Verify cache reuse | `explain --node <name> --aperture 3` |
| CI/automated checks | `status --json` or `explain --json` |
| Interactive debugging | `explain --interactive` |

## Known Limitations (Beta 100)

1. **No live verbose frames:** Task 9 deferred - verbose mode doesn't show live progress updates
2. **Actions not cached:** Only oracle outputs are cached
3. **No incremental builds:** Changing one input invalidates entire dependency chain
4. **No parallel execution:** Rules run sequentially in dependency order
5. **Single-target builds:** Multi-target designs not supported in CLI

## Next Steps

- **Beta 101:** Live verbose frames with streaming updates
- **Beta 102:** Action output caching
- **Beta 103:** Incremental builds (partial invalidation)
- **Beta 104:** Parallel rule execution
- **Beta 105:** Multi-target CLI support

## References

- **CSE Specification:** `spec/CSE-v1.md`, `spec/CSE-v2.md`
- **Bootstrap Reader:** `src/husks/_resources/bootstrap_reader.py`
- **CLI Source:** `src/husks/cli/`
- **Report Schema:** `src/husks/report.py`
- **Cache Implementation:** `src/husks/build/cache.py`

## License

Husks is released under the MIT License. See LICENSE for details.

---

**Husks Beta 100** - Deterministic builds for nondeterministic work.
Generated: 2026-05-31
