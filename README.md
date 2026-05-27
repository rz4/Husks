<p align="center">
  <img src="assets/logo/husks-banner.png" alt="Husks" width="900">
</p>

# Husks

**Build Husks, not vibes.**

Husks is a small build system for work that may include model calls.

A Husks design declares rules, inputs, outputs, and a fuel budget. Husks runs the rules, writes artifacts into a site directory, seals each rule by content hash, and reuses work when the residue is unchanged.

Use Husks when you want an agent or model to produce files, but you still want ordinary build-system properties: declared outputs, repeatable checks, traceable history, and a root that can be recomputed later.

## Install

Clone the repo and install the base package:

```bash
git clone https://github.com/rz4/Husks.git
cd Husks
python -m venv .venv
source .venv/bin/activate
pip install -e .
```

The base install supports `check`, `show`, `run --stub`, `history`, `selftest`, and `husks-gate`.

For live model calls, install the LLM extra:

```bash
pip install -e ".[llm]"
```

Husks uses LiteLLM for live oracles. The default model is Anthropic, so a typical setup is:

```bash
export ANTHROPIC_API_KEY=...
```

You can also pass another LiteLLM model name with `--model`.

## First run

Validate the demo design:

```bash
husks check examples/husks-demo.design.json
```

Run it with the stub oracle. This does not call a model:

```bash
husks run examples/husks-demo.design.json --site /tmp/husks-demo --stub
```

Run it again:

```bash
husks run examples/husks-demo.design.json --site /tmp/husks-demo --stub
```

On the second run, Husks should reuse sealed work instead of rebuilding unchanged artifacts.

Inspect convergence history:

```bash
husks history examples/husks-demo.design.json --site /tmp/husks-demo
```

For machine-readable output:

```bash
husks run examples/husks-demo.design.json --site /tmp/husks-demo --stub --json
```

## What Husks writes

A run writes into a site directory. The site contains the artifacts declared by the design, plus Husks metadata.

Typical outputs look like this:

```text
/tmp/husks-demo/
  husks-demo.husk
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

The `.husk` file is the serialized build residue. The `.traces` directory records seals and per-rule history. A seal includes recipe identity, input hashes, and output hashes. If an output is changed by hand, the next run treats the rule as stale.

## Design files

A design is a JSON file. Most user designs start with two rule kinds:

`oracle` asks a model or stub backend to produce files.

`action` runs deterministic local work, such as tests, formatters, validators, or packaging commands.

Example:

```json
{
  "name": "hello-husks",
  "fuel": 10,
  "target": "verify",
  "rules": [
    {
      "name": "write-program",
      "kind": "oracle",
      "inputs": [],
      "outputs": ["hello.py"],
      "prompt": "Write hello.py. It should print hello from husks.",
      "tools": ["write-file"],
      "fuel": 4
    },
    {
      "name": "verify",
      "kind": "action",
      "inputs": ["hello.py"],
      "outputs": ["test-output.txt"],
      "run": "python hello.py > test-output.txt"
    }
  ]
}
```

Run it with:

```bash
husks check design.json
husks run design.json --site /tmp/hello-husks --stub
```

For a live model run:

```bash
husks run design.json --site /tmp/hello-husks --model anthropic/claude-haiku-4-5-20251001
```

## Rule kinds

The JSON design language supports the full Husks build form.

| Kind | Use |
| :--- | :--- |
| `action` | Run deterministic local work. |
| `oracle` | Run one bounded model call. |
| `trial` | Try several branches and keep one winner. |
| `let` | Share an already-defined subtree. |
| `cond` | Choose a branch from a predicate. |
| `commit` | Stop successfully with a value. |
| `halt` | Stop with a failure reason. |

You usually do not need all of these. Start with `action` and `oracle`. Add the other forms when the graph shape requires them.

## Fuel

Every design has a top-level `fuel` budget. Oracle rules also declare local fuel.

```json
{
  "name": "write-docs",
  "kind": "oracle",
  "inputs": ["spec.md"],
  "outputs": ["README.md"],
  "prompt": "Write a user README from spec.md.",
  "tools": ["read-file", "write-file"],
  "fuel": 6
}
```

Top-level fuel bounds the build. Oracle fuel bounds the local model/tool loop for that oracle. `husks check` rejects designs whose declared oracle budgets exceed the top-level budget.

## Commands

```bash
husks check design.json
```

Validate a design.

```bash
husks show design.json
```

Print the compiled rule structure.

```bash
husks run design.json --site /tmp/site --stub
```

Run with the stub oracle.

```bash
husks run design.json --site /tmp/site --model anthropic/claude-haiku-4-5-20251001
```

Run with a live model.

```bash
husks history design.json --site /tmp/site
```

Show per-rule history and convergence summaries.

```bash
husks selftest
```

Recompute the shipped conformance vectors with the Python reader.

```bash
husks-gate "python my_reader.py" --stamp-dir verified
```

Run the conformance gate against an external CSE reader.

## Live oracles

Live oracles can read and write only through declared tools. Common tools are:

```json
["read-file", "write-file", "list-dir", "tree"]
```

Use deterministic actions for validation. A useful pattern is:

1. An `oracle` writes code or text.
2. An `action` runs tests, linting, scoring, or another deterministic check.
3. Husks seals the result only if declared outputs exist and validation succeeds.

Do not let a model grade its own output. Let the model produce artifacts. Let actions verify them.

## Conformance

Husks ships frozen conformance vectors under `spec/conformance`.

Run the built-in selftest:

```bash
husks selftest
```

Check the JavaScript reader directly:

```bash
node spec/conformance/verify.mjs spec/conformance/demo.husk \
  spec/conformance/demo.site "$(cat spec/conformance/demo.root)"
```

Run the gate against a reader command:

```bash
husks-gate "python readers/generated_reader.py" --stamp-dir readers
```

The reader command must accept:

```bash
reader <husk-file> <site-dir>
```

and print the lowercase hex build root to stdout.

## Bootstrap example

The bootstrap example asks a live oracle to write a CSE reader from the specs, then checks it with `husks-gate`.

Install live oracle support first:

```bash
pip install -e ".[llm]"
export ANTHROPIC_API_KEY=...
```

Prepare the site with the specs:

```bash
rm -rf /tmp/bootstrap-core
mkdir -p /tmp/bootstrap-core
cp spec/CSE-v1.md /tmp/bootstrap-core/CSE-v1.md
cp spec/CSE-v2.md /tmp/bootstrap-core/CSE-v2.md
```

Run the bootstrap:

```bash
husks run examples/bootstrap-core.json --site /tmp/bootstrap-core
```

A successful run writes:

```text
/tmp/bootstrap-core/readers/generated_reader.py
/tmp/bootstrap-core/readers/gate-report.txt
/tmp/bootstrap-core/readers/VERIFIED
```

and the gate report contains `GATE PASS`.

## Safety and portability rules

Keep paths relative to the site directory. Husks rejects absolute paths and `..` escapes in declared artifacts.

Keep validation deterministic. Tests, scoring scripts, formatters, and gates should be `action` rules.

Keep model calls bounded. Give every oracle a small output contract and a fuel limit.

Keep designs portable. Avoid machine-specific paths in `run` commands.

## Project status

Current capabilities:

- JSON designs with deterministic lowering into the Husks build form.
- Sealed artifact reuse with input and output hashing.
- Per-rule trace and history files.
- Stub and live oracle execution.
- Python and JavaScript CSE readers.
- Frozen positive and negative conformance vectors.
- `husks-gate` for external reader validation.
- Bootstrap example for generating and verifying a reader from the specs.

## License

Apache-2.0
