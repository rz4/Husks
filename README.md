<p align="center">
  <img src="assets/logo/husks-banner.png" alt="Husks" width="600" />
</p>

<p align="center">
  <em>A small build system for nondeterministic work.</em>
</p>

---

Husks is a build calculus that treats every model call as an opaque event and
verifies only the **residue** -- the bytes left on disk. You write a design (a
build graph with inputs, outputs, and fuel limits), the runtime fires an oracle
for each nondeterministic step, and the engine seals every result into a Merkle
DAG. If the inputs haven't changed, the seal is reused. If they have, the oracle
fires again -- bounded by fuel, sandboxed to declared outputs, and independently
verifiable.

The result is a `.husk` file: a content-addressed snapshot of the entire build.
Two machines that run the same design must produce the same root hash. A third
machine can verify this without re-running anything. That's the
[three-machine proof](docs/three-machine-proof.md).

## Install

```bash
pip install git+https://github.com/rzamora-lbnl/Husks.git
```

Verify the installation:

```bash
husks --version
husks doctor
```

### Requirements

- Python >= 3.10
- An Anthropic API key (for live oracle runs; not needed for `--stub` builds)

## Quick start

**1. Write a design** in [Locke](docs/locke.md) or JSON:

```
# hello.locke

design hello :- [
  fuel := 10
  target := greet

  greet :- oracle [
    prompt := "Write a greeting to out.txt"
    outputs := [out.txt]
  ]
]
```

**2. Check the design** (no model calls, validates structure):

```bash
husks check hello.locke
```

**3. Run the build** (fires the oracle, seals the result):

```bash
husks run hello.locke --site ./site --model anthropic/claude-haiku-4-5-20251001
```

**4. Inspect the site:**

```bash
husks status ./site
husks verify ./site
```

## How it works

A Husks build has three roles:

| Role | What | Who |
| :--- | :--- | :--- |
| **Author** | Writes the design (the build graph) | You, or a Claude Code instance |
| **Producer** | Generates bytes inside a bounded workspace | A fuel-limited oracle (LLM call) |
| **Verifier** | Seals results, reuses caches, recomputes hashes | The deterministic engine |

The author and the producer are different model calls. The verifier is not a
model at all. This separation is the point: a model can write a build graph,
but it cannot grade its own output -- that's what the sealed Merkle DAG is for.

## Commands

| Command | What it does |
| :--- | :--- |
| `husks check <design>` | Validate a design without executing |
| `husks run <design>` | Execute a design into a site |
| `husks status <site>` | Inspect site state and freshness |
| `husks verify <site>` | Recompute the `.husk` root hash |
| `husks compare <s1> <s2> [s3]` | Equivalence check across sites |
| `husks history <site> [rule]` | Convergence analysis across runs |
| `husks cache export <file>` | Pack cache for transfer |
| `husks cache import <file>` | Unpack cache into a site |
| `husks doctor` | Diagnose the local environment |

Every command supports `--json` for machine-readable output.

## Documentation

Full docs live in [`docs/`](docs/README.md), organized as a reading DAG from
surface usage down to the formal wire format:

- [Tutorial](docs/tutorial.md) -- driving Husks from Claude Code
- [CLI reference](docs/liquid-beta.md) -- commands, schema, FAQ
- [Locke language](docs/locke.md) -- the design surface syntax
- [Theory](docs/theory.md) -- the residue stance
- [Three-machine proof](docs/three-machine-proof.md) -- independent re-realization
- [Architecture](docs/architecture.md) -- seal preimage, Merkle DAG, recipe identity

## License

[Apache-2.0](LICENSE)
