# Getting Started with Husks

A hands-on tutorial for ML/AI engineers building PoCs with LLM calls.

By the end you will have a working build that fires an oracle, seals the
result into a Merkle DAG, and runs the three-machine proof — all from the
command line.

> Install is a single `pip install` from the GitHub URL. No checkout required.
> Setup is one command after that: `husks doctor`.

---

## 0. The mental model (read this first)

There are **three** roles, and keeping them separate is the whole point.

| Role | Who plays it | What it does |
| :--- | :--- | :--- |
| **Author** | you (or any tool that writes a `.locke` / `.json` design) | reads the task, writes the build graph, sets the global fuel budget and per-oracle fuel caps |
| **Producer** | the husks `oracle` (a litellm call, default `claude-haiku-4-5`) | the one nondeterministic step: generates bytes inside a bounded workspace |
| **Verifier** | the deterministic engine + frozen roots | seals, reuses, recomputes hashes; grades neither author nor producer on its say-so |

The author and the producer are **different model calls** (or a human and a
model call). The verifier is not a model at all. A model can write a
verifier, but it cannot grade its own verifier. That separation is what
you are setting up.

---

## 1. Prerequisites

- **Python >= 3.10**
- **An Anthropic API key**: needed only for *live* oracle runs, not for `--stub`

---

## 2. Install Husks

Into a virtual environment, straight from GitHub:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -U pip
pip install "husks @ git+https://github.com/rz4/Husks.git"
```

That's the whole install. `litellm` comes with it and powers live oracle
calls. `check`, `doctor`, and `--stub` runs need no API key; only live
oracle execution does.

> **Contributing to Husks itself?** Use an editable checkout instead:
> `git clone ...` then `pip install -e .`. Both install modes are fully
> supported; the editable one just lets you hack on the engine in place.

---

## 3. Confirm the engine is sound

Verify the install and check that dependencies are available:

```bash
husks doctor
```

Expected: silent, exit code 0. If anything is wrong, failing checks are
printed to stderr. Fix those before proceeding.

(`python -m pytest tests/ -q` runs the full suite, but that needs a source
checkout; `doctor` is the install-level soundness check.)

---

## 4. Copy the example design and check your workspace

Copy the bundled `kernel-bootstrap` example into a fresh working directory:

```bash
cp -r "$(python -c 'import husks; print(husks.__path__[0])')/../examples/kernel-bootstrap" my-project
cd my-project
```

Use `husks tree` to see what's in the directory (designs, sites, and source
files) and confirm every required input is present:

```bash
husks tree
```

Expected output:

```
  kernel-bootstrap.locke  ✓

  gate.py
  spec/
    CSE-v1.md
    CSE-v2.md
```

The green **✓** next to the design means all of its site inputs exist on
disk. If any source file were missing you would see a red **✗** with the
missing paths listed. Fix those before proceeding; the build will fail
without them.

---

## 5. Configure the oracle (optional)

Create a `.husks.toml` in your project root to configure the oracle
backend. You can generate an annotated template:

```bash
husks config template > .husks.toml
```

Edit it to set your model, API key, and any per-rule overrides:

```toml
[oracle]
model = "anthropic/claude-haiku-4-5-20251001"
api_key = "$ANTHROPIC_API_KEY"    # $ENV_VAR expansion works everywhere
temperature = 0.7

[oracle.params]
top_p = 0.95

[oracle.rules.expensive_rule]
model = "anthropic/claude-sonnet-4-20250514"
backend = "claude-code"

[oracle.rules.expensive_rule.params]
temperature = 0.2
```

Any string starting with `$` is resolved from the environment — this works
for `api_key`, `api_base`, and any value inside `params` or `rules`.

Verify your resolved config:

```bash
husks config show
husks config show --rule expensive_rule
```

API keys are masked as `****` in the output. DevOps can pipe `--json`
output into their toolchain.

---

## 6. Run the three-machine proof

This is the core reproduction path. It proves cache reuse (M2) and independent
re-realization (M3) from the same seed design.

### Check the design

```bash
husks check kernel-bootstrap.locke
```

### Machine 1: original realization

```bash
husks run examples/stub-proof/stub-proof.json --site m1 --stub
```

M1 builds the design with a stub oracle, pays synthetic oracle cost, and
produces sealed outputs.

**Note:** We use `stub-proof.json` here because `kernel-bootstrap.locke` requires
a live oracle — its conformance gate rejects stub-generated placeholder content.
Use `kernel-bootstrap.locke` with a real API key for production proofs.

### Export cache from M1

```bash
husks cache export m1 cache.tar.gz
```

### Machine 2: cached reuse at zero cost

```bash
husks cache import cache.tar.gz m2
husks run examples/stub-proof/stub-proof.json --site m2 --reuse-only
```

M2 imports M1's cache and runs with `--reuse-only`. It makes zero oracle calls,
pays zero cost, and materializes the same artifact from verified cached residue.

### Machine 3: independent re-realization

```bash
husks run examples/stub-proof/stub-proof.json --site m3 --stub
```

M3 starts with an empty cache and independently builds a valid artifact at
comparable cost to M1.

### Validate equivalence

```bash
husks compare m1 m2 m3
```

Expected: each site renders as a status card (diamond banner, motif tree,
per-node expense), followed by the three-machine proof checks:

```
── Three-Machine Proof ──
  ✓ M1↔M2↔M3 husk identical          (required)
  ✓ M1↔M2 root identical              (required)
  · M1 fired oracles                   (evidence)
  · M1 paid cost                       (evidence)
  · M2 zero oracle cost                (evidence)
  · M2 cache reuse                     (evidence)
  · M3 fired oracles                   (evidence)
  · M3 paid cost                       (evidence)
  · M1↔M3 outputs equivalent           (evidence)

proof satisfied
```

Add `--json` for machine-readable output with `proof.satisfied` and
`proof.checks` fields.

### Inspect individual machines (optional)

```bash
husks status m1   # M1: paid oracle cost
husks status m2   # M2: cached reuse
husks status m3   # M3: independent realization
```

---

## 7. Handing off to DevOps

When you hand a Husks project to another team:

1. **Generate a config template** for them: `husks config template > .husks.toml`
2. They set environment variables (`$ANTHROPIC_API_KEY`, `$API_BASE`, etc.)
   and the `$ENV_VAR` references in `.husks.toml` resolve automatically.
3. **Show resolved config** without exposing secrets: `husks config show`
4. **Per-rule overrides** let them route expensive rules to a different
   model or backend without touching the design.
5. The `.husk` file and `husks verify` give them a self-verifying artifact
   — no trust in the build machine required.

---

## 8. Troubleshooting

| Symptom | Cause | Fix |
| :--- | :--- | :--- |
| `pip install "husks @ git+..."` rejects the spec | old pip without PEP 508 direct-reference support | `pip install -U pip`, retry |
| `AuthenticationError` / 401 from the oracle | no key in env | set `api_key = "$ANTHROPIC_API_KEY"` in `.husks.toml`, then `export ANTHROPIC_API_KEY=...` |
| `husks config show` returns `{}` | no `.husks.toml` found | create one with `husks config template > .husks.toml` |
| `warning: unknown key` on config load | typo in `.husks.toml` | check spelling against `husks config template` |
| `check` rejects the design | missing `target`/output, oracle fuel/tools, or undeclared input | read the error; fix the design and re-check |
| Build halts on "empty or missing output" | an oracle wrote nothing or a 0-byte file | refine the oracle prompt; this guard is working as intended |
| Design uses `let`/`cond`/`trial` unexpectedly | advanced forms need care | start with `action`+`oracle`; use advanced forms only when needed |

---

## Cross-references

For the engine internals, see [`architecture.md`](architecture.md). For the
permanence argument, see [`theory.md`](theory.md). For the full CLI reference,
see [`cli.md`](cli.md). For the CSE wire format specs, see
`spec/CSE-v1.md` and `spec/CSE-v2.md`.
