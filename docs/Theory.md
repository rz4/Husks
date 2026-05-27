# Theory

## 1. The stance

Husks rests on a deliberate methodological choice, not a claim about cognition: treat a model call as an opaque event and verify only what it leaves behind. Whatever one believes about whether a system "has" intelligence, you cannot inspect the call as it happens — by the time you examine anything, the event is over and what you hold is its residue. Husks takes that posture as far as it will go and builds the rest of the system on it.

Husks takes that literally and refuses to pretend otherwise. An `oracle` is a bounded, nondeterministic recipe whose insides the build never opens. It does not read the model's reasoning. It does not grade the model's confidence. It does not trust the model's account of itself. It checks the bytes left on disk — hashed, sealed, and inspectable from the outside, where you actually are.

So every claim the system makes is a claim about residue, and nothing else:

- a rule fired, and these are the exact bytes it produced;
- an oracle ran with this prompt and this allowlist, and spent this much fuel;
- this artifact is sealed, and here is its hash;
- the build committed, or it halted, and here is the reason.

The observable unit is the thing left behind. The framework records only what it observed of that residue, so any claim that goes beyond it is visibly yours, not the system's — the system never vouches for the event it did not see.

---

## 2. Why not an agent loop

An agent loop runs a model until the model decides it is finished. The work and the judgment of the work happen in the same opaque pass, and at the end you are handed a transcript and a final state and asked to trust both. You are trusting the event to grade its own carcass.

A Husk reverses the order. The design is a contract that exists *before* the model touches anything: the whole graph — every input, output, prompt, tool, and fuel bound — written down where you can read it. You review the contract. Then the runtime walks it, fires only what is stale, seals what is fresh, reuses what is already sealed, and prints exactly what happened.

The contract precedes the work; it is not reconstructed from logs afterward. Fuel bounds everything — a global budget and a budget per oracle — so there are no unbounded loops to wait out. Sealed residue is never regenerated, which makes reruns nearly free. And nondeterminism has exactly one home: `oracle`. The rest is deterministic structure you can reason about.

A design is the contract. It becomes a Husk when it is lowered, sealed, and verified.

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

This lowers deterministically into an AST. The walk that performs the lowering imposes a fixed order on everything, so two designs that mean the same thing produce the same structure — canonicalization happens here, once, where the full graph is still in view. For human eyes the AST renders as a Lisp surface form:

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

Nodes hash their seal, their outputs, and their children's digests, so a build is a Merkle DAG and its root is one hash over the whole thing. A `let`-shared subtree is hashed once, so shared structure is identical by construction — the diamond is one digest, not two that happen to match. Clone a repo and you inherit the sealed residue; the expensive calls are already paid for.

Call a husk *permanent* in this operational sense: its root is reproducible from the bytes and inputs alone, by any conforming reader, with no access to the engine that produced it. That is a property you can test, not a quality you assert — and here is the test the whole design exists to pass. Throw the engine away. A small reader in a language that did not exist when the husk was sealed, given only the bytes and the inputs, must arrive at the same root. The repo ships two independent readers — `core.py` in Python and `verify.mjs` in JavaScript — and a frozen conformance vector. They agree on the root. If they ever stopped agreeing, the permanence claim would be false; they don't, so as far as it has been tested, it holds.

```bash
node spec/conformance/verify.mjs spec/conformance/demo.husk \
     spec/conformance/demo.site "$(cat spec/conformance/demo.root)"
```

A third reader has since joined those two — written from cold by a model that had only the spec, and never the other two. That is the end of this story, and it belongs at the end.

---

## 7. Conformance

Verification is only as strong as what you test it against. The repo ships a frozen conformance demo and an adversarial fixture, and the adversarial one is nasty on purpose — filenames and byte patterns that a casual JSON, regex, or whitespace parser will mishandle, because the only reader that survives them is one that honors the length prefix and reads exactly the bytes it is told to. Two more fixtures must be *rejected*, not parsed: `malformed-leadingzero.husk` and `malformed-truncated.husk`.

A reader clears Level 0 when all five hold:

1. it computes the frozen demo root;
2. it computes the frozen adversarial root;
3. it rejects the leading-zero input;
4. it rejects the truncated input;
5. it agrees with the independent JavaScript reader.

Anything less is a reader that works on the easy cases and lies on the hard ones. The point of the adversarial fixture is to make lying expensive: a parser that takes shortcuts produces a different root, and a different root is a failure you can see.

---

## 8. Bootstrap validation

`examples/bootstrap-core.json` turns that test on the framework itself. It has two nodes. An `oracle` reads CSE v1 and v2 — and nothing else; no existing reader, no answer key — and writes a dependency-free Python reader to `readers/generated_reader.py`. Then a deterministic gate, `husks_conformance.gate`, judges that reader against the five criteria above. Pass, and the gate writes `readers/VERIFIED`. Fail, and the build halts with the reason.

The shape is the whole thesis in miniature: the oracle produces, the gate verifies, and the gate is not the oracle. A model can write the verifier; it cannot grade its own verifier. The frozen roots do that — and the roots were computed by readers the model never saw. What happened the first time we ran this is at the end of the document, because it is the point of the whole exercise.

---

## 9. Convergence and extraction

A design is not written once. It is *worked*. You run it, read the trace, perturb the nodes that didn't satisfy, pin the ones that did, and run again. Across revisions this is not tuning a build. It is **program extraction against nondeterminism** — separating the part of a task you have managed to reduce to a deterministic rule from the part that has, so far, resisted that reduction.

An oracle whose output is fixed by its inputs is not an oracle. It is transcription, and transcription is a deterministic `action` you have not extracted yet. The prompt is source code for a function; leaving it as an oracle pays an API call to interpret that function at runtime. The end state of a converged node is to stop being an oracle.

`husks history` classifies how a node has moved:

- **Converging** — fuel falling or flat, prompt flat. Honest progress; the node is settling toward its minimal form and may be ready to become an action.
- **Prompt-loading** — fuel falling, prompt *rising*. The alarm. Falling fuel looks like progress, but a swelling prompt means you are hand-migrating the determined part of the work into the prompt and then paying the oracle to read your own work back. The cost did not leave. It moved from the API bill to your hands.
- **Stable** — output hashes identical across runs. The specimen is fixed. Make it an action.
- **Volatile** — no settled trend. Not converged.

The fixed point you are working toward is the maximal deterministic skeleton, with the remaining oracle nodes naming the parts that have so far resisted reduction to a deterministic action. That residue is empirical, not metaphysical: it marks what you have not yet extracted, not what is provably impossible to extract. Anything you *can* reduce should become the deterministic operation it was standing in for; what is left is simply where, for now, reduction has stopped.

---

## 10. The McCarthy version

Husks is a small evaluator over symbolic build expressions.

```text
rule   : Store ⇀ Store                          partial transformation over an artifact store
action : X → Y                                   deterministic
oracle : (prompt, tools, fuel, X) ⇝ Y            nondeterministic, bounded
trial  : (branch₁, …, branchₙ, verdict) → Y      speculative; one residue survives
```

Evaluation consumes fuel and terminates by `commit` or `halt`. The language gives uncertainty one explicit form. Everything else is structure.

This is an informal operational account, not a worked-out formal semantics. The reduction relation, a termination argument from the fuel bound, and any soundness statement relating seals to the artifacts they certify are not yet written down. "Calculus" here names the intent and the shape, not a completed formalization — that is work this document does not claim to have done.

---

## The claim, held to account

A husk has object permanence when its verifier can be produced as residue, the producing event discarded, and the result confirmed by a reader that is not it. The cross-language readers and the frozen root are the first form of that proof. The sharpest form is harder: hand a model nothing but the spec, have it write a CSE reader from cold, and check whether that reader — which has never seen the engine, the shipped readers, or the answer — arrives at the same root hashes the bedrock already holds.

We ran it. A small, cheap model, given only CSE v1 and v2, wrote a netstring parser, a seal preimage, and a Merkle node digest, and reproduced both frozen roots — `demo` at `9977239d…` and an adversarial fixture, built to break lazy parsers, at `5382838c…`. It rejected two malformed husks and agreed with the independent JavaScript reader. Judged by readers that are not it. Three cents, one call, twenty-five seconds.

It did not pass on the first run, and that is the part worth reading. The first cold reader disagreed by a definite hash, and the disagreement located a real hole: the spec described how the *elaborator* orders a node's children, and a faithful reader implemented that as a verification rule, which it is not. A second gap surfaced next — whether a digest enters a parent form as a hex string or as raw bytes. Both were holes a careful independent implementer would also have fallen into. We closed them in CSE v2 and ran again, cold. Then it clicked into the bedrock.

That is the whole point of writing a claim so it can be wrong. The format was held to account by something with every reason to disagree, and the disagreement made it more precise rather than less true — two ambiguities in the permanent layer, found and closed, by the act of being checked.

Deeper forms of the test remain: a Husk that emits its own verifier as residue, a Husk that emits the design that builds Husks. Those are not done. The first and sharpest one is.
