# Running Claude Code with Husks

A tutorial for driving the Husks build calculus from a Claude Code instance.

By the end you will have Claude Code authoring **designs** instead of running an
unbounded agent loop: it writes a build graph, you read the contract before any
model touches anything, the runtime fires only what is stale, and every claim
the system makes is a claim about sealed residue you can recompute yourself.

> Install is a single `pip install` from the GitHub URL — no checkout required.
> Setup is one command after that: `husks doctor`.

---

## 0. The mental model (read this first)

There are **three** roles, and keeping them separate is the whole point.

| Role | Who plays it | What it does |
| :--- | :--- | :--- |
| **Author** | the Claude Code instance | reads your task, writes `design.locke`, runs the CLI, reports |
| **Producer** | the husks `oracle` (a litellm call, default `claude-haiku-4-5`) | the one nondeterministic step — generates bytes inside a bounded workspace |
| **Verifier** | the deterministic engine + frozen roots | seals, reuses, recomputes hashes; grades neither author nor producer on its say-so |

The author and the producer are **different model calls**. Claude Code writes
the contract; a separate, fuel-bounded oracle inside the design produces the
residue. The verifier is not a model at all. A model can write a verifier; it
cannot grade its own verifier — that separation is what you are setting up.

---

## 1. Prerequisites

- **Python >= 3.10**
- **Node.js** (optional — only for the independent JavaScript reader / gate cross-check)
- **Claude Code** — `npm install -g @anthropic-ai/claude-code`
- **An Anthropic API key** — needed only for *live* oracle runs, not for `--stub`

---

## 2. Install Husks

Into a virtual environment, straight from GitHub:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -U pip                                          # PEP 508 direct refs
pip install "husks[llm] @ git+https://github.com/rz4/Husks.git"
```

That's the whole install. The `[llm]` extra pulls in `litellm` for live oracle
calls. Without it, `check`, `doctor`, and `--stub` runs still work —
only live oracle execution requires `litellm`. The wheel also ships the
conformance vectors and the skill.

> **Contributing to Husks itself?** Use an editable checkout instead —
> `git clone ...` then `pip install -e ".[llm]"`. Both install modes are fully
> supported; the editable one just lets you hack on the engine in place.

---

## 3. Confirm the engine is sound

Verify the install and check that dependencies are available:

```bash
husks doctor
```

Expected: exit code 0. If anything here is not green, stop — fix the
environment before proceeding.

(`python -m pytest tests/ -q` runs the full suite, but that needs a source
checkout; `doctor` is the install-level soundness check.)

---

## 4. Copy the example design and check your workspace

Copy the bundled `core-bootstrap` example into a fresh working directory:

```bash
cp -r "$(python -c 'import husks; print(husks.__path__[0])')/../examples/core-bootstrap" my-project
cd my-project
```

Use `husks tree` to see what's in the directory — designs, sites, and source
files — and confirm every required input is present:

```bash
husks tree
```

Expected output:

```
  core-bootstrap.locke  ✓

  gate.py
  spec/
    CSE-v1.md
    CSE-v2.md
```

The green **✓** next to the design means all of its `site-inputs` exist on
disk. If any source file were missing you would see a red **✗** with the
missing paths listed. Fix those before proceeding — the build will fail
without them.

---

## 5. Run the three-machine proof

This is the core reproduction path. It proves cache reuse (M2) and independent
re-realization (M3) from the same seed design.

### Check the design

```bash
husks check core-bootstrap.locke
```

### Machine 1: original realization

```bash
husks run core-bootstrap.locke --site m1 --stub
```

M1 builds the design with a stub oracle, pays synthetic oracle cost, and
produces sealed outputs.

### Export cache from M1

```bash
husks cache export cache.tar.gz --site m1
```

### Machine 2: cached reuse at zero cost

```bash
husks cache import cache.tar.gz --site m2
husks run core-bootstrap.locke --site m2 --reuse-only
```

M2 imports M1's cache and runs with `--reuse-only`. It makes zero oracle calls,
pays zero cost, and materializes the same artifact from verified cached residue.

### Machine 3: independent re-realization

```bash
husks run core-bootstrap.locke --site m3 --stub
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
husks status --site m1   # M1: paid oracle cost
husks status --site m2   # M2: cached reuse
husks status --site m3   # M3: independent realization
```

---

## 6. Troubleshooting

| Symptom | Cause | Fix |
| :--- | :--- | :--- |
| `pip install "husks @ git+..."` rejects the spec | old pip without PEP 508 direct-reference support | `pip install -U pip`, retry |
| `No module named litellm` on a live run | installed without the `[llm]` extra | reinstall with `pip install "husks[llm] @ git+..."` |
| `AuthenticationError` / 401 from the oracle | no key in env | fill `.env`, then `set -a && source .env` |
| Claude Code doesn't use Husks | skill not loaded | `claude doctor`; confirm `.claude/skills/husks/SKILL.md` exists; restart session |
| `check` rejects the design | missing `target`/output, oracle fuel/tools, or undeclared input | read the error; the skill repairs and re-checks |
| Build halts on "empty or missing output" | an oracle wrote nothing or a 0-byte file | refine the oracle prompt; this guard is working as intended |
| Design uses `let`/`cond`/`trial` unexpectedly | advanced forms need care | start with `action`+`oracle`; use advanced forms only when needed |

---

## Cross-references

For the engine internals, see [`architecture.md`](architecture.md). For the
permanence argument, see [`theory.md`](theory.md). For the full CLI reference,
see [`liquid-beta.md`](liquid-beta.md). For the CSE wire format specs, see
`spec/CSE-v1.md` and `spec/CSE-v2.md`.
