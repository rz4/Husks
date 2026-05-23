<p align="center">
  <img src="assets/logo/husks-banner.png" alt="Husks" width="900">
</p>

# Husks

**Build Husks, not vibes.**

Husks is a deterministic build calculus for nondeterministic work.

A model call is an event. You were not in the room. You do not get the event — you get what it leaves behind, and Husks forces it to leave something you can hold: sealed, content-addressed residue. The call is the event. The husk is the carcass.

The language gives uncertainty exactly one form: `oracle`. Everything else is structure.

---

## Quickstart

```bash
git clone https://github.com/rz4/Husks.git
cd Husks
python -m venv .venv
source .venv/bin/activate
pip install -e .
```

Check a plan against its contract:

```bash
husks check plan.json
```

Run it with a stub oracle — no model, no key, just the machinery:

```bash
husks run plan.json --site /tmp/husks-demo --stub
```

Run it again. Fresh seals skip work already done:

```bash
husks run plan.json --site /tmp/husks-demo --stub
```

Read how a node has moved across runs:

```bash
husks history plan.json --site /tmp/husks-demo
```

---

## 1. The stance

Intelligence is not *had* by a system. It *happens* — once, inside a bounded call — and the moment you go looking for it, it is already over. What you can examine is never the event. It is the residue: the carcass of an event you arrived too late to witness.

Husks takes that literally and refuses to pretend otherwise. An `oracle` is a bounded, nondeterministic recipe whose insides the build never opens. It does not read the model's reasoning. It does not grade the model's confidence. It does not trust the model's account of itself. It checks the bytes left on disk — hashed, sealed, and inspectable from the outside, where you actually are.

So every claim the system makes is a claim about residue, and nothing else:

- a rule fired, and these are the exact bytes it produced;
- an oracle ran with this prompt and this allowlist, and spent this much fuel;
- this artifact is sealed, and here is its hash;
- the build committed, or it halted, and here is the reason.

The observable unit is the thing left behind. Everything upstream of it is an event you weren't in the room for, and the framework will not let you talk as if you were.

---

## 2. Why not an agent loop

An agent loop runs a model until the model decides it is finished. The work and the judgment of the work happen in the same opaque pass, and at the end you are handed a transcript and a final state and asked to trust both. You are trusting the event to grade its own carcass.

A Husk reverses the order. The plan is a contract that exists *before* the model touches anything: the whole graph — every input, output, prompt, tool, and fuel bound — written down where you can read it. You review the contract. Then the runtime walks it, fires only what is stale, seals what is fresh, reuses what is already sealed, and prints exactly what happened.

The contract precedes the work; it is not reconstructed from logs afterward. Fuel bounds everything — a global budget and a budget per oracle — so there are no unbounded loops to wait out. Sealed residue is never regenerated, which makes reruns nearly free. And nondeterminism has exactly one home: `oracle`. The rest is deterministic structure you can reason about.

A plan is the contract. It becomes a Husk when it is lowered, sealed, and verified.

---

## 3. The language

Nine forms. That is the whole language.

| Category | Form | Function |
| :--- | :--- | :--- |
| **Structural** | `build` | Bounded top-level evaluation. |
| | `rule` | A work node with declared inputs and outputs. |
| | `let` | Shared subtrees — the diamonds in the DAG. |
| | `cond` | Conditional structure. |
| **Recipes** | `action` | Deterministic function. |
| | `oracle` | Bounded model call. The one source of uncertainty. |
| | `trial` | Speculative fork; one winner survives. |
| **Terminal** | `commit` | Accepted residue. |
| | `halt` | Failed residue, with a reason. |

Nesting expresses dependency. `let` expresses sharing. A recipe expresses production. `commit` and `halt` record which residue was kept and which was thrown away. You start with two — `action` and `oracle` — and reach for the rest only when the shape of the work demands it.

---

## 4. Execution model

The graph owns control flow. Each rule declares its inputs and outputs up front. Each recipe runs in a bounded workspace. Each oracle gets an explicit tool allowlist and its own local fuel. As it walks, the runtime records reads, writes, hashes, cost, timing, what was stale and why, what was reused, and how it ended.

A build moves through artifacts, in one direction:

```text
inputs → rules → outputs → seals → trace
```

The target names completion. Reach it and the build commits; fail to and it halts. There is no third outcome.

---

## 5. Transport and spine

There are two ways to hold a Husk, and they are not the same kind of thing.

**The transport** is what you author. JSON, because it is ergonomic and every tool already speaks it. It names the target, the fuel, the rules, and for each oracle its prompt and tools:

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

This lowers deterministically into an AST. The walk that performs the lowering imposes a fixed order on everything, so two plans that mean the same thing produce the same structure — canonicalization happens here, once, where the full graph is still in view. For human eyes the AST renders as a Lisp surface form:

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
    ;; dependent rules follow
    ))
```

**The spine** is what survives. Underneath the JSON and the surface Lisp is the Canonical S-expression Encoding — the byte-level form that gets hashed, and the only form that matters for verification or for replay by a reader written long after this engine is gone. CSE is not for authoring. It is netstring atoms — `<length>:<bytes>`, no leading zeros — in fixed positional schemas, with no whitespace, no keywords, and no implementation-defined behavior anywhere. The conformance demo begins:

```text
(4:husk1:1(5:build4:demo2:10(4:rule7:combine...)))
```

The transport is allowed to change. New input dialects, new conveniences, new languages — all fine, because they regenerate. The spine is frozen and append-only: CSE v1 is fixed forever, and a future v2 never edits it, it sits beside it. JSON is the airport announcement. The s-expression is the document.

---

## 6. The seal, and why a husk outlives its engine

A seal is content, never instrumentation. For each node it is a hash over the recipe and the hashes of the inputs:

```text
seal = SHA256( CSE( (4:seal <version> <recipe-digest> <input-bindings>) ) )
```

Note what is **not** in there: the model, the cost, the token counts, the wall-clock time, the name of whatever answered. Those are provenance — a lab notebook beside the specimen — and they are recorded, but they are advisory and they are never sealed. A husk must verify identically whether its oracle ran on a model from 2026 or on something unimaginable a decade later. **The seal records what was asked and what came back. It never records who answered.**

The seal does not key on the oracle's output, because the output cannot be predicted — that is what makes it an oracle. Sealing freezes the *first* residue an event produced. Rerunning does not re-enter the event; it reuses the husk. The only act that re-fires a sealed oracle is editing its recipe, and editing the recipe is precisely what changes the seal.

Nodes hash their seal, their outputs, and their children's digests, so a build is a Merkle DAG and its root is one hash over the whole thing. A subtree shared by `let` is hashed once — the diamond is literally a shared hash. Clone a repo and you inherit the sealed residue; the expensive calls are already paid for.

And here is the test the whole design exists to pass. Throw the engine away. A small reader in a language that did not exist when the husk was sealed, given only the bytes and the inputs, must arrive at the same root. The repo ships two independent readers — `core.py` in Python and `verify.mjs` in JavaScript — and a frozen conformance vector. They agree on the root. If they ever stopped agreeing, the permanence was a story we were telling ourselves. They don't, so it isn't.

```bash
node spec/conformance/verify.mjs spec/conformance/demo.husk \
     spec/conformance/demo.site "$(cat spec/conformance/demo.root)"
```

---

## 7. Convergence and extraction

A plan is not written once. It is *worked*. You run it, read the trace, perturb the nodes that didn't satisfy, pin the ones that did, and run again. Across revisions this is not tuning a build. It is **program extraction against nondeterminism** — pulling apart the part of a task that is genuinely undetermined from the part that was determined all along and only wore the costume of judgment.

An oracle whose output is fixed by its inputs is not an oracle. It is transcription, and transcription is a deterministic `action` you have not extracted yet. The prompt is source code for a function; leaving it as an oracle pays an API call to interpret that function at runtime. The end state of a converged node is to stop being an oracle.

`husks history` classifies how a node has moved:

- **Converging** — fuel falling or flat, prompt flat. Honest progress; the node is settling toward its minimal form and may be ready to become an action.
- **Prompt-loading** — fuel falling, prompt *rising*. The alarm. Falling fuel looks like progress, but a swelling prompt means you are hand-migrating the determined part of the work into the prompt and then paying the oracle to read your own work back. The cost did not leave. It moved from the API bill to your hands.
- **Stable** — output hashes identical across runs. The specimen is fixed. Make it an action.
- **Volatile** — no settled trend. Not converged.

The fixed point you are working toward is the maximal deterministic skeleton with the genuine events isolated at named, irreducible `oracle` nodes — the parts that truly could not be written down in advance. Because anything that *could* be written down should have been the deterministic operation it was pretending not to be.

---

## 8. The McCarthy version

Husks is a small evaluator over symbolic build expressions.

```text
rule   : Store ⇀ Store                          partial transformation over an artifact store
action : X → Y                                   deterministic
oracle : (prompt, tools, fuel, X) ⇝ Y            nondeterministic, bounded
trial  : (branch₁, …, branchₙ, verdict) → Y      speculative; one residue survives
```

Evaluation consumes fuel and terminates by `commit` or `halt`. The language gives uncertainty one explicit form. Everything else is structure.

---

## The claim, stated so it can be wrong

A husk has object permanence when its verifier can be produced as residue, the producing event discarded, and the result confirmed by a reader that is not it. The cross-language readers and the frozen root are the first form of that proof. The sharpest form — having the framework emit its own verifier through an oracle and checking that residue against the bedrock — is a test the project sets for itself and has not yet passed. It is being built. When it passes, the claim stands on something colder than rhetoric. Until then it is a claim, and it is written here so you can hold it to account.

---

**License:** Apache-2.0
