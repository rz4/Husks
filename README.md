<p align="center">
  <img src="assets/logo/husks-banner-4x1.png" alt="Husks" width="900">
</p>

# Husks

**Build Husks, not vibes.**

Husks is a small build calculus for nondeterministic work.

Most agent frameworks start with a chatbot, give it tools, let it improvise, then bolt guardrails onto the chaos. Husks starts with the artifact. The model does not own control flow. The build graph does.

A model call is an `oracle`: a bounded, nondeterministic recipe inside a declared rule. The oracle receives inputs, tools, and fuel. It leaves residue on disk. Husks checks, hashes, seals, reuses, or rejects that residue.

The plan is a Husk.

Not prose. Not vibes. A build contract.

---

## What Husks does

Husks turns ambiguous work into inspected artifacts.

A build declares:

- inputs,
- outputs,
- rules,
- deterministic actions,
- bounded oracle calls,
- fuel,
- terminal targets,
- validation,
- traces.

The runtime walks the build graph. Fresh outputs are sealed and reused. Missing or stale outputs cause rules to fire. Oracle calls record prompts, tools, timing, cost, and produced artifacts. A committed build leaves a trace, not a story.

Husks makes no claim about the inner life of the model. It observes the husk: the residue left behind.

---

## The language

Nine forms.

```text
Structural
────────────────────────────────────────
build    bounded top-level evaluation
rule     work node with declared inputs and outputs
let      shared subtrees / diamonds
cond     conditional structure

Recipes
────────────────────────────────────────
action   deterministic function
oracle   bounded model call
trial    speculative fork with one winner

Terminal
────────────────────────────────────────
commit   success + value
halt     failure + reason
```

The composition rule:

```text
nesting means dependency
let means sharing
recipe means production
commit means accepted residue
halt means failed residue
```

---

## Grammar

```text
tree    := (build name fuel node ...)

node    := (rule name child ... :inputs [...] :outputs [...] :recipe recipe)
         | (let [name node ...] node ...)
         | (cond pred node ...)
         | (commit value)
         | (halt reason)

child   := node | name-ref

recipe  := (action fn)
         | (oracle :prompt str :tools [...] :fuel int)
         | (trial branch ... :verdict fn)

branch  := (oracle name :prompt str ...)
         | (action name fn)
```

A `rule` declares its contract before work begins.

An `action` performs deterministic work.

An `oracle` performs bounded nondeterministic work.

A `trial` runs candidate recipes in isolated scratch spaces, applies a verdict, and commits only the winning residue.

---

## Not an agent framework

Agent frameworks center the loop.

```text
observe → think → choose tool → act → observe
```

Husks centers the artifact.

```text
inputs → rule → outputs
```

In agent loops, the model often owns control flow. It chooses tools, invents subgoals, decides progress, and narrates completion.

In Husks, the build graph owns control flow. The model appears only inside an `oracle` recipe. It receives a bounded task and a declared output contract. It produces residue. The runtime judges the residue.

```text
agent framework:
  trust the plan

Husks:
  inspect the graph
  run the build
  read the trace
```

---

## Plan JSON

The JSON plan is the practical interchange format.

This plan builds a tiny Python CLI package. The CLI reads a text file and prints JSON with character count, word count, line count, and SHA-256 hash.

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
      "outputs": [
        "husks-demo/pyproject.toml",
        "husks-demo/src/husks_demo/__init__.py",
        "husks-demo/src/husks_demo/cli.py"
      ],
      "prompt": "Create a minimal Python package called husks-demo. It exposes a CLI command that reads a text file and prints JSON with character count, word count, line count, and SHA256 hash. Write only the declared files.",
      "tools": ["read-file", "write-file", "list-dir", "tree"],
      "fuel": 8
    },
    {
      "name": "write-tests",
      "kind": "oracle",
      "inputs": [
        "husks-demo/src/husks_demo/__init__.py",
        "husks-demo/src/husks_demo/cli.py"
      ],
      "outputs": [
        "husks-demo/tests/test_cli.py"
      ],
      "prompt": "Write pytest tests for the husks-demo CLI. Tests check valid JSON output, correct character count, word count, line count, SHA256 hash, and missing-file behavior. Write only the declared test file.",
      "tools": ["read-file", "write-file"],
      "fuel": 8
    },
    {
      "name": "write-readme",
      "kind": "oracle",
      "inputs": [
        "husks-demo/src/husks_demo/cli.py"
      ],
      "outputs": [
        "husks-demo/README.md"
      ],
      "prompt": "Write a short README for husks-demo with installation and usage examples. Write only the declared README file.",
      "tools": ["read-file", "write-file"],
      "fuel": 5
    },
    {
      "name": "run-tests",
      "kind": "action",
      "inputs": [
        "husks-demo/pyproject.toml",
        "husks-demo/src/husks_demo/__init__.py",
        "husks-demo/src/husks_demo/cli.py",
        "husks-demo/tests/test_cli.py"
      ],
      "outputs": [
        "husks-demo/test-results.txt"
      ]
    },
    {
      "name": "package-complete",
      "kind": "action",
      "inputs": [
        "husks-demo/pyproject.toml",
        "husks-demo/src/husks_demo/__init__.py",
        "husks-demo/src/husks_demo/cli.py",
        "husks-demo/tests/test_cli.py",
        "husks-demo/README.md",
        "husks-demo/test-results.txt"
      ],
      "outputs": [
        "husks-demo/.complete"
      ]
    }
  ]
}
```

The plan names the target, fuel, rules, inputs, outputs, oracle prompts, and tools. The graph exists before execution. The user sees the artifact contract before the model touches the filesystem.

The checker reads the plan and verifies:

- each rule has outputs,
- each input exists at build start or comes from an earlier rule,
- each oracle has prompt, tools, and fuel,
- total oracle fuel fits the build budget,
- the terminal target has a declared output.

---

## The same plan as Lisp

The JSON plan lowers to a Lisp-shaped build expression.

```hy
(build "husks-demo" 30

  (let [package
        (rule "scaffold-package"
          :inputs  []
          :outputs ["husks-demo/pyproject.toml"
                    "husks-demo/src/husks_demo/__init__.py"
                    "husks-demo/src/husks_demo/cli.py"]
          :recipe
          (oracle
            :prompt "Create a minimal Python package called husks-demo. It exposes a CLI command that reads a text file and prints JSON with character count, word count, line count, and SHA256 hash. Write only the declared files."
            :tools  ["read-file" "write-file" "list-dir" "tree"]
            :fuel   8))

        tests
        (rule "write-tests" package
          :inputs  ["husks-demo/src/husks_demo/__init__.py"
                    "husks-demo/src/husks_demo/cli.py"]
          :outputs ["husks-demo/tests/test_cli.py"]
          :recipe
          (oracle
            :prompt "Write pytest tests for the husks-demo CLI. Tests check valid JSON output, correct character count, word count, line count, SHA256 hash, and missing-file behavior. Write only the declared test file."
            :tools  ["read-file" "write-file"]
            :fuel   8))

        readme
        (rule "write-readme" package
          :inputs  ["husks-demo/src/husks_demo/cli.py"]
          :outputs ["husks-demo/README.md"]
          :recipe
          (oracle
            :prompt "Write a short README for husks-demo with installation and usage examples. Write only the declared README file."
            :tools  ["read-file" "write-file"]
            :fuel   5))

        test-report
        (rule "run-tests" tests
          :inputs  ["husks-demo/pyproject.toml"
                    "husks-demo/src/husks_demo/__init__.py"
                    "husks-demo/src/husks_demo/cli.py"
                    "husks-demo/tests/test_cli.py"]
          :outputs ["husks-demo/test-results.txt"]
          :recipe  (action run-pytest))

        complete
        (rule "package-complete" package tests readme test-report
          :inputs  ["husks-demo/pyproject.toml"
                    "husks-demo/src/husks_demo/__init__.py"
                    "husks-demo/src/husks_demo/cli.py"
                    "husks-demo/tests/test_cli.py"
                    "husks-demo/README.md"
                    "husks-demo/test-results.txt"]
          :outputs ["husks-demo/.complete"]
          :recipe  (action touch-complete))]

    (cond
      (valid? complete) (commit complete)
      True              (halt "package did not complete"))))
```

`package` is built once.

`tests` and `readme` share `package`.

`test-report` depends on `tests`.

`complete` depends on every required artifact.

The README cannot silently disappear from the build. The terminal rule names it as an input.

---

## Diamonds

`let` gives the tree one structural liberty: shared subtrees.

```hy
(build "train-and-deploy" 100

  (let [clean
        (rule "ingest"
          :inputs  ["raw.csv"]
          :outputs ["clean.json"]
          :recipe  (action ingest-fn))]

    (rule "deploy"

      (rule "ensemble"

        (rule "model-a" clean
          :inputs  ["clean.json"]
          :outputs ["model-a.pt"]
          :recipe
          (oracle
            :prompt "Fit a linear model."
            :tools  ["read-file" "write-file"]
            :fuel   8))

        (rule "model-b" clean
          :inputs  ["clean.json"]
          :outputs ["model-b.pt"]
          :recipe
          (trial
            (oracle "sgd"
              :prompt "SGD approach."
              :tools  ["read-file" "write-file"]
              :fuel   5)

            (oracle "adam"
              :prompt "Adam approach."
              :tools  ["read-file" "write-file"]
              :fuel   5)

            :verdict score-fn))

        :inputs  ["model-a.pt" "model-b.pt"]
        :outputs ["ensemble.pt"]
        :recipe  (action ensemble-fn))

      :inputs  ["ensemble.pt"]
      :outputs ["deploy.lock"]
      :recipe  (action deploy-fn))))
```

`clean` is bound once and referenced twice.

The first reference produces and seals `clean.json`.

The second reference reuses the seal.

A tree becomes a DAG without a global registry.

---

## Trials

A `trial` is a recipe, not a structural node.

The graph sees one rule:

```hy
(rule "model-b" clean
  :inputs  ["clean.json"]
  :outputs ["model-b.pt"]
  :recipe  ...)
```

The recipe explores candidate producers:

```hy
(trial
  (oracle "sgd"
    :prompt "SGD approach."
    :tools  ["read-file" "write-file"]
    :fuel   5)

  (oracle "adam"
    :prompt "Adam approach."
    :tools  ["read-file" "write-file"]
    :fuel   5)

  :verdict score-fn)
```

Each branch receives a scratch store. The verdict selects a winner. The winning branch contributes the declared outputs. The losing branches vanish.

The uncertainty stays inside the recipe.

The graph remains stable.

---

## Trace

A Husk build prints the residue trail.

```text
════════════════════════════════════════════════════════════
  husks-demo
  site  /tmp/husks-demo
  fuel  30    oracle  anthropic/claude-haiku
════════════════════════════════════════════════════════════

  ▸ scaffold-package
    stale: husks-demo/pyproject.toml missing
    → oracle  "Create a minimal Python package called husks-demo..."
    → write-file  husks-demo/pyproject.toml
      ok
    → write-file  husks-demo/src/husks_demo/__init__.py
      ok
    → write-file  husks-demo/src/husks_demo/cli.py
      ok
      6.0k in · 1.0k out · $0.0112 · 9.17s
  ✓ scaffold-package  9.17s

  ● scaffold-package  reused by write-tests

  ▸ write-tests
    stale: husks-demo/tests/test_cli.py missing
    → oracle  "Write pytest tests for the husks-demo CLI..."
    → read-file   husks-demo/src/husks_demo/__init__.py
    → read-file   husks-demo/src/husks_demo/cli.py
    → write-file  husks-demo/tests/test_cli.py
      ok
      6.3k in · 1.2k out · $0.0122 · 8.49s
  ✓ write-tests  8.49s

  ▸ run-tests
    stale: husks-demo/test-results.txt missing
    → action run-pytest
      ok
  ✓ run-tests

  ▸ package-complete
    stale: husks-demo/.complete missing
    → action touch-complete
      ok
  ✓ package-complete

  sealed artifacts
    husks-demo/pyproject.toml                 dbed9ae5bd
    husks-demo/src/husks_demo/__init__.py     e810387f86
    husks-demo/src/husks_demo/cli.py          905042c9a8
    husks-demo/tests/test_cli.py              907e46cac3
    husks-demo/test-results.txt               76b8124b2e
    husks-demo/README.md                      8fe274b10a
    husks-demo/.complete                      31bc1a9418

────────────────────────────────────────────────────────────
  committed  29.72s
────────────────────────────────────────────────────────────
  nodes     5 fired · 1 reused
  artifacts 7 sealed · 7 new
  oracle    3 calls · 21.7k in · 3.7k out · $0.0401
  tools     10 calls
  fuel      27/30
────────────────────────────────────────────────────────────
```

The trace records:

- stale causes,
- fired rules,
- reused rules,
- oracle calls,
- tool calls,
- action checks,
- sealed artifacts,
- artifact hashes,
- cost,
- fuel,
- wall time.

The model does not summarize success. The trace shows the work.

---

## Seals

A seal records:

- rule name,
- declared inputs,
- input hashes,
- declared outputs,
- output hashes,
- recipe specification,
- oracle model and cost,
- tool calls,
- timing,
- trial verdicts.

Seals make reruns cheap.

```text
● scaffold-package  sealed
```

This is not chatbot memory.

This is artifact memory.

---

## McCarthy version

Husks is a small evaluator over symbolic build expressions.

The central expression:

```text
(build name fuel node ...)
```

A rule is a partial transformation over an artifact store:

```text
rule : Store ⇀ Store
```

An action is deterministic:

```text
action : X → Y
```

An oracle is nondeterministic and bounded:

```text
oracle(prompt, tools, fuel, X) ⇝ Y
```

A trial is isolated speculative evaluation:

```text
trial(branch₁, ..., branchₙ, verdict) → winning residue
```

Evaluation consumes fuel and terminates by `commit` or `halt`.

The model receives no metaphysical privilege. The language gives uncertainty one explicit form: `oracle`.

Everything else is structure.

---

## Quickstart

```bash
git clone https://github.com/rz4/Husks.git
cd Husks
python -m venv .venv
source .venv/bin/activate
pip install -e .
```

Check a plan:

```bash
python -m husks.cli check plan.json
```

Show a plan:

```bash
python -m husks.cli show plan.json
```

Run a plan:

```bash
python -m husks.cli run plan.json --site /tmp/husks-demo
```

Run it again:

```bash
python -m husks.cli run plan.json --site /tmp/husks-demo
```

Fresh seals skip completed work.

---

## License

Apache-2.0.
