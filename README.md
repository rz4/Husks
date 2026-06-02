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
husks check core-bootstrap.json

# Machine 1: build with stub oracle
husks run core-bootstrap.json --site m1 --stub --json > m1.json

# Export M1's cache
husks cache export cache.tar.gz --site m1

# Machine 2: import cache, reuse at zero cost
mkdir m2
husks cache import cache.tar.gz --site m2
husks run core-bootstrap.json --site m2 --reuse-only --json > m2.json

# Machine 3: independent rebuild from empty cache
husks run core-bootstrap.json --site m3 --stub --json > m3.json

# Validate the proof
husks compare-runs m1.json m2.json m3.json
```

Expected:

```
M1: oracle_calls=1, cost=$0.000800        (paid)
M2: oracle_calls=0, cost=$0.000000        (cache reuse)
M3: oracle_calls=1, cost=$0.000800        (independent rebuild)
All three: same root
```

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
pytest tests/test_three_machine_proof.py \
       tests/test_three_machine_cli_acceptance.py \
       tests/test_beta_three_machine.py \
       -v --tb=short

# Full deterministic suite
pytest tests/ -v --tb=short \
       --ignore=tests/test_live_oracle_readiness.py
```

## Commands

```bash
husks init [dir]                                  # Create new project
husks check design.json                           # Validate design
husks run design.json --site ./s1 --stub          # Build with stub oracle
husks run design.json --site ./s1 --reuse-only    # Cache-only (no oracle calls)
husks cache export cache.tar.gz --site ./s1       # Export cache
husks cache import cache.tar.gz --site ./s2       # Import cache
husks compare-runs m1.json m2.json m3.json        # Validate three-machine proof
husks explain --site ./s1 --interactive            # Navigate build residue
husks status design.json --site ./s1              # Show freshness states
husks history design.json [rule]                  # Convergence history
husks doctor --selftest                           # Conformance vectors
husks doctor --live                               # Check live oracle readiness
```

Add `--json` to most commands for machine-readable output.

## Documentation

| Document | Contents |
|----------|----------|
| [docs/liquid-beta.md](docs/liquid-beta.md) | Full CLI reference, JSON schema, FAQ |
| [docs/three-machine-proof.md](docs/three-machine-proof.md) | Beta build plan with gates A-H |
| [docs/theory.md](docs/theory.md) | Foundations, conformance, permanence argument |
| [docs/tutorial.md](docs/tutorial.md) | Claude Code integration tutorial |
| [docs/architecture.md](docs/architecture.md) | Module map, execution model, CSE wire format, CI pipeline |

## License

Apache-2.0
