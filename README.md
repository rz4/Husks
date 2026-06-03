<p align="center">
  <img src="assets/logo/husks-banner.png" alt="Husks" width="900">
</p>

# Husks

**Build Husks, not vibes.**

A build system for nondeterministic (LLM-powered) work. Husks treats model calls as opaque events and verifies only what they leave behind: sealed residue on disk, hashed and inspectable from the outside.

Three rule types: `action` (deterministic), `oracle` (bounded LLM call), `trial` (speculative A/B test). Execution consumes fuel and terminates by `commit` or `halt`. Every claim the system makes is a claim about residue.

## Install

Python >= 3.10 required.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -U pip
pip install "husks[llm] @ git+https://github.com/rz4/Husks.git"
```

The `[llm]` extra pulls in `litellm` for live oracle calls. Without it, `--stub` runs, `check`, `doctor`, and `init` still work.

Verify the install:

```bash
husks doctor --selftest
```

All conformance vectors should pass. If anything fails here, stop — the rest depends on it.

## Run the Three-Machine Proof

This is the core demonstration. It proves cache reuse (M2) and independent re-realization (M3) from the same seed design, using zero API cost.

```bash
# Initialize a project
husks init
husks check core-bootstrap.locke

# Machine 1: build with stub oracle
husks run core-bootstrap.locke --site m1 --stub

# Export M1's cache
husks cache export cache.tar.gz --site m1

# Machine 2: import cache, reuse at zero cost
husks cache import cache.tar.gz --site m2
husks run core-bootstrap.locke --site m2 --reuse-only

# Machine 3: independent rebuild from empty cache
husks run core-bootstrap.locke --site m3 --stub

# Validate the proof
husks compare m1 m2 m3
```

Expected: M1 pays oracle cost, M2 reuses from cache at zero cost with zero oracle calls, M3 rebuilds independently at comparable cost. All three share the same build root (stub oracle is deterministic).

M2 proves reuse. M3 proves portable re-realization from the seed design.

### Inspect the results

```bash
husks explain --site m1 --node generate --aperture 3   # M1: paid oracle
husks explain --site m2 --node generate --aperture 3   # M2: cached
husks explain --site m3 --node generate --aperture 3   # M3: independent
```

## Run the Tests Locally

From a source checkout:

```bash
git clone https://github.com/rz4/Husks.git
cd Husks
python -m venv .venv && source .venv/bin/activate
pip install -e ".[llm]" pytest

# Three-machine proof (headline invariant)
pytest tests/test_LIQUID_69_three_machine_proof.py \
       tests/test_LIQUID_70_three_machine_cli_acceptance.py \
       tests/test_LIQUID_68_beta_three_machine.py \
       -v --tb=short

# Full deterministic suite
pytest tests/ -v --tb=short \
       --ignore=tests/test_SOLID_50_live_oracle_readiness.py
```

## Commands

```bash
husks init [dir]                                  # Create new project
husks check design.locke                          # Validate design
husks run design.locke --site ./s1 --stub         # Build with stub oracle
husks run design.locke --site ./s1 --reuse-only   # Cache-only (no oracle calls)
husks cache export cache.tar.gz --site ./s1       # Export cache
husks cache import cache.tar.gz --site ./s2       # Import cache
husks compare s1 s2 s3                            # Equivalence + three-machine proof
husks status s1                                   # Show freshness states
husks explain --site ./s1 --interactive           # Navigate build residue
husks history design.locke [rule]                 # Convergence history
husks doctor --selftest                           # Conformance vectors
husks doctor --live                               # Check live oracle readiness
```

Add `--json` to most commands for machine-readable output.

## Documentation

| Document | Contents |
|----------|----------|
| [docs/README.md](docs/README.md) | **Start here** — the documentation reading DAG (surface → philosophy → science → formal) |
| [docs/liquid-beta.md](docs/liquid-beta.md) | Full CLI reference, JSON schema, FAQ |
| [docs/three-machine-proof.md](docs/three-machine-proof.md) | Beta build plan with gates A-H |
| [docs/theory.md](docs/theory.md) | Foundations, conformance, permanence argument |
| [docs/tutorial.md](docs/tutorial.md) | Claude Code integration tutorial |
| [docs/architecture.md](docs/architecture.md) | Module map, execution model, CSE wire format, CI pipeline |

## License

Apache-2.0
