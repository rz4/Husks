<p align="center">
  <img src="assets/logo/husks-banner.png" alt="Husks" width="900">
</p>

# Husks

**Build Husks, not vibes.**

Husks is a small build calculus for nondeterministic work.

```bash
pip install -e .
husks check plan.json
husks run plan.json --site /tmp/my-build --stub
husks history plan.json --site /tmp/my-build
```

---

## The stance

A model call is an event. You do not get to inspect the event. You get what it leaves behind.

Husks takes that literally. An `oracle` is a bounded, nondeterministic recipe whose internals the build never examines. The build does not read the model's reasoning, does not grade its confidence, does not trust its account of itself. It checks the residue: the artifacts left on disk, hashed and sealed.

Judgment is not *had* by the build. It *happens*, once, inside a bounded call, and what remains is a husk: the carcass of an event the build can inspect from the outside.

So every claim the system makes is a claim about residue:

- a rule fired, and these are the bytes it produced,
- an oracle ran with this prompt and this tool allowlist, and cost this much,
- this artifact is sealed, and here is its hash,
- the build committed, or it halted, and here is the reason.

The observable unit is the artifact left behind. Everything else is an event you weren't in the room for.

---

## Why not an agent loop

An agent loop runs the model until it decides it is done. The work and the judgment of the work live in the same opaque process. You see a transcript and a final state, and you trust both.

A Husk inverts the order. The plan exists as a machine-checkable contract *before* the model touches the filesystem: the full build graph, every input, output, prompt, tool, and fuel bound. You review the contract. The runtime then walks it, fires only stale rules, seals fresh residue, reuses sealed residue, and emits a trace of exactly what happened.

- **The contract precedes the work.** The graph is inspected before execution, not reconstructed from logs after.
- **Fuel bounds everything.** A global budget and a per-oracle budget. No unbounded loops.
- **Residue is reused.** A sealed artifact is not regenerated. Reruns are cheap.
- **Nondeterminism has exactly one form.** `oracle`. Everything else is deterministic structure.

The plan is a Husk: a build contract you can read, edit, and re-run.

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

Composition:

```text
nesting expresses dependency
let expresses sharing
recipe expresses production
commit records accepted residue
halt records failed residue
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

A `trial` runs candidate recipes in isolated scratch spaces, applies a verdict, and commits the winning residue.

---

## Execution model

The build graph owns control flow.

Each rule has declared inputs and outputs. Each recipe receives a bounded workspace. Each oracle receives an explicit tool allowlist and local fuel budget. The runtime records reads, writes, hashes, cost, timing, stale causes, reused seals, and terminal status.

A build proceeds through artifacts:

```text
inputs → rules → outputs → seals → trace
```

The terminal target names completion.

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

The plan names the target, fuel, rules, inputs, outputs, oracle prompts, and tools. The graph exists before execution. The user reviews the artifact contract before the model touches the filesystem.

The plan may declare `"site_inputs"`, a list of paths that exist on the site before the build starts. The checker treats site inputs as pre-produced, so rules may declare them as inputs without a prior rule producing them.

```json
{
  "name": "my-build",
  "fuel": 20,
  "target": "process",
  "site_inputs": ["raw-data.csv", "config.yaml"],
  "rules": [
    {
      "name": "process",
      "kind": "action",
      "inputs": ["raw-data.csv", "config.yaml"],
      "outputs": ["output.json"]
    }
  ]
}
```

The checker verifies:

- each rule has outputs,
- each input exists as a site input or comes from an earlier rule,
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

The terminal rule names every artifact required for completion.

---

## Diamonds

`let` gives the tree shared subtrees.

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

A tree gains DAG structure through lexical binding.

---

## Trials

A `trial` is a recipe.

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

Each branch receives a scratch store. The default strategy (`first-valid`) picks the first non-errored branch and notes in the trace when it chose arbitrarily among multiple survivors. Supply a custom `:verdict` function for deliberate selection. The winning branch contributes the declared outputs. The losing branches vanish.

The graph remains stable. The uncertainty stays inside the recipe.

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

The trace shows the work.

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

This is artifact memory.

A seal keys on the recipe specification (the prompt, the sorted tool allowlist, the fuel) and the per-input hashes. It does not key on the oracle's output, because the oracle is nondeterministic and its output cannot be predicted. Sealing therefore freezes the *first* residue an event produced. Re-running does not re-enter the event; it reuses the husk. The one act that re-fires a sealed oracle is editing its recipe, and editing the recipe is what changes the seal key.

---

## Convergence and extraction

A plan is not written once. It is worked.

You run it, read the trace, perturb the nodes that did not satisfy, pin the ones that did, and run again. Across revisions, working a plan is not tuning a build. It is **program extraction against nondeterminism**: separating the part of the task that is genuinely undetermined from the part that was determined all along and only looked like judgment.

Two facts make this precise.

**An oracle whose output is determined by its inputs is not an oracle.** If a node always produces the same residue from the same inputs, it is transcribing, not judging. Transcription is a deterministic `action` you have not extracted yet. The prompt is source code for a function. Leaving it as an oracle pays an API call to interpret that function at runtime. The end state of a converged node is to stop being an oracle and become an action.

**Satisfaction is exogenous.** Whether a residue is good is judged from outside the event: by a downstream `action` gate that validates it, by a `trial` verdict that selects among candidates, or by you. An oracle cannot certify its own residue: that would be the event grading its own carcass, which is the one move the framework forbids. So validation is always a deterministic action; oracles produce, actions verify.

### The log

Each rule records a per-node convergence history at `.traces/<rule-name>.history.jsonl`. One JSONL record per fire:

```json
{
  "run_id": "uuid",
  "ts": 1716300000.0,
  "fuel_consumed": 1,
  "prompt_length": 342,
  "satisfaction": null,
  "traced_reads": ["clean.json", "config.yaml"],
  "output_hashes": ["a1b2c3..."]
}
```

Fields:

- `run_id`: unique per build invocation.
- `fuel_consumed`: local fuel this rule burned. Lower means the event was more tightly pinned: fewer tool calls, less groping for context.
- `prompt_length`: `len(prompt)` for oracles, `null` for actions.
- `satisfaction`: `true` (trial winner, gate pass), `false` (trial loser, gate throw), `null` (nobody looked). `null` is honest: it means unexamined, not fine.
- `traced_reads`: file paths the rule's tool calls actually read.
- `output_hashes`: SHA-256 of declared outputs at seal time.

### Reading the descent

```bash
python -m husks.cli history plan.json scaffold-package --site /tmp/husks-demo
python -m husks.cli history plan.json --site /tmp/husks-demo
```

`convergence_summary(rule, site, n)` classifies the last N runs of a node from its fuel trend, prompt-length trend, and output stability:

- **converging**: fuel falling or flat, prompt flat or falling. Honest progress: the node is settling toward its minimal form, and may be a candidate to extract into an `action`.
- **prompt-loading**: fuel falling, prompt *rising*. The alarm. Falling fuel looks like progress, but a growing prompt means you are hand-migrating the determined part of the computation into the prompt, one revision at a time, doing the extraction with your fingers and then paying the oracle to read your work back. The cost did not leave; it moved from the API bill to your labor.
- **stable**: output hashes identical across runs. The residue is fixed. Strong signal the node has become deterministic and should be an action.
- **volatile**: no settled trend. The node has not converged.

`declared_vs_traced(plan, site)` diffs each rule's declared inputs against its traced reads. An oracle reaching for paths the plan did not declare is not an error (the tool layer enforces site containment, so all reads are structurally bounded to the site root), but it is a signal: the contract and the residue have diverged, and the plan is due for its next revision. The gap between what you declared and what the event touched is the diagnostic for where the plan has not yet converged.

### The fixed point

The thing you are converging toward is a plan whose every remaining oracle carries irreducible nondeterminism, and everything else is deterministic action: the **maximal deterministic skeleton with the genuine events isolated at named nodes**. A node that has sealed and not re-fired across many runs, with one-fuel completion and no traced reads, has become determined, so it should be an action. What is left as an oracle is only the judgment that genuinely could not be written down in advance. Because if it could be written down, writing it down is the deterministic operation it should have been replaced by.

There is a floor. Past a point, driving an oracle's fuel to one is no longer efficiency. It is you absorbing the nondeterminism into the prompt until the oracle is transcribing. The efficient point is the lowest fuel at which the oracle is still doing the judgment you actually meant to delegate. Below that, the event has nothing left to be.

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

The language gives uncertainty one explicit form: `oracle`.

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
husks check plan.json
```

Show a plan:

```bash
husks show plan.json
```

Run a plan (stub oracle, no LLM):

```bash
husks run plan.json --site /tmp/husks-demo --stub
```

Run it again — fresh seals skip completed work:

```bash
husks run plan.json --site /tmp/husks-demo --stub
```

Inspect convergence across runs:

```bash
husks history plan.json --site /tmp/husks-demo
```

---

## License

Apache-2.0.
