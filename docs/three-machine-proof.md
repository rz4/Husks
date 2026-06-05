# Three-Machine Proof

The verification spec for Husks beta acceptance.

## Beta acceptance target

Husks beta is reached when this workflow passes from a clean checkout
and from an installed package:

```text
Machine 1: same seed design + empty cache + oracle access
  -> builds a valid artifact
  -> reports paid oracle cost C1
  -> exports reusable residue

Machine 2: same seed design + imported cache from Machine 1 + no oracle use
  -> materializes the same or equivalent artifact
  -> reports zero paid oracle cost
  -> reports zero oracle calls
  -> reports cache reuse

Machine 3: same seed design + empty cache + oracle access
  -> independently builds a valid artifact
  -> reports paid oracle cost C3 comparable to C1
```

The proof is:

```text
Machine 2 proves reuse.
Machine 3 proves portable re-realization from the seed design.
```

Machine 3 does not receive the shared cache. It receives only the seed
design and independently realizes a valid build at comparable cost to
Machine 1.

## Beta definition

```text
Beta = seed portability
     + transactional execution
     + sealed artifact identity
     + verified cache reuse
     + independent re-realization
     + cost comparability
     + a user-runnable three-machine acceptance test
     + a small enough code path that the proof is auditable
```

## The gates

Eight gates, A–H. Each names one property that must hold.

### Gate A: Seed design portability

A seed design can move to a clean machine and build without repo-local
assumptions, hidden state, or test-only fixtures.

Exit criteria:
- A seed with relative declared site inputs builds from a clean site.
- Missing declared site inputs fail before execution.
- `husks check && husks run --stub` succeeds.
- The seed exists outside tests and is the only source of truth for
  the acceptance test.

### Gate B: Transactional execution

A build cannot corrupt the live site. Outputs commit only after
validation.

Exit criteria:
- Failed validation commits no declared outputs and writes no seal.
- Live-site bypass cannot produce a sealed success.
- Cache failures do not corrupt the transaction story.

### Gate C: Artifact identity and equivalence

Outputs can be compared and verified across machines.

Exit criteria:
- `husks compare` can compare sites.
- Invalid roots or invalid manifests fail the acceptance path with
  clear JSON.

### Gate D: Cache reuse

Machine 2 can reuse Machine 1's realized residue at zero oracle cost
without trusting unverified imported files.

Exit criteria:
- Machine 1 exports a portable cache bundle by CLI.
- Machine 2 imports it by CLI.
- Machine 2 runs with `--reuse-only`, makes no oracle calls, and
  reports reuse.
- A poisoned imported cache entry cannot materialize as a successful
  zero-cost build.

#### Commit-gate cache promotion

A killed or halted run must leave no reusable residue. Cache promotion
is staged: oracle outputs are written to a pending area during
execution and promoted to the servable cache only when the build
reaches `committed`. On `halt` or abnormal exit, the pending area is
discarded.

### Gate E: Independent re-realization

Machine 3 can build from the same seed design with an empty cache and
achieve a valid result at cost comparable to Machine 1.

Exit criteria:
- Machine 1 and Machine 3 independently build valid artifacts from
  the seed.
- Machine 3 cost is comparable to Machine 1 by explicit tolerance.
- The seed works in stub mode and has a clear live-mode path.

### Gate F: Ledger and cost comparability

Each run emits one machine-readable report proving cost, reuse,
validity, and comparability.

Exit criteria:
- `run --json` is sufficient evidence for cost, validity, reuse, and
  failure diagnosis.
- Cache reuse reports zero paid oracle calls and zero paid oracle cost.
- Failed runs still produce useful JSON.

### Gate G: Release smoke and three-machine acceptance

The beta proof can be run from a clean checkout or installed package.

Exit criteria:
- The acceptance script can be copied from docs and run.
- The CLI produces parseable JSON for every acceptance step.
- A clean wheel install can run the stub beta proof.

### Gate H: Bloat control and consolidation

Pass beta without letting the codebase accrete a second implementation
of every beta concept.

Exit criteria:
- One report contract feeds acceptance comparison.
- One cache API validates imported residue.
- One site-input helper defines seed portability.
- One beta seed is used by docs and tests.

---

## Conditional seed semantics

**Runtime Execution**: Only the selected branch executes (determined by
predicate evaluation).

**Design Identity**: Both branches are bound into the seed identity
(CSE form).

**Build Root**: Includes actual output content, so it differs when
different branches produce different outputs.

This semantic choice enables seed portability while maintaining
reproducibility:

```
Machine 1 (file exists)    ->  executes 'then' branch  ->  output A
Machine 2 (file missing)   ->  executes 'else' branch  ->  output B

Same seed design (same CSE form)
Different build outputs (different build-roots)
Both valid, both reproducible
```

The **seed design** is portable and complete. The **build outputs**
depend on the environment and predicate evaluation.

### Design identity (CSE form)

When a `cond` node is serialized to CSE, it includes the predicate
identity, the complete 'then' branch subtree, and the complete 'else'
branch subtree:

```python
[b"cond", predicate_id, then_cse, else_cse]
```

Both branches are part of the design, making it complete (all execution
paths specified), portable (the design can move between machines), and
deterministic (same design produces the same CSE hash).

### Build root (Merkle DAG)

The build-root is computed after execution and includes which branch
actually executed, the actual output content hashes, and the seals of
rules that fired. Different branches produce different outputs, so:

```
Build-root = f(design, inputs, environment, predicate_result)
```

### Three-machine conditional scenario

For the beta three-machine proof, if Machine 1 and Machine 3 take
different branches:

- Machine 1: `predicate=True` -> executes then branch -> output A
- Machine 3: `predicate=False` -> executes else branch -> output B

Expected behavior: same design (CSE hash matches), different
build-roots (outputs differ), both valid and reproducible, seed is
portable. Machine 2 uses cache from Machine 1: same design, same
branch executed (cache hit requires same recipe), same build-root
(reused outputs), zero oracle cost.

A conditional design is complete only if both branches are specified.
Missing either branch makes the design incomplete and non-portable.

---

## Live-path equivalence vocabulary

Two values, per declared output. Default is `exact` for backward
compatibility.

- `exact`: the output's content hash must match across independent
  realizations. Reserved for acceptance-bearing outputs whose content
  is a deterministic function of the artifact's verified behavior (the
  conformance digest), not a constant pass-marker.
- `free`: the output may differ across independent realizations. Not
  acceptance-bearing. Excluded from the cross-machine relation.

Validator-bounded acceptance is `exact` applied to the output that
carries the conformance digest. An `exact` mark on a constant output
is meaningless; the acceptance output must be behavioral so the mark
has content.

### Cross-machine relation

Three scoped checks replace global root identity:

1. **Cache path is deterministic.** M1 root must equal M2 root
   exactly. This preserves the guarantee that cache reuse is bitwise
   materialization.

2. **Re-realization is validator-bounded.** Build the set of
   acceptance-bearing outputs from declared `equivalence` (every
   output not marked `free`, across all rules). For each acceptance
   output, M3's hash must equal M1's hash, matched by `path`, not
   position. `free` outputs are excluded before comparison. If the
   seed declared nothing, default all outputs to `exact`.

3. **Cost comparability uses the declared tolerance.** A hard
   violation when out of bound.

An observational `convergence` block never flips `equivalent`:

```json
"convergence": {
  "m1_m3_same_root": false,
  "acceptance_outputs": ["readers/VERIFIED"],
  "acceptance_outputs_match": true,
  "free_outputs": ["readers/generated_reader.py", "readers/gate-report.txt"]
}
```

### Declaring equivalence in the seed design

An optional per-rule `equivalence` map keyed by output path. Unlisted
outputs default to `exact`. Example for `core-bootstrap`:

```json
{
  "name": "generate",
  "kind": "oracle",
  "outputs": ["readers/generated_reader.py"],
  "equivalence": { "readers/generated_reader.py": "free" }
}
```

```json
{
  "name": "validate",
  "kind": "action",
  "outputs": ["readers/gate-report.txt", "readers/VERIFIED"],
  "equivalence": {
    "readers/gate-report.txt": "free",
    "readers/VERIFIED": "exact"
  }
}
```

Constraints: `equivalence` is metadata for comparison only. It must
not enter the seal preimage or the build root. The build transaction
receives a plain string list of outputs. Do not overload `outputs`.

### Binding acceptance to behavior

The `core-bootstrap` validate rule runs the conformance gate, not just
`py_compile`. The gate stamps a conformance digest (a SHA-256 of the
reader's correct outputs on frozen vectors) instead of a constant.
The conformance digest is constant across all *correct* readers,
because the frozen `.root` values are fixed. A reader that computes a
wrong root fails the gate before any stamp is written, so it cannot
produce the digest. Two machines matching on `VERIFIED` is a real
statement of behavioral equivalence, not "both compiled."

### Declared cost tolerance

A top-level seed field:

```json
"cost_tolerance": { "ratio": [0.5, 2.0] }
```

`husks compare` reads this. If absent, default to ratio `[0.5, 2.0]`.
The bound is sourced from the seed, not from code.

---

## Live equivalence acceptance criteria

A live three-machine run (M1 live oracle, M2 cache reuse, M3 live
oracle) returns `equivalent: true`, exit 0, with divergent build roots
and matching `VERIFIED` conformance digests.

Acceptance is behavioral: `VERIFIED` carries the conformance digest,
and a reader that compiles but computes a wrong root fails the gate
and never seals.

`husks compare` enforces: M1==M2 root, M3 validator-bounded acceptance
on the conformance digest, cost within declared tolerance. It reports
M1/M3 root convergence observationally only.

The seed design states the per-output equivalence form and the cost
tolerance, satisfying white paper Section 5.

Build root is unchanged by the equivalence metadata. The `equivalence`
and `cost_tolerance` fields do not enter the seal preimage or the
build root.
