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
Two machines that run the same design produce the same root hash wherever the
work is deterministic or a sealed result is reused. Where an oracle fires live,
they produce equivalent residue under a relation the design declares, not an
identical hash, because the event is not reproducible. A third machine verifies
either claim without re-running anything. That's the
[three-machine proof](docs/three-machine-proof.md).

## Install

```bash
pip install git+https://github.com/rz4/Husks.git
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
# kernel-bootstrap.locke -- Generates a CSE reader from the frozen spec.
#

#- Design fixture
"kernel-bootstrap"       := design
                    5  := fuel
             [0.5 2.0] := tolerance

#- Site inputs: spec files + standalone gate script
gate.py := site
spec := site [
  CSE-v1.md
  CSE-v2.md
]

#- Deterministic validation gate
validate := action [
  readers/generated_reader.py := inputs

  readers/gate-report.txt     := free   # output
  readers/VERIFIED            := exact  # output

  "python3 gate.py 'python3 readers/generated_reader.py' --stamp-dir readers" := run

  #- Nondeterministic generator
  generate :- oracle [
    [CSE-v1.md CSE-v2.md]         := inputs
    readers/generated_reader.py   := free
    [read-file write-file]        := tools
    4                             := fuel

    """Read CSE-v1.md (the frozen spec) and CSE-v2.md (clarifications).
    Implement a dependency-free CSE reader in a single Python file
    at readers/generated_reader.py.

    Write only readers/generated_reader.py.""" := prompt

]]
```

**2. Check the design** (no model calls, validates structure):

```bash
husks check kernel-bootstrap.locke
```

**3. Run the build** (fires the oracle, seals the result):

```bash
husks run kernel-bootstrap.locke --site ./M1 --model anthropic/claude-haiku-4-5-20251001
```

**4. Inspect the site:**

```bash
husks status ./M1
husks verify ./M1
```

**5. Run the three-machine proof** (independent re-realization):

```bash
husks cache export M1 cache.tar.gz
husks cache import cache.tar.gz M2
husks run kernel-bootstrap.locke --site ./M2 --reuse-only
husks run kernel-bootstrap.locke --site ./M3
husks compare M1 M2 M3
```

```
     ◆    design: kernel-bootstrap
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

  ...

  equivalence
  ───────────────────────────────────────────────────────────────────────────────
  ✓ M1 ≡ M2
  ✗ M1 ≡ M3
  ✗ M2 ≡ M3
  ───────────────────────────────────────────────────────────────────────────────
  ✗ not equivalent

  three-machine proof
  ───────────────────────────────────────────────────────────────────────────────
  ✓ M1↔M2↔M3 husk identical
  ✓ M1↔M2 root identical
  evidence
  ✓ M1 fired oracles
  ✓ M1 paid cost
  ✓ M2 zero oracle cost
  ✓ M2 cache reuse
  ✓ M3 fired oracles
  ✓ M3 paid cost
  ✗ M1↔M3 outputs equivalent
  ───────────────────────────────────────────────────────────────────────────────
  ✓ proof satisfied
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
| `husks cache export <site> <file>` | Pack cache for transfer |
| `husks cache import <file> <site>` | Unpack cache into a site |
| `husks config show` | Show resolved oracle configuration |
| `husks config template` | Print annotated `.husks.toml` template |
| `husks doctor` | Diagnose the local environment |

Every command supports `--json` for machine-readable output.

## Documentation

Full docs live in [`docs/`](docs/README.md), organized as a reading DAG from
surface usage down to the formal wire format:

- [Tutorial](docs/tutorial.md) -- install, configure, and run the three-machine proof
- [CLI reference](docs/cli.md) -- commands, schema, FAQ
- [Locke language](docs/locke.md) -- the design surface syntax
- [Theory](docs/theory.md) -- the residue stance
- [Three-machine proof](docs/three-machine-proof.md) -- independent re-realization
- [Architecture](docs/architecture.md) -- seal preimage, Merkle DAG, recipe identity

## License

[Apache-2.0](LICENSE)
