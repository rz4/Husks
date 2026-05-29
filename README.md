<p align="center">
  <img src="assets/logo/husks-banner.png" alt="Husks" width="900">
</p>

# Husks

**Build Husks, not vibes.**

---

A model call is an opaque event. By the time you look at it, the event is over and what you hold is its residue. Husks treats that as the only thing worth verifying.

Traditional build systems like Make, Bazel, and Ninja assume **determinism**: given the same inputs, a build step always produces the same outputs. This assumption breaks down for LLM-powered workflows:

- **Same prompt → different outputs**: LLMs are nondeterministic by design
- **Expensive to re-run**: Oracle calls cost money and time ($0.0008–$0.50 per call)
- **Hard to share results**: No standard way to cache and verify LLM outputs across machines
- **Reproducibility crisis**: How do you prove two builds are equivalent when outputs differ?

**Husks solves this** by treating model calls as bounded nondeterministic events and verifying only what they leave behind: sealed residue on disk, hashed and inspectable from the outside.

The system makes claims only about residue, never about the event itself:
- A rule fired, and these are the exact bytes it produced
- An oracle ran with this prompt and allowlist, and spent this much fuel
- This artifact is sealed, and here is its hash
- The build committed or halted, and here is the reason

## What is Husks?

Husks is a **symbolic evaluator** over build expressions where nondeterminism has exactly one home: the `oracle` rule type. Everything else is deterministic structure you can reason about.

**Execution model:**

```
inputs → rules → outputs → seals → trace
```

The target names completion. Reach it and the build commits; fail to and it halts. There is no third outcome.

**Two forms of the same design:**

- **Transport** (what you author): JSON, ergonomic, allowed to evolve
- **Spine** (what survives): CSE (Canonical S-Expression), frozen, append-only

The transport lowers deterministically to the spine. The spine is the byte-level form that gets hashed — the only form that matters for verification or replay by a reader written long after this engine is gone.

## Grammar

Husks is a small evaluator over three rule types:

```
rule   : Store ⇀ Store                          partial transformation over an artifact store

action : X → Y                                   deterministic shell command
oracle : (prompt, tools, fuel, X) ⇝ Y            nondeterministic LLM call, bounded
trial  : (branch₁, …, branchₙ, verdict) → Y      speculative A/B test; one residue survives
```

**Execution consumes fuel and terminates by `commit` or `halt`.**

### Seal Definition

A seal is content, never instrumentation:

```
seal = SHA-256( CSE( (seal <version> <recipe-digest> <input-bindings>) ) )
```

**What is NOT sealed:**
- Model name, cost, token counts, wall-clock time, who answered

**Why:** A husk must verify identically whether its oracle ran on a model from 2026 or something unimaginable a decade later. The seal records what was asked and what came back, never who answered.

### Build Root

Nodes hash their seal, their outputs, and their children's digests, forming a **Merkle DAG**. The build root is one hash over the entire graph. Shared `let`-bound subtrees hash once — the diamond is one digest, not two that happen to match.

**Permanence claim:** The root is reproducible from bytes and inputs alone, by any conforming reader, with no access to the engine that produced it.

## How Husks Works

### 1. Define Your Build (Transport)

Create a `design.json` file:

```json
{
  "name": "example",
  "fuel": 10,
  "target": "result",
  "site_inputs": ["prompt.txt"],
  "rules": [
    {
      "name": "generate",
      "kind": "oracle",
      "inputs": ["prompt.txt"],
      "outputs": ["draft.md"],
      "prompt": "Read {prompt.txt} and write a technical document",
      "tools": ["write-file"],
      "fuel": 5
    },
    {
      "name": "validate",
      "kind": "action",
      "inputs": ["draft.md"],
      "outputs": ["result.txt"],
      "run": "python validate.py draft.md > result.txt"
    }
  ]
}
```

This JSON transport lowers deterministically to a canonical AST, then to **CSE** (the spine):

```
(4:husk1:1(5:build7:example2:10(4:rule8:generate...)))
```

CSE is netstring atoms `<length>:<bytes>` in fixed positional schemas, with no whitespace, no keywords, and no implementation-defined behavior. **CSE v1 is frozen forever.**

### 2. Run the Build

```bash
husks run design.json --site ./mysite
```

The runtime:
- Resolves dependencies (topological sort)
- Fires only stale rules
- Seals fresh outputs (freezes the **first** residue an oracle produces)
- Reuses sealed residue (no re-entry into expensive events)
- Reports cost, cache hits, convergence stats

**Build output:**

```json
{
  "status": "committed",
  "root": "9977239d...",
  "cost": {"paid": 0.0008, "reused": 0.0, "projected": 0.0008},
  "nodes": [
    {"name": "generate", "state": "fired", "cost": {"this_run": 0.0008}},
    {"name": "validate", "state": "fired", "cost": {"this_run": 0.0}}
  ]
}
```

### 3. Share the Cache (Cross-Machine Transfer)

**Machine 1** (original build):
```bash
husks cache export cache.tar.gz --site ./mysite
```

**Machine 2** (reuse sealed residue):
```bash
husks cache import cache.tar.gz --site ./othersite
husks run design.json --site ./othersite --reuse-only
# Zero oracle calls, zero cost ✓
```

**Cache validation on import:**
1. Verify `seal.json` recipe digest matches current rule
2. Verify output files exist and hash correctly
3. Reject if any check fails (prevents poisoning)

### 4. Validate Equivalence (Three-Machine Proof)

```bash
# M1: Original build
husks run design.json --site m1 --json > m1.json

# M2: Cache reuse
husks cache import cache.tar.gz --site m2
husks run design.json --site m2 --reuse-only --json > m2.json

# M3: Independent rebuild
husks run design.json --site m3 --json > m3.json

# Validate the proof
husks compare-runs m1.json m2.json m3.json --json
```

**Proof validation:**

```json
{
  "equivalent": true,
  "checks": {
    "m1_paid_cost": true,           // M1 paid oracle cost
    "m2_zero_oracle_calls": true,   // M2 made no oracle calls
    "m2_zero_cost": true,            // M2 cost = 0 (complete cache hit)
    "m3_paid_cost": true,            // M3 paid comparable cost to M1
    "same_root": true                // All three have same build root hash
  },
  "runs": [
    {"cost_paid": 0.0008, "oracle_calls": 1, "root": "9977239d..."},
    {"cost_paid": 0.0,    "oracle_calls": 0, "root": "9977239d..."},
    {"cost_paid": 0.0008, "oracle_calls": 1, "root": "9977239d..."}
  ]
}
```

## Convergence and Extraction

A design is not written once. It is **worked**: you run it, read the trace, perturb nodes that didn't satisfy, pin the ones that did, and run again.

This is **program extraction against nondeterminism** — separating the part of a task you've reduced to a deterministic rule from the part that has, so far, resisted reduction.

```bash
husks history design.json generate
```

**Convergence states:**

- **Converging**: Fuel falling or flat, prompt flat → honest progress
- **Prompt-loading**: Fuel falling, prompt *rising* → alarm! You're hand-migrating work into the prompt and paying the oracle to read it back
- **Stable**: Output hashes identical across runs → make it an `action`
- **Volatile**: No settled trend → not converged

**The fixed point:** Maximal deterministic skeleton, with remaining oracle nodes naming only what has resisted reduction so far.

## Who Uses Husks?

**Research Teams**: Reproducible LLM experiments with shared caching across lab members

**AI Product Teams**: Cache expensive LLM calls in CI/CD pipelines, reuse across deployments

**Scientific Workflows**: Track convergence and costs for prompt engineering, validate nondeterministic outputs

**Formal Methods**: Treat oracles as bounded nondeterministic operations with verifiable residue

## Install

Into a virtual environment, straight from GitHub:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -U pip
pip install "husks[llm] @ git+https://github.com/rz4/Husks.git"
```

The `[llm]` extra pulls in `litellm` for live oracle calls. Without it, `check`, `doctor`, `init`, and `--stub` runs still work.

For engine-level work (the Hy kernel backend), add the `[hy]` extra:

```bash
pip install "husks[llm,hy] @ git+https://github.com/rz4/Husks.git"
```

Live oracles default to Anthropic. Export a key for live runs:

```bash
export ANTHROPIC_API_KEY=...
```

Any other LiteLLM model name works via `--model`.

## Verify Your Install

```bash
husks doctor
```

Expected with `[llm,hy]` installed and `ANTHROPIC_API_KEY` set:

```text
  ✓ husks                importable
  ✓ conformance          6 vectors at .../spec/conformance
  ✓ selftest             pass
  ✓ hy                   importable
  ✓ litellm              importable
  ✓ ANTHROPIC_API_KEY    set
  ✓ git                  found
  ✓ node                 found
```

To confirm the engine reproduces its frozen roots:

```bash
husks doctor --selftest
```

Expected:

```text
  adversarial                PASS  5382838c381fc9d0...
  demo                       PASS  9977239d5eb0131a...
  malformed-leadingzero      PASS  correctly rejected
  malformed-trailing         PASS  correctly rejected
  malformed-truncated        PASS  correctly rejected
  unsorted                   PASS  4f119edd838718ab...
```

## Quickstart

### Initialize a Project

```bash
husks init ./my-project
cd my-project
```

This creates:
```
my-project/
  design.json       # Build specification (transport)
  prompt.txt        # Example input
  README.md         # Project documentation
```

### Run the Build

```bash
# With stub oracle (no API calls, for testing)
husks run design.json --stub

# With live LLM oracle
export ANTHROPIC_API_KEY=sk-...
husks run design.json --model anthropic/claude-haiku-4-5-20251001
```

### Inspect Results

```bash
# Show build status
husks status design.json

# Explain dependency graph
husks explain design.json --graph --format mermaid

# View convergence history
husks history design.json

# Check environment
husks doctor --live
```

## The Beta Test: Three-Machine Proof

The **Husks beta** is validated by a **three-machine proof** that demonstrates:

1. **Oracle caching works**: M1 pays LLM cost, M2 reuses with zero cost
2. **Cache is portable**: Export from M1, import to M2
3. **Builds are equivalent**: M3's independent rebuild produces same root hash
4. **Verification is automated**: `compare-runs` validates the proof from JSON reports

### Running the Beta Test

```bash
# Clone the repo
git clone https://github.com/rz4/Husks.git
cd Husks

# Install with test dependencies
pip install -e ".[llm,hy]"

# Run the full acceptance test
pytest tests/test_three_machine_cli_acceptance.py -v
```

**What the test does:**

1. **Machine 1**: Builds `examples/beta_seed` with stub oracle
   - Pays oracle cost: $0.0008
   - Exports cache to `cache.tar.gz`
   - Root: `9977239d...`

2. **Machine 2**: Imports cache, runs with `--reuse-only`
   - Oracle cost: $0.00 (complete cache hit)
   - No oracle calls fired (all sealed residue reused)
   - Root: `9977239d...` (identical to M1)

3. **Machine 3**: Independent rebuild with stub oracle
   - Oracle cost: $0.0008 (same as M1 for deterministic stub)
   - Fresh oracle calls (no shared cache with M1 or M2)
   - Root: `9977239d...` (identical to M1 and M2)

4. **Validation**: `compare-runs` verifies all checks pass
   - ✓ M1 paid cost
   - ✓ M2 zero oracle calls
   - ✓ M2 zero cost
   - ✓ M3 paid cost
   - ✓ Same root hash across all three

### Beta Acceptance Criteria (12 Gates)

All gates must pass for beta seal:

- **Gate A**: Site input resolution (no manual copying)
- **Gate B**: CSE wire format (canonical S-expressions)
- **Gate C**: Equivalence validation (compare-runs)
- **Gate D**: Cache validation (seal.json verification)
- **Gate E**: Beta seed example (runnable proof)
- **Gate F**: JSON contracts (structured error output)
- **Gate G**: Three-machine CLI proof (end-to-end acceptance)
- **Gate H**: Code consolidation (no bloat)

Run all gates:
```bash
pytest tests/ -v
```

## Conformance and Permanence

**Verification is only as strong as what you test it against.**

The repo ships six frozen conformance vectors:

**Positive cases** (must reproduce roots):
- `demo` → root `9977239d...`
- `adversarial` → root `5382838c...` (nasty filenames/bytes to break lazy parsers)
- `unsorted` → verifies canonical ordering

**Negative cases** (must reject):
- `malformed-leadingzero` (violates netstring spec)
- `malformed-trailing` (extra bytes after structure)
- `malformed-truncated` (incomplete netstring)

### Cross-Language Verification

The repo includes **three independent readers**:

1. `core.py` (Python, reference implementation)
2. `verify.mjs` (JavaScript, independent port)
3. `readers/generated_reader.py` (written from cold by a model given only the CSE spec)

All three agree on the frozen roots. **If they ever stopped agreeing, the permanence claim would be false.**

```bash
# Run conformance check
husks doctor --conformance --reader "python readers/generated_reader.py"
```

### The Bootstrap Validation

`examples/bootstrap-core.json` turns the conformance test on Husks itself:

1. An `oracle` reads CSE v1/v2 specs (nothing else — no existing reader, no answer key)
2. The oracle writes a dependency-free Python reader to `readers/generated_reader.py`
3. A deterministic gate judges that reader against frozen conformance vectors
4. Pass → writes `readers/VERIFIED`, fail → build halts with diagnosis

**The shape is the thesis in miniature:** The oracle produces, the gate verifies, and the gate is not the oracle. A model can write the verifier; it cannot grade its own verifier. The frozen roots do that.

**What happened:** A small, cheap model wrote a CSE reader from cold and reproduced both frozen roots on the third run. The first two disagreements exposed real spec ambiguities (child ordering rules, hex vs raw bytes in digests). We closed the holes in CSE v2. Then it clicked into the bedrock. Three cents, one call, twenty-five seconds.

## Commands Reference

```bash
husks init [dir]                     # Create new project
husks check design.json              # Validate design
husks run design.json                # Execute build
husks run design.json --reuse-only   # Use cache only (no oracle calls)
husks status design.json             # Show build freshness
husks explain design.json --graph    # Visualize dependencies
husks history design.json [rule]     # Show convergence history
husks compare site1 site2 site3      # Compare output equivalence
husks compare-runs m1.json m2.json   # Validate three-machine proof
husks cache export cache.tar.gz      # Export cache for sharing
husks cache import cache.tar.gz      # Import cache from file
husks doctor --live                  # Check environment readiness
husks doctor --selftest              # Run frozen conformance vectors
husks doctor --conformance           # Run external reader conformance
```

Add `--json` to most commands for machine-readable output.

## Architecture Summary

**Transport → Spine:**
- JSON design file (human-authored)
- ↓ deterministic lowering
- Canonical AST (fixed ordering)
- ↓ CSE encoding
- Netstring atoms (frozen byte format)
- ↓ SHA-256
- Merkle DAG with sealed nodes

**Build execution:**
- Topological sort of dependency graph
- Fire stale rules, seal fresh outputs, reuse sealed residue
- Oracle = bounded nondeterministic event (fuel-limited)
- Action = deterministic shell command
- Trial = speculative A/B test

**Cache validation:**
- Each sealed oracle includes `seal.json`
- Verify recipe digest + output hashes on cache hit
- Reject on mismatch (prevents poisoning)

## Oracles and the Rule That Matters

Live oracles read and write only through declared tools:

```json
["read-file", "write-file", "list-dir", "tree"]
```

**Validation is a deterministic `action`, never an oracle.** Gate on exit code; a nonzero `run` already halts the build. **Do not let a model grade its own output.** The model produces; the action verifies; the seal records the result only if declared outputs exist and validation succeeds. That separation is the whole point, and the one place a build like this can quietly collapse if you let it.

A useful pattern:

1. An `oracle` writes code or text
2. An `action` runs tests, linting, scoring, or another deterministic check
3. Husks seals only if validation passes

## License

Apache-2.0
