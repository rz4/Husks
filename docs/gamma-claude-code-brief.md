# Gamma: Claude Code build brief

Companion spec: `gamma-design.md`. Read it first. This brief is the execution
contract. Where the two differ, the design doc defines intent and this brief
defines order, scope, and the tests that gate each step.

## Mission

Make Husks able to condense a design from an open pilot run, such that the
condensed design then clears alpha (hydrates dry to CSE) and beta (passes the
three-machine proof) and matches the result the run accepted. Gamma is an
authorship status, not a new verifier. It adds no new way to verify a husk.

## The invariant (verbatim, do not edit, do not soften)

> A husk is a declaration that passed its gates, even when authored in flight.
> Condensation runs the gate cold. It never snapshots the session. The day a
> seal contains the transcript, gamma is dead and you have built a recorder.

Authorship, acceptance, and verification stay three separate things. Any flow
that blurs them is wrong even if it is more helpful.

## Hard constraints (these bind every commit)

- Additive only. No edits to `kernel.py`. No semantic change to `engine.py`,
  `seal.py`, `locke.py` beyond new call sites.
- Reuse, do not reimplement: `build`, `fresh_store`, `compute_build_root`,
  `recompute_root`, `verify`, and the `compare` three-machine proof.
- New modules are full layer citizens: `layers.toml` entry, a Locke contract,
  and tests. Same discipline as every existing module, or the convergence audit
  flags them.
- 777 existing tests stay green throughout. One commit per phase.
- Build `condense` before `pilot`. Do not start `pilot.py` until the conformance
  set below is green. This ordering is a requirement, not a preference: it keeps
  authorship and verification from merging under a UX.

## Repo facts (verified, do not rediscover)

- Layers: kernel L0, forms L1, seal L2, engine L3, oracle/config L4, locke L5,
  report L6, cli L7. New: `gamma.py` L6, `pilot.py` L7 (phase 3 only).
- Design schema (JSON or `.locke`): `name`, `fuel`, `target`,
  `site_inputs` (map local-name to source-path), `rules` (each `action` with
  `run`, or `oracle` with `prompt`/`tools`/`fuel`), optional `imports`,
  `predicates`.
- A declared input must be a `site_input` or a rule output. A loose file in the
  dir is not an input. This is the first thing to get wrong.
- CLI primitives to reuse: `husks check`, `husks run <d> --site S [--reuse-only]
  [--backend claude-code]`, `husks cache export S F`, `husks cache import F S`,
  `husks compare S1 S2 S3 --json` (reports `proof.satisfied`), `husks verify S`.
- Verified current behavior: a nonzero action exit is caught and seals nothing.
  An action that exits zero but never writes its declared output still seals an
  empty output. That second case is Tier 0 item G.a below.
- `_three_machine_checks` currently leaves M1-to-M3 root convergence
  observational. That is Tier 0 item G.b.

## Naming

The check that the cold result equals what the run accepted is the
**acceptance anchor**. Use `acceptance_anchor` in code and prose. "Warm" and
"cold" are informal gloss only.

## Tier 0: certification hardening (do this first, it is beta hardening)

These are prerequisites, not gamma features. Gamma cannot be sound until they
land. Each lands with its failing-then-passing test.

- G.a Silent under-production. After an action, require every declared output to
  have been written by the recipe. If a declared output is absent or was not
  produced by the run, fail. No auto-touched empty outputs.
- G.b Deterministic root convergence. In `_three_machine_checks`, when a design
  has no oracle and no free outputs, promote M1-to-M3 root convergence from
  observational to required. A deterministic build whose independent runs diverge
  must fail the proof.
- G.c Acceptance anchor as a required check. Compare each cold output against the
  recorded accepted digest (action), or run the affirmed verdict predicate
  against the cold output (oracle). Meaningful only when an acceptance reference
  exists, that is, in a condensation. Skipped in a plain `run`.
- G.d Cold sandbox denial. The clean-room build denies wall-clock and network
  unless declared. Reuse the oracle sandbox denial path. Do not write a second.

## Tier 1: condense (Phase 1)

`gamma.py` at L6, plus `husks condense`.

- `husks condense <design> --accept <out>=<file> [--site <envelope>]`. Assemble
  the candidate, run `check`, hydrate (alpha), run the three-machine proof
  (beta), run the acceptance anchor. CONDENSE on all-pass, REJECT otherwise.
  Manual stand-in already exists as `prove.sh`; promote its logic into the
  command.
- Verdicts are typed, not prose. An acceptance verdict V is a named, versioned,
  deterministic predicate with declared inputs. The certificate reads: same
  recipe identity, cold output satisfies V, accepted output satisfied V. Refuse
  outright any oracle candidate whose acceptance is prose, a human judgment, or
  any non-executable form. No verdict, no anchor, no husk. Anything weaker is
  vibes with a manifest.
- Action anchor is the output content digest. Oracle anchor is V, never bytes.
- Seal/manifest fields, none of which weaken verification: `acceptance_anchor`
  (action digests or verdict id+version), `condensed_in_flight` bool,
  `proposal_source` (`manual` or `tracer`, transparent provenance only).

## Tier 2: the extractor (Phase 2)

`pilot.py` instrumentation. The extractor reads the open run's tool stream
(reads, writes, bash) and drafts a candidate design. It is gamma's authoring
mechanism and has zero authority over validity.

- Treat extractor output exactly as an untrusted patch. It proposes
  `site_inputs`, rules, outputs, and target. The clean-room certification
  decides. No extractor-derived file is ever implicitly trusted as an input.
- The trace and transcript never cross into a seal. The extractor emits a
  candidate design and nothing else.

## Tier 3: pilot envelope (Phase 3, blocked until conformance is green)

`husks pilot` launches a live Claude Code session in a site with the extractor
attached. Explicit `condense` trigger only, never inferred. Multiple
condensations per session. A failed condensation returns to vapor. Live
oracle-to-action ratchet.

## Conformance set (the gate on the whole effort)

Five adversarial tests, one per invariant, each a refusal. They are the
definition of correct, the way the rest of Husks is defined by what it rejects.
Write them first and start red. `pilot.py` is forbidden until all five pass.

1. Undeclared session file. A candidate whose recipe reads a file created during
   the run but not declared as a `site_input` must REJECT (fails beta in the
   clean room). Exercisable today via `run` in a fresh site; `prove.sh` leaky
   case already demonstrates it.
2. Nondeterministic deterministic-typed recipe. An action whose output differs
   across independent cold runs (for example reads `/dev/urandom`) must REJECT
   under G.b.
3. Reproducible but not accepted. A deterministic recipe that reproduces the same
   root every cold run but whose output differs from the accepted output must
   REJECT under G.c, the acceptance anchor.
4. Unverdictable oracle. An oracle candidate with no executable, declared verdict
   predicate must REJECT. Prose acceptance is not a verdict.
5. Transcript in the seal. A candidate, or an extractor proposal, that would place
   transcript bytes into the seal must REJECT. No transcript content reaches a
   sealed field.

Suggested stubs (target `husks condense`, start red):

```python
# tests/L6-inspect/test_gamma_conformance.py
import subprocess, json, pathlib, pytest

def condense(design, accept, site):
    return subprocess.run(
        ["husks", "condense", design, "--accept", accept, "--site", site],
        capture_output=True, text=True)

def test_undeclared_session_file_rejects(tmp_path): ...      # invariant 1
def test_nondeterministic_action_rejects(tmp_path): ...      # invariant 2
def test_reproducible_but_unaccepted_rejects(tmp_path): ...  # invariant 3
def test_unverdictable_oracle_rejects(tmp_path): ...         # invariant 4
def test_transcript_never_in_seal(tmp_path): ...             # invariant 5
```

Each test asserts a nonzero exit and that no husk was sealed. For invariant 5,
assert additionally that no sealed field equals or contains any transcript
substring fed to the extractor.

## Review gates

Stop and wait for review after: Tier 0 complete and green; Tier 1 plus the five
conformance tests green; Tier 2 green. Do not begin Tier 3 before the conformance
set passes. Do not collapse authorship, acceptance, and verification into one
flow at any point.

## First task only

Tier 0, item G.a. Close silent under-production: an action that does not produce
its declared output must fail and seal nothing. Add the failing test first
(`run: "true"` with a declared `out.txt` currently seals an empty file), then the
fix, then confirm 777 plus the new test pass. Stop there for review.
