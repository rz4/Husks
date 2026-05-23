<p align="center">
  <img src="assets/logo/husks-banner.png" alt="Husks" width="900">
</p>

# Husks

**Build Husks, not vibes.**

Husks is a deterministic build calculus for nondeterministic work. 

It makes model calls inspectable from the outside by forcing them to leave sealed, content-addressed residue. The model call is an event. The Husk is what survives it.

The language gives uncertainty exactly one explicit form: `oracle`. 
Everything else is structure.

```bash
pip install -e .
husks check plan.json
husks run plan.json --site /tmp/my-build --stub
husks history plan.json --site /tmp/my-build
```

---

## 1. The Stance

A model call is an event. You do not get to inspect the event. You only get what it leaves behind.

Husks takes this literally. An `oracle` is a bounded, nondeterministic recipe. The build system never examines its internals. It does not read the model's reasoning, it does not grade its confidence, and it does not trust its account of itself. It checks the residue: the artifacts left on disk, hashed, and sealed.

Judgment is not *had* by the build. It *happens*—once—inside a bounded call. What remains is a husk: the carcass of an event that the build can inspect objectively from the outside.

Every claim the system makes is a claim about this residue:
* **A rule fired**, and these are the exact bytes it produced.
* **An oracle ran** with this prompt and this tool allowlist, and cost this much fuel.
* **An artifact is sealed**, and here is its SHA-256 hash.
* **The build committed** (or halted), and here is the reason.

The observable unit is the artifact left behind. Everything else is an event you weren't in the room for.

---

## 2. Why Not an Agent Loop?

An agent loop runs a model until the model decides it is done. The work and the judgment of the work live in the same opaque process. You see a transcript and a final state, and you are forced to trust both.

A Husk inverts the order. The plan exists as a machine-checkable contract *before* the model touches the filesystem. The full build graph, every input, output, prompt, tool, and fuel bound is explicitly declared. You review the contract. The runtime then walks it, fires only stale rules, seals fresh residue, reuses sealed residue, and emits a trace of exactly what happened.

* **The Contract Precedes the Work:** The graph is inspected before execution, not reconstructed from logs after.
* **Fuel Bounds Everything:** There is a global budget and a per-oracle budget. Unbounded loops do not exist here.
* **Residue is Reused:** A sealed artifact is never regenerated. Reruns are cheap.
* **Nondeterminism is Boxed:** It has exactly one form: `oracle`. Everything else is deterministic structure.

A plan is the contract. The plan becomes a Husk when it is lowered, sealed, and verified.

---

## 3. The Language

Husks relies on exactly nine forms, categorized by their systemic role.

| Category | Form | Function |
| :--- | :--- | :--- |
| **Structural** | `build` | Bounded top-level evaluation. |
| | `rule` | Work node with declared inputs and outputs. |
| | `let` | Shared subtrees / diamonds. |
| | `cond` | Conditional structure. |
| **Recipes** | `action` | Deterministic function. |
| | `oracle` | Bounded model call. |
| | `trial` | Speculative fork with one winner. |
| **Terminal** | `commit` | Success + value. |
| | `halt` | Failure + reason. |

### Composition Logic
* **Nesting** expresses dependency.
* **Let** expresses sharing.
* **Recipe** expresses production.
* **Commit** records accepted residue.
* **Halt** records failed residue.

---

## 4. Execution Model

The build graph owns the control flow. 

Each rule has declared inputs and outputs. Each recipe receives a bounded workspace. Each `oracle` receives an explicit tool allowlist and local fuel budget. The runtime aggressively records reads, writes, hashes, costs, timing, stale causes, reused seals, and terminal status.

A build proceeds strictly through artifacts:
`Inputs` → `Rules` → `Outputs` → `Seals` → `Trace`

---

## 5. Transport vs. Spine: JSON, Surface Lisp, and CSE

The **JSON plan** is the ergonomic input format. It names the target, fuel, rules, inputs, outputs, oracle prompts, and tools.

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
        "husks-demo/src/husks_demo/cli.py"
      ],
      "prompt": "Create a minimal Python package called husks-demo...",
      "tools": ["read-file", "write-file"],
      "fuel": 8
    }
  ]
}
```

This JSON plan lowers deterministically into the Husk AST. The AST can be rendered as a readable **Lisp-shaped surface form** for humans, but the permanent spine is much stricter: the **Canonical S-expression Encoding (CSE)**.

CSE is a byte-level serialization used purely for hashing and cryptographic verification. It uses netstring atoms and fixed positional schemas with no whitespace, no keywords, and no implementation-defined behavior. 

**True CSE (The Permanent Object):**
```text
(4:husk2:v1(5:build10:husks-demo2:30...))
```

**Readable Surface Form (For Humans):**
```hy
(build "husks-demo" 30
  (let [package
        (rule "scaffold-package"
          :inputs  []
          :outputs ["husks-demo/pyproject.toml"
                    "husks-demo/src/husks_demo/cli.py"]
          :recipe
          (oracle
            :prompt "Create a minimal Python package called husks-demo..."
            :tools  ["read-file" "write-file"]
            :fuel   8))]
    ;; ... dependent rules follow
))
```

* `let` gives the tree its shared subtrees (DAG structure).
* `trial` isolates speculative evaluation, applying a verdict to pick a winner while losing branches vanish entirely.

---

## 6. Convergence & Extraction

A plan is not written once. It is *worked*. 

You run it, read the trace, perturb the nodes that did not satisfy, pin the ones that did, and run again. Across revisions, working a plan is not tuning a build. It is **program extraction against nondeterminism**: separating the part of the task that is genuinely undetermined from the part that was determined all along.

An oracle whose output is fully determined by its inputs is not an oracle—it is transcription. The end state of a converged node is to stop being an oracle and become an `action`. 

### Reading the Descent

Husks tracks the convergence history of every node across runs.

```bash
husks history plan.json --site /tmp/husks-demo
```

This classifies the health of your rules based on fuel and prompt trends:
* **Converging:** Fuel is falling or flat; prompt is flat. Honest progress.
* **Prompt-loading (The Alarm):** Fuel is falling, but the prompt is *rising*. You are hand-migrating the deterministic work into the prompt. The cost didn't vanish; it moved from the API to your labor.
* **Stable:** Output hashes are identical across runs. The specimen is fixed. Time to convert to an `action`.
* **Volatile:** No settled trend.

The fixed point of a Husks plan is the maximal deterministic skeleton, with genuine intelligence events isolated at explicitly named, irreducible `oracle` nodes.

---

## 7. The McCarthy Version

Husks is a small evaluator over symbolic build expressions.

* `rule : Store ⇀ Store` (A partial transformation over an artifact store)
* `action : X → Y` (Deterministic)
* `oracle(prompt, tools, fuel, X) ⇝ Y` (Nondeterministic and bounded)
* `trial(branch₁, ..., branchₙ, verdict) → residue` (Speculative evaluation)

---

## 8. Quickstart

```bash
git clone [https://github.com/rz4/Husks.git](https://github.com/rz4/Husks.git)
cd Husks
python -m venv .venv
source .venv/bin/activate
pip install -e .
```

**Check a plan:**
```bash
husks check plan.json
```

**Run a plan (stub oracle, no LLM):**
```bash
husks run plan.json --site /tmp/husks-demo --stub
```

**Run it again (fresh seals skip completed work):**
```bash
husks run plan.json --site /tmp/husks-demo --stub
```

**Inspect convergence across runs:**
```bash
husks history plan.json --site /tmp/husks-demo
```

---
**License:** Apache-2.0
