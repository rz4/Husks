# Gas Gamma: design plan

Status: design. Target: a new operating mode for Husks. Author voice: declarative.

## 0. Where gamma sits

Alpha, beta, and gamma are statuses of Husks, the project. Each names a
capability the system demonstrates over a design. They are not states an
individual husk is in, and the matter metaphor (solid, liquid, gas) is only a
mnemonic for the progression, not a property of any artifact.

- Alpha: Husks can hydrate a husk for CSE from dry. The sealed residue
  reconstructs its own canonical form. Permanence.
- Beta (current): the same design passes the three-machine proof. Independent
  re-realization agrees. Reproduction.
- Gamma (this plan): Husks can condense a design from an open pilot run. A run
  that began with no design at all yields one. In-flight authorship.

The key property of gamma is that it is recursive on the prior two statuses, and
adds no new verification. An open pilot run has no design up front. Gamma is the
capability to extract one from the run. A condensed design is valid only if it
then clears alpha and beta: it hydrates dry to CSE, and it passes the
three-machine proof, producing the output the run accepted. Gamma is the
authoring status. Alpha and beta are the verification statuses it must feed.

So gamma removes beta's straitjacket, that the success condition must be declared
before it is known, by splitting the work in time. First an open run forms a
hypothesis through costly, wasteful exploration. Then condensation extracts a
design from it, and alpha plus beta certify the subset that hydrates and
reproduces. Nothing about how a husk is verified changes. Only where the design
came from.

## 1. Goals and non-goals

Goals.
- Let a piloted agent explore with full freedom, sealing nothing during search.
- Convert an exploration session into a set of small, independently verifiable
  husks, each reproducible from declared inputs alone.
- Preserve every beta integrity guarantee. A gamma husk is verifiable by the
  same readers, with no weaker contract.
- Trust the session for nothing. The transcript is disposable.

Non-goals.
- Recording or replaying what the agent did. Gamma seals declarations, not
  transcripts.
- Making oracle output deterministic. Gamma certifies the honest weaker claim
  for model-mediated steps.
- Automating the decision to seal. Condensation is an explicit act of authorship.

## 2. The central invariant

One rule the whole mode hangs on, to be quoted verbatim to any agent or
contributor who touches gamma:

> A husk is a declaration that passed its gates, even when authored in flight.
> Condensation runs the gate cold. It never snapshots the session. The day a
> seal contains the transcript, gamma is dead and you have built a recorder.

Everything below is mechanism in service of this rule.

## 3. Conceptual model

- Vapor: the live exploration. Reads, edits, commands, dead ends. High entropy,
  trusted for nothing, sealed by nothing.
- Condensation: extracting a candidate design from the run and certifying it by
  alpha and beta plus the warm anchor. Pass yields a droplet. Fail returns to
  vapor.
- Droplet: a sealed husk. A condensed design that hydrated, reproduced, and
  matched what the pilot accepted.
- Envelope: the session container, a working site holding the agent, the pilot,
  and the accumulating droplets.
- Evaporation: session end. The transcript is discarded. The condensate, a graph
  of droplets, persists and is independently replayable.

## 4. Condensation and certification (no new primitive)

Gamma adds no new way to verify a husk. It adds a way to produce a design from an
open run and then subjects that design to alpha and beta unchanged. Condensation
is two acts: extract a candidate design, then certify it with the existing
statuses plus a warm anchor.

### 4.1 Extraction

An open pilot run starts with no design. The extractor (section 7) reads the run
and drafts a candidate design: `site_inputs`, rules, outputs, target. Extraction
is the authoring act and the substance of gamma. It is allowed to be imperfect,
because a bad design fails certification and forms no husk.

### 4.2 Certification by alpha and beta

A candidate design is certified by running the two prior statuses against it. No
third gate.

- Alpha (hydration): the candidate seals and hydrates dry to its CSE. The
  residue reconstructs its own canonical form. Reuse the existing seal and
  `recompute_root` path.
- Beta (three-machine proof): the same candidate passes reproduction. Reuse the
  existing harness, do not build a new comparator.
  - M1: fresh build in a clean store from declared inputs only.
  - M2: cache reuse of M1 (export, import, `--reuse-only`).
  - M3: independent fresh build from declared inputs only.
  - Primitive: `husks compare M1 M2 M3 --json` reports `proof.satisfied`.

The clean store carries only the declared `site_inputs`. Wall-clock and network
are denied unless declared. Reuse the oracle sandbox's denial path. A candidate
that leaned on a file created during the run, or on ambient env, fails beta
because the clean room does not have it. So an honest design hydrates and
reproduces; a design that smuggled session state does neither.

### 4.3 The warm anchor

Alpha and beta together prove the candidate is permanent and reproducible. They
do not prove it produces what the pilot accepted. The open run happened with
session debris present and is not one of M1, M2, M3, so the cold machines can
agree with each other on a reproducibly-wrong result that diverges from the
accepted one. Condensation therefore captures the accepted result as a fourth
reference and requires the certified design to match it.

- Action recipe (deterministic): record the content digest of each accepted
  output. The cold result must reproduce that digest byte-for-byte. Anchor is the
  output hash.
- Oracle recipe (nondeterministic): record the verdict the pilot affirmed. The
  cold result must satisfy that verdict and share recipe identity. Anchor is the
  verdict, not the bytes. Two honest oracle runs differ in text; requiring
  byte-identity would be a lie about what a model step can promise.

The strength of the certificate tracks the recipe kind. Deterministic comes out
provably fixed. Model-mediated comes out provably checkable. That is the most a
nondeterministic step can honestly claim.

### 4.4 Condensation verdict

Condense if and only if the candidate type-checks, hydrates (alpha), passes the
three-machine proof (beta), and matches the warm anchor for every declared
output. Otherwise refuse and return to vapor. Refuse outright any candidate whose
verdict cannot check its output. No verdict, no anchor, no husk.

This is the recursive criterion stated operationally: a gamma husk is exactly a
condensed design that earned alpha and beta status and is anchored to the run's
accepted result.

## 5. Proof-system changes this requires

The current `_three_machine_checks` needs two changes. These are prerequisites,
not gamma-only code, and they tighten beta as well.

1. Deterministic root convergence becomes required. Today "M1 to M3 root
   convergence" is observational only, which is correct when oracles are present
   but too weak when they are not. When a design has no oracle and no free
   outputs, promote root convergence to a required check. A fully deterministic
   build that fails to reproduce its root across independent runs must fail the
   proof.
2. Warm anchor as a required check. Add a check that compares each cold output
   against the recorded warm-accepted digest (action) or runs the affirmed
   verdict against the cold output (oracle). This check is only meaningful in a
   gamma condensation, where a warm reference exists; in a plain beta `run` it is
   absent and skipped.

## 6. The declaration and its seal

A drafted declaration is the existing Design object: `name`, `fuel`, `target`,
`site_inputs` (local name to source path), `rules` (each `action` with `run`, or
`oracle` with `prompt`/`tools`/`fuel`), optional `imports` and `predicates`.

Gamma adds metadata to the manifest and seal, none of which weakens
verification:

- `declared_output_digests`: map of output path to sha256, captured from the
  warm-accepted artifacts. The action anchor.
- `accepted_verdict`: the verdict predicate and its warm pass record. The oracle
  anchor.
- `condensed_in_flight`: boolean. Marks a husk authored during exploration. A
  reader sees provenance; the flag never changes how verification runs.
- `proposal_source`: `manual` or `tracer`. Advisory only. Records who drafted the
  declaration, carries zero authority over the gate.

## 7. The extractor (the tracer)

The extractor is gamma's core authoring mechanism, not a convenience. It is how a
design comes out of an open run that started with none. During the vapor phase it
instruments the Claude Code tool stream: file reads, file writes, bash
invocations. From that it drafts a candidate design: the input set, the recipe,
the outputs, the target.

Being the authoring mechanism does not make it an authority over validity. The
split is the same as everywhere else in Husks: the extractor authors, alpha and
beta certify.

- The extractor has zero authority. A wrong proposed input set fails beta in the
  clean room and forms no husk. So extraction can be imperfect and the certificate
  stays sound.
- Soundness under a hostile extractor: a polluted or adversarially-manipulated
  trace can mislead the candidate but cannot forge a certified husk, because
  certification re-derives from the candidate in a clean room and anchors to the
  accepted result. This property must be tested explicitly, not assumed.
- The trace and the transcript never enter a seal. The extractor emits a
  candidate design and nothing else crosses into the husk.
- `proposal_source` records `manual` or `tracer` as transparent provenance. It
  never modifies certification.

## 8. The pilot envelope

`husks pilot` launches a Claude Code session inside a site, tracer attached,
`CLAUDE.md` binding the agent to the condensation discipline.

- Explicit trigger. A husk condenses only when the pilot issues `condense`. Never
  inferred from the tracer detecting a crystallized verdict. Sealing stays an act
  of authorship, not a side effect of exploration.
- Multiple condensations per session. The envelope accumulates droplets as
  conditions crystallize, rather than producing one husk at the end.
- Failure returns to vapor. A failed condensation costs little (the gate is cheap
  to re-run), so the pilot keeps exploring and retries.
- Oracle-to-action ratchet, live. Where the crystallized work is deterministic,
  the loop proposes the action recipe over the oracle. Explore with the oracle,
  condense to the action. Gamma is the ratchet's natural home.

## 9. Inter-husk DAG and evaporate-then-replay

A session yields a graph of droplets, not a flat pile. One condensed husk's
output is another's declared input. The chain is trustworthy only because the
warm anchor guarantees each output is what it claims to be, so a downstream
declared input is sound.

On session end the envelope evaporates: the transcript is discarded, and only the
replayable graph persists. An independent reader replays it cold, in topological
order, reusing the existing manifest and proof harness end to end. Exploration is
ephemeral; verified residue is permanent.

## 10. Module and layer placement

Two new modules, full layer citizens (layers.toml entry, Locke contract, tests),
same discipline as every existing module.

- `src/husks/gamma.py`, layer L6. The condensation orchestrator: assemble a
  Design, run `check`, run the cold gate (three-machine plus warm anchor), seal
  on pass. Imports `husks.locke` (L5) and below. Sits beside `report` (L6).
- `src/husks/pilot.py`, layer L7. The tracer and envelope: wrap a live session,
  instrument the tool stream, drive the explicit `condense` trigger. Imports
  `gamma` and `cli` surface as needed.

No edits to `kernel.py`. No semantic change to `engine.py`, `seal.py`,
`locke.py` beyond new call sites. Reuse `build`, `fresh_store`,
`compute_build_root`, `recompute_root`, `verify`, and the `compare` proof.

## 11. CLI surface

- `husks condense <design> --accept <out>=<file> [--site <envelope>]`
  Run the gate on a drafted declaration against the accepted warm output(s).
  CONDENSE or REJECT. Manual stand-in already prototyped as `prove.sh`.
- `husks pilot [--site <dir>] [--backend claude-code]`
  Launch the envelope. Inside, the pilot issues `condense` to fire the gate.
- Reused unchanged: `check`, `run`, `compare`, `cache export/import`, `verify`,
  `status`, `tree`.

## 12. Integrity and security model

- The seal binds only the declaration and its verified results. Never the trace.
- Cold sandbox denies clock and network unless declared, inherited from the
  oracle sandbox.
- A failing recipe must not seal. Nonzero action exit is already caught. Silent
  under-production (an action that exits zero but never writes its declared
  output) must be closed: require each declared output to be written by the
  recipe, else fail. This is a beta-level fix that gamma depends on, since the
  warm anchor assumes outputs are real.
- Hostile tracer cannot forge a husk (section 7).
- `condensed_in_flight` is transparent provenance, not a trust modifier.

## 13. Dependency order and critical path

Read top to bottom. Each tier depends on the tier above.

```
TIER 0  Certification soundness (prerequisites, also tighten beta)
  G.a  Close silent under-production: actions must produce declared outputs
  G.b  Deterministic root convergence becomes a required proof check
  G.c  Warm anchor as a required check (action digest, oracle verdict)
  G.d  Cold sandbox denials reused from oracle path
        |
TIER 1  Condensation (Phase 1)
  C.a  husks condense: assemble design, run cold gate, seal/refuse
  C.b  Refuse unverdictable declarations
  C.c  Oracle seals verdict + recipe identity, never bytes
  C.d  Manifest/seal fields: declared_output_digests, accepted_verdict,
       condensed_in_flight, proposal_source
        |
TIER 2  Tracer (Phase 2)
  T.a  Tool-stream instrumentation to draft a candidate Design
  T.b  Proposal validated only by re-derivation, never asserted
  T.c  Hostile-tracer soundness test
  T.d  Trace never enters seal (boundary test)
        |
TIER 3  Pilot envelope (Phase 3)
  P.a  husks pilot launches a live session, tracer attached
  P.b  Explicit condense trigger
  P.c  Multiple condensations per session
  P.d  Failed condensation returns to vapor
  P.e  Live oracle-to-action ratchet
        |
TIER 4  Composition (Phase 4)
  D.a  Inter-husk DAG: one output, another's declared input
  D.b  Evaporate-then-replay: discard transcript, persist replayable graph
  D.c  Cold topological end-to-end replay via existing harness
```

Critical path: G.c (warm anchor) and G.b (deterministic convergence) are the true
root. If either is wrong, every husk above inherits the unsoundness. Build and
prove Tier 0 before writing a line of condense. The pilot (Tier 3) cannot exist
before the tracer (Tier 2), and the extractor is pointless before the certification it feeds
(Tier 1). The DAG (Tier 4) needs the warm anchor specifically, because a chained
declared input is only sound if the upstream output is anchored.

Cross-cutting, grows every tier:
  X.a  Failure localization: name the undeclared file a rejected recipe leaned on
  X.b  Acceptance tests: promote prove.sh cases into the suite, one set per tier

## 14. Phased delivery with acceptance tests

Each phase is one reviewable unit. Do not start the next before the prior passes.
777 tests stay green throughout, plus the new gamma tests. One commit per phase.

Phase 0 (Tier 0). Land G.a through G.d in the existing proof and engine. Tests:
an action that does not write its declared output fails; a deterministic design
whose independent run diverges fails the proof; a clock/network access that is
undeclared fails cold.

Phase 1 (Tier 1). `husks condense`, manual declaration, cold gate, warm anchor,
seal on pass. Tests, the prove.sh set promoted:
- honest deterministic declaration condenses (exact digest match);
- leaky declaration (undeclared session file) rejects at the clean-room build;
- oracle declaration condenses via verdict, not byte-identity;
- declaration with a missing/empty declared output rejects;
- unverdictable declaration is refused outright.
Stop here for review.

Phase 2 (Tier 2). Tracer as proposer. Tests: a correct proposal condenses; a
proposal omitting a real input rejects cold; a maliciously-padded trace cannot
produce a passing husk; no seal contains any transcript byte.

Phase 3 (Tier 3). `husks pilot` envelope. Tests: explicit trigger required;
multiple condensations accumulate; a failed condensation leaves the pilot able to
retry; the ratchet proposes an action where the work is deterministic.

Phase 4 (Tier 4). Inter-husk DAG and evaporate-then-replay. Tests: a two-husk
chain where one output feeds another's input replays cold in topological order; on
session end the transcript is gone and the graph alone reproduces every droplet.

## 15. Open decisions to pin before coding

- Trigger model for the pilot: confirmed explicit `condense`, not inferred. Pin
  it in the brief so the agent does not "helpfully" auto-seal.
- Accepted-output capture: does the pilot hand the accepted artifact to
  `condense` (current prove.sh shape), or does the envelope snapshot the target
  output at the moment the pilot issues the trigger. The latter is more
  ergonomic and keeps the anchor honest. Decide in Phase 1.
- Oracle verdict storage: the affirmed verdict must be a declared predicate, not
  free text, so the cold gate can re-run it. Forbid condensing an oracle result
  whose acceptance was only an informal judgment.
- Scope of evaporation: whether the envelope keeps a local, unsealed exploration
  log for the pilot's own use after the session, clearly outside any husk and
  never an input. Default: discard, to keep the boundary unambiguous.

## 16. Risks

- The warm anchor is the load-bearing novelty. If it is implemented as cold-cold
  agreement only, gamma silently certifies reproducibly-wrong results. Treat G.c
  as the highest-risk item and test it adversarially.
- Tracer scope creep toward sealing convenience. Any pressure to "just record
  what happened" reintroduces the recorder failure. Hold the section 2 invariant.
- Ergonomics of declaring inputs. If condensation is painful, pilots will
  over-declare or abandon the mode. The tracer exists to make the honest path the
  easy path; if it does not, the mode will not be used.
- Layer discipline. gamma.py and pilot.py must be full citizens or the next
  convergence audit flags them, the same way config was flagged before.
