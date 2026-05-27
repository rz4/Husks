<p align="center">
  <img src="assets/logo/husks-banner.png" alt="Husks" width="900">
</p>

# Husks

**Build Husks, not vibes.**

A model call is an opaque event. By the time you look at it, the event is over and what you hold is its residue. Husks treats that as the only thing worth verifying.

A *design* is a contract you write before any model runs: inputs, outputs, prompts, tools, fuel. The whole graph, on disk, in JSON. The engine walks it, fires only what is stale, seals what is fresh, reuses what is already sealed, and prints exactly what happened. Sealed residue keys on what was asked, not who answered, so a husk built today must verify identically against a reader written long after this engine is gone.

An ordinary build system gives you declared outputs, content-addressed reuse, and a verifiable root. Husks gives you the same thing, pointed at work that includes nondeterministic model calls. Nondeterminism has exactly one home: the `oracle` form. The rest is structure.

For the long version, see [`docs/Theory.md`](docs/Theory.md). For driving Husks from Claude Code, see [`docs/Tutorial.md`](docs/Tutorial.md).

---

## Install

Into a virtual environment, straight from GitHub:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -U pip
pip install "husks[llm] @ git+https://github.com/rz4/Husks.git"
```

That is the whole install. The `[llm]` extra pulls in `litellm` for live oracle calls. Without it, `check`, `selftest`, `init`, and `--stub` runs still work. Only live oracle execution needs `litellm`.

For engine-level work (the Hy kernel backend, lower-level kernel hacking), add the `[hy]` extra:

```bash
pip install "husks[llm,hy] @ git+https://github.com/rz4/Husks.git"
```

To hack on the engine itself, clone instead and `pip install -e ".[llm,hy]"`.

Live oracles default to Anthropic. Export a key for live runs:

```bash
export ANTHROPIC_API_KEY=...
```

Any other LiteLLM model name works via `--model`.

---

## Verify your install

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

A `✗` on `litellm` means `--stub` runs work but live oracles will fail. A `○` on `hy` means the Hy kernel backend is unavailable (optional unless you're hacking on the engine). A `○` on `ANTHROPIC_API_KEY` only matters for live runs; the rest of the system runs without it.

To confirm the engine reproduces its frozen roots:

```bash
husks selftest
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

This recomputes the frozen conformance roots with the bundled Python reader and confirms the malformed vectors are correctly rejected. If anything here is not green, stop. Permanence is what the rest rests on.

To confirm live oracles fire, run the demo without `--stub` once a key is set:

```bash
husks run examples/husks-demo.design.json --site /tmp/husks-demo-live
```

The oracle should fire `claude-haiku-4-5`, write the declared outputs, the action should verify them, and the build should commit with a nonzero dollar cost reported. A second run on the same site reuses every seal and reports `$0.0000`.

---

## The development cycle of a design

The demo design walks the full loop. Clear the site so the example is reproducible:

```bash
rm -rf /tmp/husks-demo
```

### 1. Author

A design is JSON. Two rules: an `oracle` that scaffolds a tiny Python package, an `action` that marks completion.

```json
{
  "name": "husks-demo",
  "fuel": 30,
  "target": "package-complete",
  "rules": [
    {
      "name": "scaffold-package",
      "kind": "oracle",
      "inputs": [],
      "outputs": ["husks-demo/pyproject.toml", "husks-demo/src/husks_demo/cli.py"],
      "prompt": "Create a minimal Python package called husks-demo: a pyproject.toml and src/husks_demo/cli.py exposing a main() entry point that prints a greeting.",
      "tools": ["read-file", "write-file"],
      "fuel": 8
    },
    {
      "name": "package-complete",
      "kind": "action",
      "inputs": ["husks-demo/pyproject.toml", "husks-demo/src/husks_demo/cli.py"],
      "outputs": [".complete"]
    }
  ]
}
```

This file is the contract. Read it before anything runs.

### 2. Check

```bash
husks check examples/husks-demo.design.json
```

```text
  ✓ syntax
  ✓ names
  ✓ paths
  ✓ inputs
  ✓ outputs
  ✓ fuel
  ✓ targets
  ✓ imports
  ✓ other
```

`check` validates the design statically. Add `--verbose` to print the compiled graph, or `husks graph design.json` to render the dependency DAG in `text`, `mermaid`, `dot`, or `json`.

### 3. Stub run

```bash
husks run examples/husks-demo.design.json --site /tmp/husks-demo --stub
```

```text
  ✓ scaffold-package  (oracle)  $0.0000
  ✓ package-complete  (action)

  committed  root 511c1b7e25  fuel 28/30  $0.0000
```

`--stub` runs the graph without firing a model. Oracles write placeholder bytes. This confirms the shape executes, seals are written, the target is reached. Use it whenever the graph itself is new.

### 4. Live run

Drop `--stub`:

```bash
husks run examples/husks-demo.design.json --site /tmp/husks-demo
```

The oracle fires, the action verifies, the build commits. Each rule writes a seal under `.traces/`. The site now contains:

```text
/tmp/husks-demo/
  husks-demo.husk          # serialized residue (Merkle DAG)
  .traces/
    scaffold-package.seal
    scaffold-package.history.jsonl
    package-complete.seal
    package-complete.history.jsonl
  husks-demo/
    pyproject.toml
    src/husks_demo/cli.py
  .complete
```

### 5. Reuse

Run it again:

```bash
husks run examples/husks-demo.design.json --site /tmp/husks-demo
```

```text
  ● scaffold-package  (oracle)
  ● package-complete  (action)

  committed  root 511c1b7e25  fuel 30/30  $0.0000
```

Filled dots mean reuse. Nothing fired. Sealed residue is never regenerated, which makes reruns nearly free.

### 6. Read the state of the site

```bash
husks status examples/husks-demo.design.json --site /tmp/husks-demo
```

```text
  site: /tmp/husks-demo
  root: 511c1b7e25c5facd...
  rules:
    ✓ package-complete     fresh
    ✓ scaffold-package     fresh
  artifacts:
    ✓ .complete                fresh
    ✓ husks-demo/pyproject.toml fresh
    ✓ husks-demo/src/husks_demo/cli.py fresh
```

Now edit an output by hand. The seal records what was produced; edit the file, and the rule goes dirty:

```bash
echo "# tampered" >> /tmp/husks-demo/husks-demo/pyproject.toml
husks status examples/husks-demo.design.json --site /tmp/husks-demo
```

```text
  rules:
    ▸ package-complete     stale  (input_changed:husks-demo/pyproject.toml)
    ! scaffold-package     dirty  (output_hash_changed:husks-demo/pyproject.toml)
  artifacts:
    ✓ .complete                fresh
    ! husks-demo/pyproject.toml modified
    ✓ husks-demo/src/husks_demo/cli.py fresh
```

`husks diff` shows the exact hashes:

```bash
husks diff examples/husks-demo.design.json --site /tmp/husks-demo
```

```text
  modified:
    husks-demo/pyproject.toml 45ddb7152d -> 301e1723d8
```

`husks explain` dumps a rule's seal and state:

```bash
husks explain scaffold-package --site /tmp/husks-demo
```

```text
  rule: scaffold-package  (oracle)
  state: dirty  (output_hash_changed:husks-demo/pyproject.toml)
  outputs: husks-demo/pyproject.toml, husks-demo/src/husks_demo/cli.py
  seal:    898a9384efb9e9f2...
  history: 1 runs
```

Re-run the build and the dirty rule re-fires; the action downstream re-runs because its input changed.

### 7. Iterate

Designs are not written once. They are *worked*. You perturb a prompt, run again, read the trace, decide whether the change helped, pin what works, perturb the next thing. `husks history` classifies how each node has moved across runs:

```bash
husks history examples/husks-demo.design.json --site /tmp/husks-demo
```

```text
  convergence history summary
  scaffold-package         1 runs  converging
  package-complete         1 runs  converging
```

The classifier reports four trends, and they mean different things:

- **converging**: fuel falling or flat, prompt flat. The node is settling toward its minimal form. Honest progress.
- **prompt-loading**: fuel falling, prompt *rising*. The alarm. You are hand-migrating the determined part of the work into the prompt and then paying the oracle to read your own work back. The cost did not leave; it moved from the API bill to your hands.
- **stable**: output hashes identical across runs. The specimen is fixed.
- **volatile**: no settled trend. Not converged.

### 8. Extract

The end state of a converged node is to stop being an oracle. An oracle whose output is fixed by its inputs is not an oracle. It is transcription, and transcription is a deterministic `action` you have not extracted yet. When `history` reports `stable`, rewrite the rule as an `action` and stop paying an API call to interpret a function you have already written.

That is the cycle. Author the contract, check, dry-run, fire, read, iterate, extract. Across revisions, the fixed point you are working toward is the maximal deterministic skeleton with the smallest residue of oracles naming the parts you have not yet reduced.

---

## Driving Husks from Claude Code

`husks init` wires a project so Claude Code authors *designs* instead of running an unbounded agent loop:

```bash
cd /path/to/your-project
husks init
```

It runs `selftest`, checks for `ANTHROPIC_API_KEY`, installs the Husks skill at `.claude/skills/husks`, and emits a `CLAUDE.md` stance file versioned with the engine. From there, Claude Code reads the skill, writes `design.json`, runs `check`, and waits for your approval before any oracle fires. Full walkthrough: [`docs/Tutorial.md`](docs/Tutorial.md).

---

## Rule kinds

| Kind | Use |
| :--- | :--- |
| `action` | Run deterministic local work. |
| `oracle` | Run one bounded model call. |
| `trial` | Try several branches and keep one winner. |
| `let` | Share an already-defined subtree. |
| `cond` | Choose a branch from a predicate. |
| `commit` | Stop successfully with a value. |
| `halt` | Stop with a failure reason. |

Start with `action` and `oracle`. Add the others when the graph shape requires them.

## Fuel

Every design has a top-level `fuel` budget. Oracle rules also declare local fuel. Top-level fuel bounds the build. Oracle fuel bounds the local model/tool loop for that oracle. `husks check` rejects designs whose declared oracle budgets exceed the top-level budget. There are no unbounded loops to wait out.

## Commands

```text
husks check    design.json               validate; --verbose prints compiled graph
husks run      design.json --site DIR    check, compile, execute
husks status                --site DIR   freshness state of a built site
husks diff                  --site DIR   differences between sealed and current artifacts
husks explain  SUBJECT      --site DIR   explain a rule or artifact
husks graph    design.json               render dependency graph (text|mermaid|dot|json)
husks history  design.json  --site DIR   per-rule convergence history
husks selftest                           recompute frozen conformance roots
husks doctor                             environment and dependency check
husks init                               wire a project for Claude Code
husks gate     "READER_CMD" --stamp-dir DIR  run conformance gate on an external CSE reader
```

`husks-gate` is also available as a standalone entry point. Add `--json` to most commands for machine-readable output.

---

## Oracles and the rule that matters

Live oracles read and write only through declared tools:

```json
["read-file", "write-file", "list-dir", "tree"]
```

Validation is a deterministic `action`, never an oracle. Gate on exit code; a nonzero `run` already halts the build. **Do not let a model grade its own output.** The model produces; the action verifies; the seal records the result only if declared outputs exist and validation succeeds. That separation is the whole point, and the one place a build like this can quietly collapse if you let it.

A useful pattern:

1. An `oracle` writes code or text.
2. An `action` runs tests, linting, scoring, or another deterministic check.
3. Husks seals only if validation passes.

---

## Conformance

Husks ships frozen conformance vectors under `spec/conformance`: positive cases that must reproduce their roots, and adversarial fixtures that must be *rejected*. The repo ships two independent readers, Python (`core.py`) and JavaScript (`verify.mjs`), built from the spec and run against the same vectors. They agree. If they ever stopped agreeing, the permanence claim would be false.

```bash
husks selftest                                 # built-in Python reader
node spec/conformance/verify.mjs spec/conformance/demo.husk \
     spec/conformance/demo.site "$(cat spec/conformance/demo.root)"   # JS reader
husks gate "python readers/generated_reader.py" --stamp-dir readers   # external reader
```

A reader command must accept `<husk-file> <site-dir>` and print the lowercase-hex build root to stdout.

## Bootstrap

`examples/bootstrap-core.json` turns the conformance test on the framework itself. An `oracle` reads CSE v1 and v2 (no existing reader, no answer key) and writes a dependency-free Python reader. A deterministic gate then judges that reader against the frozen vectors.

```bash
rm -rf /tmp/bootstrap-core && mkdir -p /tmp/bootstrap-core
cp spec/CSE-v1.md spec/CSE-v2.md /tmp/bootstrap-core/
husks run examples/bootstrap-core.json --site /tmp/bootstrap-core
```

A successful run writes `readers/generated_reader.py`, `readers/gate-report.txt`, and `readers/VERIFIED`. The gate report contains `GATE PASS`. The shape is the whole thesis in miniature: the oracle produces, the gate verifies, the gate is not the oracle.

## Portability rules

Keep paths relative to the site. Husks rejects absolute paths and `..` escapes. A leaked `/home/<user>/…` would live in the seal forever.

Keep validation deterministic. Tests, scoring scripts, formatters, and gates are `action` rules.

Keep oracles bounded. Every oracle gets a small output contract and a fuel limit.

Keep `run` commands portable. No `source .../activate`, no machine-specific paths; call tools directly.

## Status

Current capabilities:

- JSON designs lowering deterministically into the Husks build form.
- Sealed artifact reuse keyed on recipe and input hashes.
- Per-rule trace and history files; convergence classification.
- Stub and live oracle execution via LiteLLM.
- Python and JavaScript CSE readers built from the spec.
- Frozen positive and adversarial conformance vectors.
- `husks gate` for external reader validation.
- `husks init` and a versioned Claude Code skill.
- Bootstrap example that generates and verifies a reader from the specs.

## License

Apache-2.0
