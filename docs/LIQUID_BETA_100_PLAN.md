# Liquid Beta 100: live three-machine equivalence

Target commit base: `eb90208` ("Liquid beta 95"). Spec of record: `three_machine_problem_white_paper_v3.pdf`. Goal: the three-machine proof validates on the live oracle path, not only the stub path. Equivalence on the live path is per-output and validator-bounded, proved on a behavioral conformance digest.

## Problem statement

The live three-machine run passes every substantive check (M1 paid, M2 cache reuse at zero cost, M3 independent paid, M1/M3 cost comparable, all sites valid) but `compare-runs` reports `equivalent: false` on a single violation: `Build roots differ`.

This violation is wrong against the spec. White paper Section 4 states the seed/cache split exists to prevent "independent re-realization from being mistaken for deterministic identity." Section 3 sets M3's obligation at "a valid artifact ... comparable to C1 under a declared tolerance," not a shared root. Section 5 states equivalence "may be bitwise identity ... or validator-bounded acceptance" and that "the seed design must state which form is required."

In the live run, M3's declared outputs match M1 on everything except the generated source:

- `readers/VERIFIED@e3b0c4` (M1) == `readers/VERIFIED@e3b0c4` (M3)
- `readers/gate-report.txt@7f6aec` (M1) == `readers/gate-report.txt@7f6aec` (M3)
- only `readers/generated_reader.py` differs (`@278d36` vs `@ca6a95`)

This has the shape of validator-bounded acceptance, but with the current validator it is vacuous and must not be relied on as a live proof. See Task A0. The `core-bootstrap` validate rule used by this run does not run the conformance gate. It runs `py_compile` and writes constants: `VERIFIED` is an empty file (`e3b0c4` is the SHA-256 of empty input) and `gate-report.txt` is the fixed string `PASS: reader compiles` (`7f6aec`). Both outputs are independent of what the oracle generated, so any two readers that merely compile match, including a reader that compiles and computes the wrong root. A live equivalence proof requires the acceptance output to be a function of the artifact's behavior.

Three root causes:

1. The `core-bootstrap` validate rule does not bind acceptance to behavior. The acceptance outputs are constants (Task A0).
2. `bootstrap-core.json` declares `outputs` but states no equivalence relation. The spec requires it to (Task A1).
3. `_cmd_compare_runs` hard-codes global bitwise root identity across all three sites (`if len(set(roots)) > 1`), which the spec scopes to the cache path only (Task A4).

Do not pursue any output canonicalizer for the generated source. Forcing M1/M3 to one root collapses re-realization into deterministic identity, the exact conflation Section 4 forbids. The source stays `free`; equivalence is proved on a behavioral acceptance digest instead.

## Equivalence vocabulary

Two values, per declared output. Default is `exact` for backward compatibility.

- `exact`: the output's content hash must match across independent realizations. Reserved for acceptance-bearing outputs whose content is a deterministic function of the artifact's verified behavior (the conformance digest from Task A0), not a constant pass-marker.
- `free`: the output may differ across independent realizations. Not acceptance-bearing. Excluded from the cross-machine relation.

No third value is needed. Validator-bounded acceptance is `exact` applied to the output that carries the conformance digest. An `exact` mark on a constant output is meaningless; A0 makes the acceptance output behavioral so the mark has content.

## Task A0: bind acceptance to behavior (prerequisite for a live proof)

This is the load-bearing task. Without it the live equivalence relation is vacuous.

Files: `src/husks/gate.py`, `src/husks/setup.py` (the `core-bootstrap` JSON template `validate` rule near line 253, and the Hy template near line 308), `examples/json_designs/bootstrap-core.json`.

1. Make `core-bootstrap`'s `validate` rule run the conformance gate, not `py_compile`. The Hy template already does (`python3 -m husks.gate 'python3 readers/generated_reader.py' --stamp-dir readers`). Bring the JSON template and `bootstrap-core.json` to the same gate invocation. Confirm `husks.gate.main` exits nonzero on gate failure so a wrong reader halts the build and never seals.

2. Make the gate stamp a conformance digest, not a constant. In `gate.gate()`, during the positive-vector loop, collect each `(name, got_root)` pair (on pass, `got == expected`). After all checks pass, compute `digest = sha256( "\n".join(f"{name}:{got_root}" for name,got_root in sorted(pairs)) )` and write it to the stamp output instead of `"PASS\n"`:

```python
(stamp_dir / "VERIFIED").write_text(conformance_digest + "\n")
```

Optionally also write the per-vector detail to `gate-report.txt` (human-readable log; this output stays `free`).

The conformance digest is constant across all *correct* readers, because the frozen `.root` values are fixed. That is the point: it is a canonical acceptance token derived from verified behavior. A reader that computes a wrong root fails the gate before any stamp is written, so it cannot produce the digest.

Result: `VERIFIED` content now means "this reader agrees with the frozen golden roots," and two machines matching on `VERIFIED` is a real statement of behavioral equivalence, not "both compiled."

## Task A1: declare equivalence in the seed design

Files: `src/husks/setup.py` (the `core-bootstrap` template dict near line 233, plus the Hy template `deforacle`/`rule` form around line 301), and `examples/json_designs/bootstrap-core.json`.

Add an optional per-rule `equivalence` map keyed by output path. Unlisted outputs default to `exact`. For `core-bootstrap`:

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

`readers/VERIFIED` carries the conformance digest from A0 and is the single acceptance-bearing output. `gate-report.txt` is a human-readable log and is `free` (it may carry timing or paths). The generated source is `free`.

Constraints:

- `equivalence` is metadata for `compare-runs` only. It must not enter the seal preimage or the build root. The seal/node form lives in `src/husks/core.py` (`compute_seal`, the `node` form over `out_list`); do not touch it.
- Keep `outputs` as `list[str]`. The build transaction in `src/husks/build/eval.py` (`BuildTransaction.validate_outputs`, iterating `self.outputs`) must continue to receive a plain string list. Do not overload `outputs`.
- Confirm `husks check` and the design loader accept the new key without rejecting it as unknown. If the loader is strict, add `equivalence` to the allowed rule keys.

## Task A2: add a declared cost tolerance to the seed design

White paper Section 5: "The tolerance for comparable cost must be explicit." Add a top-level seed field:

```json
"cost_tolerance": { "ratio": [0.5, 2.0] }
```

`compare-runs` reads this. If absent, default to ratio `[0.5, 2.0]` (the spec's example). This replaces the hard-coded 10% epsilon currently in `_cmd_compare_runs`. The live result (C3/C1 = 1.002) passes either way; the point is to source the bound from the seed, not from code.

## Task A3: emit named output hashes in the report

File: `src/husks/report.py`, `assemble()`.

The node dict currently carries `output_hashes` as a positional `list[str]` with no path pairing. Per-output comparison by name is impossible from this. Add a named map while keeping the list for backward compatibility:

```python
node_dict["outputs"] = [
    {"path": path, "hash": h}
    for path, h in zip(rule_ir.get("outputs", []), cur_hashes)
]
```

Also surface each rule's `equivalence` map onto the node so `compare-runs` does not need to re-load the seed:

```python
node_dict["equivalence"] = rule_ir.get("equivalence", {})
```

Update `validate_report_schema()` to accept the optional `outputs` (list of `{path, hash}`) and optional `equivalence` (dict) fields. Keep `schema_version` at `beta-1`; these are additive and optional, so no version bump is required, but assert the old `output_hashes` field is still present.

## Task A4: rewrite the cross-machine relation in `compare-runs`

File: `src/husks/cli/cmd/compare.py`, `_cmd_compare_runs`, the three-machine block.

Replace the global root check:

```python
roots = [r["root"] for r in comparison["runs"] if r["root"]]
if len(set(roots)) > 1:
    comparison["violations"].append(f"Build roots differ: {roots}")
    comparison["equivalent"] = False
```

with three scoped checks.

1. Cache path is deterministic. M1 root must equal M2 root exactly. If not, violation `m1_m2_root_identical` fails. This preserves the existing guarantee that cache reuse is bitwise materialization.

2. Re-realization is validator-bounded. Build the set of acceptance-bearing outputs from declared `equivalence` (every output not marked `free`, across all rules). With the A1 declaration this is `readers/VERIFIED` alone, carrying the A0 conformance digest. For each acceptance output, M3's hash must equal M1's hash, matched by `path`, not position. Any mismatch is a violation `m3_declared_equivalence`. `free` outputs are excluded before comparison. If the seed declared nothing, default all outputs to `exact` (preserves current strictness for designs that never opt in).

3. Cost comparability uses the declared tolerance from Task A2. Keep this a hard violation when out of bound.

Add an observational `convergence` block that never flips `equivalent`:

```json
"convergence": {
  "m1_m3_same_root": false,
  "acceptance_outputs": ["readers/VERIFIED"],
  "acceptance_outputs_match": true,
  "free_outputs": ["readers/generated_reader.py", "readers/gate-report.txt"]
}
```

Preserve the existing invariant: any entry in `violations` implies `equivalent == false`. Keep all current oracle-evidence and cache-evidence node-level checks unchanged. Exit `EXIT_OK` when equivalent, `EXIT_BUILD_FAIL` otherwise.

## Task B: renderer corrections

File: `src/husks/cli/view.py` (rewritten in beta 95; the regressions below are in that code).

1. The whole rule tree must render from the first hydration frame, with only node state advancing. The current live frames show `generate` alone, then `validate` with a child `generate`. The tree shape must be stable across frames.

2. The sealed final frame on M1 and M3 shows `⚡0/20` while both paid one live oracle call. The oracle/fuel counter on a committed frame must reflect oracle calls actually fired this run. Fix the counter source so a paid live run does not render as `⚡0`.

3. A single committed run must render local success even when its root will diverge from a sibling. Global divergence belongs only in `compare-runs` `convergence`, never in the per-site seal frame. Verify the per-site view does not import cross-site state.

## Tests

Files: `tests/test_compare_runs.py`, `tests/test_beta_three_machine.py`, `tests/test_three_machine_cli_acceptance.py`, `tests/test_artifact_equivalence.py`, `tests/test_live_oracle_readiness.py`.

Required cases:

1. Re-realization pass: three committed reports where M1 root == M2 root, M3 root differs, M3 `generated_reader.py` hash differs from M1, M3 `VERIFIED` hash equals M1 (both carry the same conformance digest from A0), costs within declared tolerance. Expect `equivalent: true`, exit 0, `convergence.m1_m3_same_root: false`, `convergence.acceptance_outputs_match: true`. Model the divergent source on the live result (`@278d36` vs `@ca6a95`) and the costs (`$0.031699` vs `$0.031765`), but set `VERIFIED` to a shared non-empty digest, not the pre-A0 empty-file hash `e3b0c4`.

2. Acceptance divergence fails: same as case 1 but M3 `VERIFIED` differs from M1 (the two readers computed different conformance digests). Expect `equivalent: false`, violation `m3_declared_equivalence`, exit nonzero.

3. Cache nondeterminism fails: M1 root != M2 root. Expect `equivalent: false`, violation `m1_m2_root_identical`.

4. Cost out of tolerance fails: C3/C1 outside declared ratio. Expect violation, exit nonzero.

5. Default strictness preserved: a seed with no `equivalence` declarations treats every output as `exact`; a differing source output then fails, matching pre-change behavior.

6. Root invariance regression: building `core-bootstrap` with and without the `equivalence` and `cost_tolerance` fields yields the identical build root. Equivalence metadata must not perturb the seal.

7. Schema: a report with the new named `outputs` and `equivalence` fields passes `validate_report_schema`; a report missing `output_hashes` still fails.

8. Behavioral validator (A0): a reader that compiles but computes a wrong root on any frozen vector fails the gate, exits nonzero, and does not seal. Assert no `VERIFIED` is written on gate failure. Assert two correct-but-textually-different readers produce identical `VERIFIED` digests.

9. Live end-to-end (gated, requires `ANTHROPIC_API_KEY`; skip otherwise): run M1 and M3 with the live oracle and M2 from M1's cache, then `compare-runs`. Expect `equivalent: true` with divergent roots and matching `VERIFIED` digests. This is the actual Beta 100 live proof; keep it as a marked integration test so CI without a key still runs cases 1 to 8.

## Task C: amend `docs/CLI_BETA_100.md` for the live claim

Proving live contradicts two statements the doc currently makes, both of which are stub-only:

1. The `compare-runs` Checks list reads "All: Same root (build equivalence)." Replace with the scoped relation: M1==M2 root (cache), M3 validator-bounded acceptance on the conformance digest, cost within declared tolerance, root convergence reported observationally.
2. The Overview headline "verifiably identical build artifacts" is true for stub, false for live. Reword to "verifiably equivalent build artifacts under the design's declared acceptance relation."

Add a live expected-result block alongside the existing stub one, showing divergent roots with matching `VERIFIED` digests and comparable cost. Keep the stub block; both paths are valid. The stub path proves deterministic identity; the live path proves bounded re-realization with behavioral acceptance.

## Acceptance criteria for Liquid Beta 100

- A live three-machine run (M1 live oracle, M2 cache reuse, M3 live oracle) returns `equivalent: true`, exit 0, with divergent build roots and matching `VERIFIED` conformance digests.
- Acceptance is behavioral: `VERIFIED` carries the conformance digest, and a reader that compiles but computes a wrong root fails the gate and never seals.
- `compare-runs` enforces: M1==M2 root, M3 validator-bounded acceptance on the conformance digest, cost within declared tolerance. It reports M1/M3 root convergence observationally only.
- The seed design states the per-output equivalence form and the cost tolerance, satisfying white paper Section 5.
- Build root is unchanged by the new metadata.
- Renderer shows a stable tree from frame one, a correct oracle counter on paid runs, and no cross-site state in a single-site seal frame.
- `docs/CLI_BETA_100.md` no longer claims same-root or bitwise-identical artifacts on the live path.
- Full test suite green, including the nine cases above (case 9 gated on `ANTHROPIC_API_KEY`).

## Out of scope

- Output canonicalization or any attempt to force M1/M3 root identity.
- Changes to `core.py` seal/root computation.
- Changes to the `compare` command (artifact `compare_artifacts`); only `compare-runs` changes here.
