# Husks CLI Reference

## Overview

Husks is a deterministic build system for nondeterministic (LLM-powered) work. This release demonstrates **computational state equivalence** through a three-machine proof: independent realizations of the same design produce verifiably equivalent build artifacts under the design's declared acceptance relation.

## Quick Start

```bash
# Check design validity
husks check <your-design.json>

# Run the build with stub oracle (zero API cost)
husks run <your-design.json> --site m1 --stub

# Verify the .husk artifact
husks verify m1

# Inspect the build residue
husks status m1
```

## The Three-Machine Proof

The core reproduction path. Proves cache reuse (M2) and independent
re-realization (M3) from the same seed design.

### Stub proof path (automated, zero cost)

Uses a minimal oracle+action design (like the one in `tests/test_three_machine_stub.py`).
Proves the cache/refire mechanics with deterministic identity — no API key required.

```bash
# Machine 1: Original realization
husks run stub-proof.json --site m1 --stub

# Export cache from M1
husks cache export m1 cache.tar.gz

# Machine 2: Import cache and reuse at zero cost
husks cache import cache.tar.gz m2
husks run stub-proof.json --site m2 --reuse-only

# Machine 3: Independent re-realization
husks run stub-proof.json --site m3 --stub

# Verify computational equivalence
husks compare m1 m2 m3
```

**Expected result (stub path, deterministic identity):**
```
── Three-Machine Proof ──
  ✓ M1↔M2↔M3 husk identical          (required)
  ✓ M1↔M2 root identical              (required)
  ✓ M1 fired oracles                   (required)
  · M1 paid cost                       (evidence)
  · M2 zero oracle cost                (evidence)
  ✓ M2 cache reuse                     (required)
  ✓ M3 fired oracles                   (required)
  · M3 paid cost                       (evidence)
  · M1↔M3 outputs equivalent           (evidence)

proof satisfied
```

### Live proof path (requires API key)

Uses `core-bootstrap.locke` with a real oracle. Proves behavioral equivalence
through the conformance gate. **Note:** `core-bootstrap.locke --stub` does not
pass the conformance gate because the stub oracle writes placeholder content
that the gate rejects. Use a live oracle for core-bootstrap.

```bash
# Machine 1: Original realization with live oracle
husks run core-bootstrap.locke --site m1 --model anthropic/claude-haiku-4-5

# Export cache from M1
husks cache export m1 cache.tar.gz

# Machine 2: Import cache and reuse at zero cost
husks cache import cache.tar.gz m2
husks run core-bootstrap.locke --site m2 --reuse-only

# Machine 3: Independent re-realization with live oracle
husks run core-bootstrap.locke --site m3 --model anthropic/claude-haiku-4-5

# Verify computational equivalence
husks compare m1 m2 m3
```

**Expected result (live path, validator-bounded acceptance):**

With live oracles, M1 and M3 produce different generated source code
(non-deterministic), resulting in different roots. Equivalence is proved via
validator-bounded acceptance: both readers pass the conformance gate and produce
identical `VERIFIED` digests, proving behavioral equivalence without requiring
identical source. See Section 4 of the white paper.

## Core Commands

### `husks check <design>`

Validate design structure and dependencies.

**Behavior:**
- Silent on success (exit code 0)
- Reports errors to stderr on failure (exit code 1)

**Options:**
- `--json` - JSON output with validation details
- `--verbose` - Show full validation report

**Example:**
```bash
# Silent validation
husks check core-bootstrap.locke

# JSON output
husks check core-bootstrap.locke --json
```

### `husks run <design>`

Execute a build design, running oracles and actions.

**Required:**
- `--site <dir>` - Site directory for inputs and outputs

**Options:**
- `--stub` - Use stub oracle (zero API cost, deterministic)
- `--model <name>` - LLM model (default: anthropic/claude-haiku-4-5)
- `--reuse-only` - Fail if cache miss (requires prior cache import)
- `--json` - JSON report output
- `--verbose` - Detailed execution trace
- `--soft-fail` - Exit 0 even on build failure
- `--backend <name>` - Oracle backend: `litellm` (default) or `claude-code`

**Examples:**
```bash
# Run with stub oracle
husks run core-bootstrap.locke --site m1 --stub

# Run with live oracle
husks run core-bootstrap.locke --site m1 --model anthropic/claude-haiku-4-5

# Cache-only run (M2 scenario)
husks run core-bootstrap.locke --site m2 --reuse-only

# JSON output
husks run core-bootstrap.locke --site m1 --stub --json
```

### `husks verify <site>`

Recompute the `.husk` root hash from sealed artifacts.

**Purpose:** Proves the `.husk` file is self-verifying. Any future reader
with SHA-256 and the site files can reproduce the root hash. The engine
that built it can be discarded.

**Options:**
- `--json` - JSON output

**Example:**
```bash
husks verify m1
```

### `husks status <site>`

Inspect a built site's state and freshness.

**Arguments:**
- `<site>` - Site directory with manifest and build state

**Options:**
- `--json` - JSON output
- `--verbose` - Show per-node detail

**Example:**
```bash
husks status m1
husks status m1 --json
```

### `husks history <site> [rule]`

Show convergence history across runs for a site.

**Arguments:**
- `<site>` - Site directory
- `[rule]` - Optional rule name to filter

**Options:**
- `-n <count>` - Number of runs to show (default: 5)
- `--json` - JSON output

**Example:**
```bash
husks history m1
husks history m1 generate
```

### `husks compare <sites...>`

Compare equivalence across two or more sites. With three sites, runs
the full three-machine proof.

**Arguments:**
- `<sites...>` - Two or more site directories

**Options:**
- `--json` - Machine-readable JSON output
- `--roots-only` - Compare only root hashes
- `--hashes-only` - Compare only husk hashes

**Example:**
```bash
husks compare m1 m2 m3
```

**Three-machine proof checks (3 sites):**

Required:
- M1↔M2↔M3: husk hash identical
- M1↔M2: root hash identical (cache determinism)

Evidence (informational):
- M1: fired oracles, paid cost
- M2: zero oracle cost, cache reuse
- M3: fired oracles, paid cost
- M1↔M3: outputs equivalent

JSON output includes `proof.satisfied` and `proof.checks` with a
`required` flag on each check.

### `husks cache export <site> <file>`

Export build cache to a portable tarball.

**Arguments:**
- `<site>` - Site directory with cache to export
- `<file>` - Output tarball path (must end with `.tar.gz`)

**Options:**
- `--json` - JSON status output

**Example:**
```bash
husks cache export m1 cache.tar.gz
```

### `husks cache import <file> <site>`

Import cache from a tarball into a site.

**Arguments:**
- `<file>` - Tarball to import
- `<site>` - Target site directory

**Options:**
- `--json` - JSON status output

**Example:**
```bash
husks cache import cache.tar.gz m2
```

### `husks config show`

Show the resolved oracle configuration from `.husks.toml`.

**Options:**
- `--rule <name>` - Show config for a specific rule (applies per-rule overrides and deep merge)
- `--json` - JSON output (default format is already JSON)

API keys are masked as `****` in the output.

**Examples:**
```bash
# Show base oracle config
husks config show

# Show resolved config for a specific rule
husks config show --rule expensive_rule
```

### `husks config template`

Print an annotated `.husks.toml` template to stdout.

**Example:**
```bash
# Generate a config file
husks config template > .husks.toml
```

The template includes all known keys, defaults, comments explaining each
option, and examples of `[oracle.params]` and `[oracle.rules.*]`.

### `husks doctor`

Diagnose the local environment. Silent on success (exit code 0); only prints
failing checks to stderr.

**Options:**
- `--json` - Full JSON report (always printed, including passing checks)
- `--arch` - Verify module import DAG against `layers.toml`

**Example:**
```bash
husks doctor
husks doctor --json
```

## Visual Output Format

Husks renders a diamond card with a motif tree:

```
     ◆    design: core-bootstrap
    ╱ ╲   state:  sealed
   ◆ ◆ ◆  husk:   0bb90a01b978767c...
    ╲ ╱   root:   182e3015da5cc7d4...
     ◆    site:   M1

  status
  ───────────────────────────────────────────────────────────────────────────────
  ■ validate          action                                                 0.1s
  └─ ■ generate       oracle            15.3kin · 3.1kout · $0.0306 · 25.1s · ⚡3
  ───────────────────────────────────────────────────────────────────────────────
  sealed                                15.3kin · 3.1kout · $0.0306 · 25.2s · ⚡4
```

### Diamond Card

The card header shows:
- `design:` - Design name
- `state:` - Build state (sealed/checked/failed)
- `husk:` - CSE husk hash
- `root:` - Build root hash (green if sealed, red if failed)
- `site:` - Site directory name

### Motif Tree

Each node shows:
- **Glyph:** State indicator
  - `□` unrealized (exists but not executed)
  - `■` sealed (executed, fresh)
  - `◆` cached (reused from cache)
  - `△` stale (inputs changed, needs rebuild)
  - `✕` failed (execution error)

- **Name:** Rule name
- **Kind:** oracle/action/trial
- Right-aligned metadata: tokens, cost, duration, fuel consumed

### Summary Line

Bottom line aggregates totals: tokens, cost, duration, and total fuel steps.

## JSON Report Schema (beta-1)

The JSON report follows the beta-1 schema:

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
    "start": 5,
    "end": 4
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

The default template demonstrates CSE bootstrapping:

**Goal:** Generate a CSE reader from specs, then validate it against
frozen conformance vectors.

**Rules:**

1. **generate** (oracle)
   - Inputs: `CSE-v1.md`, `CSE-v2.md`
   - Output: `readers/generated_reader.py` (free)
   - Tools: read-file, write-file
   - Fuel: 4

2. **validate** (action, target)
   - Input: `readers/generated_reader.py`
   - Outputs: `readers/gate-report.txt` (free), `readers/VERIFIED` (exact)
   - Command: `python3 gate.py` (runs the reader against frozen vectors)
   - Actions don't consume fuel

**Design principles:**
- Minimal: 2 rules, 1 oracle, 1 action
- Self-verifying: the gate checks conformance, not just compilation
- Deterministic gate: `readers/VERIFIED` carries a conformance digest
- Portable: works on any machine with Python 3

## Stub Oracle Mode

The `--stub` flag uses the default oracle backend, a deterministic
stub that writes placeholder content to each declared output:

```python
def default_oracle_backend(S, rule_name, recipe, outputs):
    content = f"# oracle output: {rule_name}\n# prompt: {prompt}\n"
    for o in outputs:
        write_text(site_path(S, o, write=True), content)
    return {"tokens_in": 0, "tokens_out": 0, "cost_usd": 0.0,
            "fuel_steps": 1, "backend": "stub", "model": "stub"}
```

**Behavior:**
- Zero API cost, zero tokens
- Deterministic outputs (reproducible builds)
- No API keys needed

This enables:
- **M1/M3 equivalence:** Both use stub, get identical outputs
- **Zero-cost testing:** Full three-machine proof without any API access
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
husks cache export m1 cache.tar.gz
```
Creates tarball with:
- `.cache/` directory structure
- All cached outputs and metadata
- Preserves seal hashes for lookup
- Deterministic archive (pinned mtime, uid/gid, sort order)

**Import:**
```bash
husks cache import cache.tar.gz m2
```
Merges imported cache into target site:
- Existing entries: Kept (merge mode)
- New entries: Added to cache

**Security note:** Only import caches from trusted sources. Imported cache entries are used verbatim without re-validation.

## State Vocabulary

Husks uses a unified state model across all commands:

| State | Glyph | Meaning |
|-------|-------|---------|
| `unrealized` | □ | Node exists in design, not executed |
| `sealed` | ■ | Executed and fresh (inputs unchanged) |
| `cached` | ◆ | Reused from cache with explicit evidence |
| `stale` | △ | Recipe/inputs changed or outputs missing |
| `failed` | ✕ | Execution failed with diagnosis |

**Kind vocabulary:**
- `oracle` - LLM-powered generative rule
- `action` - Deterministic shell command
- `trial` - Speculative fork with verdict function

## Exit Codes

| Code | Meaning |
|------|---------|
| 0 | Success (check passed, build committed, comparison valid) |
| 1 | Build failure (halted, failed rules, validation errors) |
| 2 | Usage error (invalid arguments, missing files) |
| 3 | Missing dependency (litellm not installed) |
| 4 | Dirty or stale site (with `--fail-if-dirty` / `--fail-if-stale`) |
| 5 | Internal error |

## Configuration

Husks reads oracle configuration from `.husks.toml`, searching upward from
the working directory. Any string value starting with `$` is expanded from
`os.environ` (empty string if the variable is not set). This works for all
keys — `api_key`, `api_base`, values inside `[oracle.params]`, and per-rule
overrides in `[oracle.rules.*]`.

Generate an annotated template with `husks config template > .husks.toml`.
Inspect the resolved config with `husks config show`.

Unknown keys and type mismatches produce warnings on stderr (never errors),
so forward-compatible additions won't break existing configs.

Per-rule overrides use deep merge: a rule's `params` dict merges with the
base `params` instead of replacing it. A rule can also override the
`backend` to route specific rules to a different oracle backend.

## Environment Variables

- `ANTHROPIC_API_KEY` - Required for live oracle calls (not stub). Reference as `$ANTHROPIC_API_KEY` in `.husks.toml`.
- `HUSKS_CONFORMANCE_DIR` - Override the conformance vectors directory (defaults to the bundled vectors in the wheel, or `spec/conformance/` in an editable install).
- `PYTHONPATH` - May be needed if running from source

## FAQ

### Why does M2 run the validate action?

Actions are not cached. Only oracle outputs are cached. The validate action
runs on M2, but the generate oracle is cached, so M2 pays zero oracle cost.

### Why do M1 and M3 have the same root in stub mode but different roots in live mode?

The stub oracle is **deterministic**: same inputs → same outputs. M1 and M3
both use stub mode with identical inputs, so they produce byte-identical
outputs, resulting in the same build root hash. This proves **deterministic
identity**.

With live oracles, M1 and M3 produce different generated source code
(non-deterministic), resulting in different roots. This is expected and
correct. Section 4 of the white paper states the seed/cache split prevents
"independent re-realization from being mistaken for deterministic identity."
Equivalence on the live path is proved via **validator-bounded acceptance**:
both readers pass the conformance gate and produce identical `VERIFIED`
digests, proving behavioral equivalence without requiring identical source.

### Can I run without an API key?

Yes. Use `--stub` mode with the stub-proof example (which has no conformance gate):
```bash
husks run examples/stub-proof/stub-proof.json --site m1 --stub
```

This uses a deterministic stub oracle with zero API cost.

**Note:** `core-bootstrap.locke --stub` will fail the conformance gate because the
stub oracle writes placeholder content. Use a live oracle for core-bootstrap, or
use `examples/stub-proof/stub-proof.json` for zero-cost testing.

### What's the difference between --stub and live oracles?

| Aspect | --stub | Live Oracle |
|--------|--------|-------------|
| API Cost | $0 | Real cost (e.g., $0.0008) |
| Determinism | Always identical | Non-deterministic |
| API Key | Not required | Required |
| Use Case | Testing, proofs | Production builds |
| Outputs | Reference implementation | LLM-generated |

### Can I use my own design instead of core-bootstrap?

Yes. Create a `.locke` or `.json` design:

```json
{
  "name": "my-design",
  "fuel": 50,
  "target": "validate",
  "site_inputs": {
    "input.txt": "path/to/input.txt"
  },
  "rules": [
    {
      "name": "generate",
      "kind": "oracle",
      "inputs": ["input.txt"],
      "outputs": ["output.txt"],
      "prompt": "Your prompt here",
      "tools": ["read-file", "write-file"],
      "fuel": 20
    },
    {
      "name": "validate",
      "kind": "action",
      "inputs": ["output.txt"],
      "outputs": ["result.txt"],
      "run": "python3 check.py output.txt"
    }
  ]
}
```

The target must be an action (use `--unsafe` to override).

See `examples/` for more designs.

## References

- **CSE Specification:** `spec/CSE-v1.md`, `spec/CSE-v2.md`
- **Conformance Vectors:** `spec/conformance/` (bundled into the wheel at `husks/_resources/conformance/`)
- **Permanence Layer:** `src/husks/kernel.py`
- **Build Engine:** `src/husks/engine.py`
- **CLI Source:** `src/husks/cli.py`
- **Report/Manifest:** `src/husks/report.py`
- **Locke Parser:** `src/husks/locke.py`
- **Conformance Gate:** `examples/core-bootstrap/gate.py`
