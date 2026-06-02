# Husks Beta Build Plan: Three-Machine Problem

Revised after review of `Husks-main (16).zip`.

This version replaces the broader beta task list with a smaller gated plan. The repo now has most of the beta machinery: transactions, staged output policy, artifact identity, cache export and import plumbing, reuse-only CLI support, a beta seed directory, and internal three-machine tests. The remaining work is narrower: make the proof trustworthy, make it user-runnable from the CLI, and reduce code accretion while doing it.

The current risk is not that Husks lacks machinery. The risk is that the same beta concepts are now represented in too many places. Cost, reuse, report fields, cache metadata, CLI output, history, and tests each know part of the proof. The next revision should remove duplication where it blocks beta, not perform a broad cleanup.

## Beta acceptance target

Husks beta is reached when this workflow passes from a clean checkout and from an installed package:

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

Machine 3 does not receive the shared cache. It receives only the seed design and independently realizes a valid build at comparable cost to Machine 1.

## Current beta posture after Husks-main (16)

```text
Gate A: Seed design portability                Yellow / Red
Gate B: Transactional execution                Green
Gate C: Artifact identity and equivalence      Green / Yellow
Gate D: Cache reuse                            Yellow / Red
Gate E: Independent re-realization             Yellow / Red
Gate F: Ledger and cost comparability          Yellow
Gate G: Release smoke and acceptance           Red / Yellow
Gate H: Bloat control and consolidation        Yellow / Red
```

Interpretation:

```text
Green        Preserve behavior, keep tests passing.
Yellow       Machinery exists, but the acceptance path is incomplete.
Red          Blocks beta proof or clean handoff.
Yellow / Red Machinery exists, but one remaining flaw invalidates the gate.
```

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

Do not broaden the scope beyond this proof.

## Bloat-control rule for the next pass

Every new feature task that touches a large module must either:

```text
1. land behind an existing narrow API, or
2. extract duplicated policy into one small module before adding behavior.
```

Do not add a second implementation of an existing concept. Do not make beta depend on test-only helper behavior. Do not add another report schema, another cache schema, another CLI JSON format, or another seed fixture.

Current large modules to protect:

```text
src/husks/cli/commands.py
src/husks/designs/ir.py
src/husks/build/eval.py
src/husks/build/cache.py
src/husks/core.py
tests/conftest.py and ad hoc subprocess tests
```

Preferred movement:

```text
- Move policy out of large modules into narrow helpers.
- Keep CLI commands thin.
- Keep eval focused on execution.
- Keep cache validation inside the cache module.
- Keep report acceptance fields in one schema.
- Keep all CLI subprocess tests on one helper.
```

## Development rule

Use the three-machine CLI acceptance test as the spine.

A task is beta-relevant only if it makes this script more correct, more secure, more portable, or easier to audit:

```bash
husks run examples/beta_seed/design.json \
  --site m1-site \
  --cache m1-cache \
  --json > m1.json

husks cache-export \
  --cache m1-cache \
  --output husks-cache.tgz \
  --json > cache-export.json

husks cache-import \
  --cache m2-cache \
  --input husks-cache.tgz \
  --json > cache-import.json

husks run examples/beta_seed/design.json \
  --site m2-site \
  --cache m2-cache \
  --reuse-only \
  --json > m2.json

husks run examples/beta_seed/design.json \
  --site m3-site \
  --cache m3-cache \
  --json > m3.json

husks compare-runs \
  m1.json m2.json m3.json \
  --json > beta-comparison.json
```

If the project chooses nested commands instead, use this form consistently everywhere:

```bash
husks cache export --cache m1-cache --output husks-cache.tgz --json
husks cache import --cache m2-cache --input husks-cache.tgz --json
```

Do not document one command shape while implementing another.

# Gate A: Seed design portability

Goal:

```text
A seed design can move to a clean machine and build without repo-local assumptions, hidden state, or test-only fixtures.
```

Current status:

```text
Yellow / Red. Unknown-field validation and init behavior have improved. `site_inputs` mostly work for absolute paths and dict mappings. The blocker is relative seed input portability. A design with `site_inputs: ["prompt.txt"]` does not reliably resolve that file relative to the design file and carry it into a clean site. Missing declared inputs can be hidden by stub behavior.
```

| Rank | Status | Task | Files to inspect | Claude Code prompt |
|---:|---|---|---|---|
| A1 | Blocker | Resolve relative `site_inputs` against the design file | `src/husks/designs/ir.py`, `src/husks/build/run.py`, `src/husks/build/site.py`, `src/husks/core.py`, tests | Use the design file `_source_path` to resolve relative `site_inputs`. List form should mean `design_dir/name -> site/name`. Dict form should support explicit source and destination. Add CLI tests where `design.json` and `prompt.txt` live together and the site starts empty. |
| A2 | Blocker | Require declared site inputs to exist before execution | `src/husks/build/site.py`, `src/husks/build/run.py`, tests | A missing declared site input should halt before any rule fires. Do not allow a missing input signature to become `ABSENT` for declared seed inputs unless the design explicitly marks it optional. |
| A3 | Done, keep tests | Preserve unknown-field rejection | `src/husks/designs/ir.py`, tests | Keep failures for misspelled fields such as `ouputs`, `taget`, `fuell`, and unknown top-level fields. Avoid duplicating allowed-field lists across modules. |
| A4 | Partial | Keep graph diagnostics clear without expanding scope | `src/husks/designs/ir.py`, tests | Preserve current forward-reference, duplicate-output, and conditional diagnostics. Improve only if messages block the beta seed or acceptance test. |
| A5 | Partial | Make `husks init` share the same seed machinery as `examples/beta_seed` | `src/husks/setup.py`, `examples/beta_seed`, tests | Avoid maintaining two unrelated seed examples. Either generate from the canonical beta seed template or keep a smaller init template that exercises the same portability path. |
| A6 | Partial | Keep one canonical beta seed directory | `examples/beta_seed/`, docs, tests | Use one spelling, one path, and one README. Do not duplicate a second `examples/beta-seed/` unless the whole repo switches to hyphenated naming. |

Exit criteria:

```text
- A JSON seed with relative declared site inputs builds from a clean site.
- Missing declared site inputs fail before execution.
- `husks init && husks check && husks run --stub` succeeds.
- The beta seed exists outside tests and is the only source of truth for the acceptance test.
```

## Conditional seed semantics

Conditional seed portability semantics (formerly Beta Gate A4).

**Runtime Execution**: Only the selected branch executes (determined by predicate evaluation).

**Design Identity**: Both branches are bound into the seed identity (CSE form).

**Build Root**: Includes actual output content, so it differs when different branches produce different outputs.

This semantic choice enables seed portability while maintaining reproducibility:

```
Machine 1 (file exists)    ->  executes 'then' branch  ->  output A
Machine 2 (file missing)   ->  executes 'else' branch  ->  output B

Same seed design (same CSE form)
Different build outputs (different build-roots)
Both valid, both reproducible
```

The **seed design** is portable and complete. The **build outputs** depend on the environment and predicate evaluation.

### Design identity (CSE form)

When a `cond` node is serialized to CSE, it includes the predicate identity, the complete 'then' branch subtree, and the complete 'else' branch subtree:

```python
[b"cond", predicate_id, then_cse, else_cse]
```

Both branches are part of the design, making it complete (all execution paths specified), portable (the design can move between machines), and deterministic (same design produces the same CSE hash).

### Build root (Merkle DAG)

The build-root is computed after execution and includes which branch actually executed, the actual output content hashes, and the seals of rules that fired. Different branches produce different outputs, so:

```
Build-root = f(design, inputs, environment, predicate_result)
```

### Three-machine conditional scenario

For the beta three-machine proof, if Machine 1 and Machine 3 take different branches:

- Machine 1: `predicate=True` -> executes then branch -> output A
- Machine 3: `predicate=False` -> executes else branch -> output B

Expected behavior: same design (CSE hash matches), different build-roots (outputs differ), both valid and reproducible, seed is portable. Machine 2 uses cache from Machine 1: same design, same branch executed (cache hit requires same recipe), same build-root (reused outputs), zero oracle cost.

A conditional design is complete only if both branches are specified. Missing either branch makes the design incomplete and non-portable.

# Gate B: Transactional execution

Goal:

```text
A build cannot corrupt the live site. Outputs commit only after validation.
```

Current status:

```text
Green. BuildTransaction, staging, validation, rollback, live-site bypass blocking, regular-file output policy, import hardening, and reader command parsing are in place. Do not redesign this gate before beta.
```

| Rank | Status | Task | Files to inspect | Claude Code prompt |
|---:|---|---|---|---|
| B1 | Done, protect | Preserve `BuildTransaction` behavior | `src/husks/build/eval.py`, `src/husks/build/site.py`, tests | Do not refactor transaction semantics unless a cache validation change requires it. Keep staging, validation, promotion, and rollback tests green. |
| B2 | Done, protect | Preserve live-site bypass blocking | `src/husks/build/site.py`, `src/husks/build/eval.py`, tests | Declared outputs must come through staged write paths. A direct live write must not become a sealed success. |
| B3 | Done, protect | Preserve regular-file output policy | `src/husks/build/eval.py`, `src/husks/build/site.py`, tests | Keep directories, symlinks, broken symlinks, and special files rejected before sealing. |
| B4 | Done, protect | Preserve import and symlink hardening | `src/husks/build/site.py`, tests | Keep runtime validation for path traversal, internal paths, collisions, and unsafe symlinks. |
| B5 | Done, protect | Keep trial outputs text-only for beta | `src/husks/build/eval.py`, tests | Preserve the explicit text-only beta policy unless the beta seed needs binary outputs. |
| B6 | Done, protect | Preserve `shlex.split()` reader parsing | `src/husks/gate.py`, `src/husks/cli/commands.py`, tests | Avoid reintroducing raw `.split()`. |
| B7 | Done or verify | Keep cache write failure nonfatal after promotion | `src/husks/build/eval.py`, `src/husks/build/cache.py`, tests | Verify that a post-promotion cache write failure cannot make the build look half-failed or corrupt the site. If already fixed, keep the regression and do not touch. |

Exit criteria:

```text
- Failed validation commits no declared outputs and writes no seal.
- Live-site bypass cannot produce a sealed success.
- Cache failures do not corrupt the transaction story.
```

# Gate C: Artifact identity and equivalence

Goal:

```text
Outputs can be compared and verified across machines.
```

Current status:

```text
Green / Yellow. Site comparison exists. Root verification and artifact identity are strong enough for beta. The remaining work is report-level comparison: Machine 1, 2, and 3 JSON reports must be checked for validity, reuse, oracle calls, and cost tolerance.
```

| Rank | Status | Task | Files to inspect | Claude Code prompt |
|---:|---|---|---|---|
| C1 | Done, audit once | Preserve recipe identity coverage | `src/husks/build/identity.py`, `src/husks/build/nodes.py`, tests | Keep shell command identity, Python action identity, oracle recipe identity, inputs, outputs, and parameters in recipe digests. Add only missing invalidation tests. |
| C2 | Partial | Improve invalid-state diagnostics without a new schema | `src/husks/manifest.py`, `src/husks/build/seal.py`, tests | Expose concise invalid manifest and invalid root reasons. Do not introduce a second manifest validation path. |
| C3 | Partial | Add `compare-runs` for the beta proof | `src/husks/cli/commands.py`, `src/husks/report.py`, tests | Add a report-level comparison command. It should read `m1.json`, `m2.json`, and `m3.json`, then check artifact validity, output roots or declared hashes, seal validity, Machine 2 reuse, Machine 2 zero oracle calls, and Machine 3 cost tolerance. |
| C4 | Partial | Make `compare-runs --json` quiet | `src/husks/cli/commands.py`, tests | Emit valid JSON only on stdout. Put human diagnostics on stderr or non-JSON mode. |
| C5 | Done, protect | Preserve normalized hashing semantics | `src/husks/core.py`, `src/husks/build/site.py`, `src/husks/manifest.py`, tests | Keep absent files, regular files, and unsupported paths represented consistently. |

Exit criteria:

```text
- `husks compare` or library equivalence can compare sites.
- `husks compare-runs` can compare the three beta reports.
- Invalid roots or invalid manifests fail the acceptance path with clear JSON.
```

## Live-path equivalence vocabulary

Two values, per declared output. Default is `exact` for backward compatibility.

- `exact`: the output's content hash must match across independent realizations. Reserved for acceptance-bearing outputs whose content is a deterministic function of the artifact's verified behavior (the conformance digest), not a constant pass-marker.
- `free`: the output may differ across independent realizations. Not acceptance-bearing. Excluded from the cross-machine relation.

Validator-bounded acceptance is `exact` applied to the output that carries the conformance digest. An `exact` mark on a constant output is meaningless; the acceptance output must be behavioral so the mark has content.

### Cross-machine relation in `compare-runs`

Replace global root identity with three scoped checks:

1. **Cache path is deterministic.** M1 root must equal M2 root exactly. If not, violation `m1_m2_root_identical` fails. This preserves the existing guarantee that cache reuse is bitwise materialization.

2. **Re-realization is validator-bounded.** Build the set of acceptance-bearing outputs from declared `equivalence` (every output not marked `free`, across all rules). For each acceptance output, M3's hash must equal M1's hash, matched by `path`, not position. Any mismatch is a violation `m3_declared_equivalence`. `free` outputs are excluded before comparison. If the seed declared nothing, default all outputs to `exact` (preserves current strictness for designs that never opt in).

3. **Cost comparability uses the declared tolerance.** Keep this a hard violation when out of bound.

Add an observational `convergence` block that never flips `equivalent`:

```json
"convergence": {
  "m1_m3_same_root": false,
  "acceptance_outputs": ["readers/VERIFIED"],
  "acceptance_outputs_match": true,
  "free_outputs": ["readers/generated_reader.py", "readers/gate-report.txt"]
}
```

### Declaring equivalence in the seed design

Add an optional per-rule `equivalence` map keyed by output path. Unlisted outputs default to `exact`. Example for `core-bootstrap`:

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

Constraints: `equivalence` is metadata for `compare-runs` only. It must not enter the seal preimage or the build root. Keep `outputs` as `list[str]`. The build transaction must continue to receive a plain string list. Do not overload `outputs`.

### Binding acceptance to behavior

The `core-bootstrap` validate rule must run the conformance gate, not just `py_compile`. The gate stamps a conformance digest — a SHA-256 of the reader's correct outputs on frozen vectors — instead of a constant. The conformance digest is constant across all *correct* readers, because the frozen `.root` values are fixed. A reader that computes a wrong root fails the gate before any stamp is written, so it cannot produce the digest. Two machines matching on `VERIFIED` is a real statement of behavioral equivalence, not "both compiled."

### Declared cost tolerance

Add a top-level seed field:

```json
"cost_tolerance": { "ratio": [0.5, 2.0] }
```

`compare-runs` reads this. If absent, default to ratio `[0.5, 2.0]`. This replaces hard-coded epsilon values. The point is to source the bound from the seed, not from code.

# Gate D: Cache reuse

Goal:

```text
Machine 2 can reuse Machine 1's realized residue at zero oracle cost without trusting unverified imported files.
```

Current status:

```text
Yellow / Red. CLI cache export/import and reuse-only mode now exist in some form. Tar member validation has improved. The blocker is cache-hit trust. A cache entry can still be poisoned by changing `outputs.json`, imported, and materialized at zero cost. Imported residue must be verified before reuse.
```

| Rank | Status | Task | Files to inspect | Claude Code prompt |
|---:|---|---|---|---|
| D1 | Blocker | Validate cache hits before materialization | `src/husks/build/cache.py`, `src/husks/build/eval.py`, tests | Before returning a cache hit, verify recipe digest, declared output names, output hashes, seal schema, and content availability. Reject entries whose output set differs from the current rule. Add a regression that poisons `outputs.json` and proves reuse-only halts. |
| D2 | Blocker | Store `seal.json` and output hashes by default | `src/husks/build/eval.py`, `src/husks/build/cache.py`, tests | Cache entries should contain enough sealed information to verify residue without trusting `outputs.json`. If `seal_data` is optional internally, beta oracle outputs should still write it by default. |
| D3 | Blocker | Make imported cache bundles self-describing | `src/husks/build/cache.py`, tests | Ensure export bundles include a manifest with format version, created timestamp, entry count, entry roots, and optional source site root. Import should validate the manifest and fail clearly if missing or inconsistent. |
| D4 | Partial | Keep safe tar import strict | `src/husks/build/cache.py`, tests | Preserve rejection of absolute paths, `..`, symlinks, hardlinks, devices, oversized members, and unexpected names. Do not reintroduce raw `tar.extract(...)`. |
| D5 | Partial | Reconcile cache CLI shape | `src/husks/cli/commands.py`, docs, tests | Choose either `husks cache-export/cache-import` or nested `husks cache export/import`. Make docs, tests, and beta script match exactly. Optional aliases are fine, but one form must be canonical. |
| D6 | Partial | Prove `--reuse-only` makes no oracle calls | `src/husks/cli/commands.py`, `src/husks/build/run.py`, tests | The Machine 2 acceptance test must use CLI `--reuse-only`. Missing or invalid cache entries should halt with a reuse-miss style failure and zero oracle calls. |
| D7 | Partial | Keep cache reuse report fields stable | `src/husks/report.py`, `src/husks/build/eval.py`, tests | A cache-satisfied rule should report `reused=true`, `paid_cost=0`, `oracle_calls=0`, source cache identity, and output root. |

Exit criteria:

```text
- Machine 1 exports a portable cache bundle by CLI.
- Machine 2 imports it by CLI.
- Machine 2 runs with `--reuse-only`, makes no oracle calls, and reports reuse.
- A poisoned imported cache entry cannot materialize as a successful zero-cost build.
```

## Commit-gate cache promotion

A killed or halted run currently leaves a servable, exportable cache entry for an oracle output that never passed its consuming gate. A rerun then serves that poisoned entry. By the system's stance a non-committed realization must leave no reusable residue.

Root cause: `cache_put` fires inside the oracle rule's own block, right after `write_seal`, gated only on `recipe.type == "oracle"` and cache-not-disabled. It has no knowledge of the downstream gate or the build's final status. So the cache reflects "the oracle produced a nonempty file," not "the realization committed."

Required semantics — separate two promotions that are currently fused:

1. **Site promotion** (unchanged): the oracle output is written into the live site per rule, so the consuming gate can read and test it.
2. **Cache promotion** (new): the oracle output becomes a servable, exportable cache entry only when the build reaches `committed`.

Mechanism:

- In the oracle rule block, replace the immediate `cache_put` with a staged write to a pending cache area (e.g. `.cache/_pending/<key>/`), recording everything `cache_put` needs.
- At build end, promote pending entries into the servable cache only when `S["status"] == "committed"` (via `cache_promote_pending`).
- On `halt`, or if the run ends without reaching `committed`, discard the pending area. Do not promote.
- `cache_get` and lookup read only the servable cache, never `_pending`. A SIGKILL mid-run leaves only an unpromoted pending area, which is never a hit.

Status (shipped in `a143da7`): `cache_put_pending`, `cache_promote_pending`, and `cache_discard_pending` exist in `src/husks/build/cache.py`; eval stages oracle outputs to `_pending`; run promotes on committed and discards on halt; export skips `_pending`.

Remaining defect: promotion does not filter by run. `cache_promote_pending` iterates the whole `_pending` directory and promotes every entry, regardless of which run created it. The fix: pending entries already record `created_run_id` in `meta.json`, so `cache_promote_pending` must promote only entries whose `created_run_id == S["run-id"]`, and best-effort GC foreign orphans.

Export must refuse non-committed builds (shipped): `_cmd_cache_export` skips `_pending`, so a halted build exports zero entries.

Keep the existing `cache-write-failed` nonfatal behavior: a failure to promote at commit must not corrupt an already-sealed build.

# Gate E: Independent re-realization

Goal:

```text
Machine 3 can build from the same seed design with an empty cache and achieve a valid result at cost comparable to Machine 1.
```

Current status:

```text
Yellow / Red. The beta seed now exists outside tests, which fixes the prior file-inventory failure in part. It is still too weak for beta. The seed depends on stub behavior, uses `tools: []`, manually copied inputs in tests, and a validator that mostly checks non-empty output.
```

| Rank | Status | Task | Files to inspect | Claude Code prompt |
|---:|---|---|---|---|
| E1 | Blocker | Make `examples/beta_seed` live-capable and stub-capable | `examples/beta_seed/design.json`, validator, docs, tests | Give the oracle the tools needed to read the prompt and write the declared output, such as `read-file` and `write-file`, if those are the correct tool names. Stub mode should still pass. Live mode should have a clear gated path. |
| E2 | Blocker | Strengthen the beta seed validator | `examples/beta_seed`, tests | Replace non-empty validation with a deterministic contract. The output should include a required token, structured field, checksum, or other invariant that proves the oracle followed the seed task. |
| E3 | Blocker | Remove manual test-only input copying | `tests/test_beta_three_machine.py`, `tests/test_three_machine_cli_acceptance.py`, `examples/beta_seed` | The acceptance test should rely on declared `site_inputs`, not manual `shutil.copy()` into every machine site. |
| E4 | Partial | Add cost comparability tolerance | `src/husks/report.py`, compare-runs code, tests | For stub tests, compare oracle-call count or synthetic cost. For live tests, allow a documented tolerance such as absolute or relative percent difference. |
| E5 | Partial | Add optional live marker, not a default live dependency | `tests/test_beta_three_machine_live.py`, docs | Add a marker-gated live test that uses the same seed and same report schema. Default beta smoke remains stub-safe. |
| E6 | Done, protect | Preserve missing-output failure behavior | `src/husks/build/eval.py`, tests | Keep the rule that an oracle or trial winner omitting any declared output halts, writes no seal, and promotes no partial artifacts. |
| E7 | New | Add a file-inventory guard to the acceptance test | `tests/test_three_machine_cli_acceptance.py`, `examples/beta_seed`, docs | Before running acceptance, assert the expected seed files exist on disk: design, prompt, validator or validation command, and README. This prevents an implementation agent from writing files and then forgetting to stage or reference them. |

Exit criteria:

```text
- The beta seed exists outside tests and is referenced by tests and docs.
- Machine 1 and Machine 3 independently build valid artifacts from that seed.
- Machine 3 cost is comparable to Machine 1 by explicit tolerance.
- The seed works in stub mode and has a clear live-mode path.
```

## Live equivalence acceptance criteria

A live three-machine run (M1 live oracle, M2 cache reuse, M3 live oracle) returns `equivalent: true`, exit 0, with divergent build roots and matching `VERIFIED` conformance digests.

Acceptance is behavioral: `VERIFIED` carries the conformance digest, and a reader that compiles but computes a wrong root fails the gate and never seals.

`compare-runs` enforces: M1==M2 root, M3 validator-bounded acceptance on the conformance digest, cost within declared tolerance. It reports M1/M3 root convergence observationally only.

The seed design states the per-output equivalence form and the cost tolerance, satisfying white paper Section 5.

Build root is unchanged by the new metadata. The `equivalence` and `cost_tolerance` fields do not enter the seal preimage or the build root.

# Gate F: Ledger and cost comparability

Goal:

```text
Each run emits one machine-readable report proving cost, reuse, validity, and comparability.
```

Current status:

```text
Yellow. Usage accounting and reports have improved. The bloat risk is that report fields, trace events, history records, cache metadata, and CLI JSON each carry overlapping facts. For beta, centralize only the fields used by acceptance.
```

| Rank | Status | Task | Files to inspect | Claude Code prompt |
|---:|---|---|---|---|
| F1 | Blocker | Define one beta report contract | `src/husks/report.py`, `src/husks/cli/commands.py`, tests | Create one documented JSON contract for `run --json`. It must include status, artifact validity, output root or hashes, oracle calls, paid oracle cost, cache reuse, reused nodes, failed rule, failure class, and committed output state. |
| F2 | Blocker | Make report generation the only source for acceptance fields | `src/husks/report.py`, `src/husks/build/eval.py`, usage code | Do not let `compare-runs` infer cost or reuse from trace internals, history files, or ad hoc CLI text. It should consume the beta report contract. |
| F3 | Partial | Introduce a small `BuildLedger` or centralized equivalent | `src/husks/report.py`, `src/husks/build/eval.py`, `src/husks/oracle/kernel.py`, usage code | Keep this minimal. A ledger can be a small event container or normalized report builder. Do not perform a large rewrite before beta. |
| F4 | Partial | Separate build-rule fuel from oracle tool-step fuel | `src/husks/build/eval.py`, `src/husks/oracle/kernel.py`, `src/husks/report.py`, tests | Report build-rule fuel and oracle tool-step fuel as distinct fields. Do not mix them in acceptance comparison. |
| F5 | Partial | Ensure failed runs produce JSON | `src/husks/report.py`, `src/husks/cli/commands.py`, tests | A failed Machine 1, 2, or 3 run should emit JSON explaining failure class, failed rule, error, cost so far, and whether declared outputs were committed. |
| F6 | Done, protect | Preserve trace reset per build | `src/husks/build/run.py`, `src/husks/utils/events.py`, tests | Keep regressions showing builds in one process do not contaminate each other's reports. |
| F7 | Defer | Rich trial summaries | `src/husks/report.py`, `src/husks/build/eval.py` | Defer unless the beta seed uses trials. Do not add report complexity for unused beta behavior. |

Exit criteria:

```text
- `run --json` is sufficient evidence for cost, validity, reuse, and failure diagnosis.
- `compare-runs` uses only the beta report contract.
- Cache reuse reports zero paid oracle calls and zero paid oracle cost.
- Failed runs still produce useful JSON.
```

# Gate G: Release smoke and three-machine acceptance

Goal:

```text
The beta proof can be run from a clean checkout or installed package.
```

Current status:

```text
Red / Yellow. CLI support is closer, but direct subprocess tests still fail unless `PYTHONPATH=src` is exported. The CLI acceptance test is not yet fully CLI-only, docs disagree with command names, and there is no wheel/install smoke.
```

| Rank | Status | Task | Files to inspect | Claude Code prompt |
|---:|---|---|---|---|
| G1 | Blocker | Make the three-machine test truly CLI-only | `tests/test_three_machine_cli_acceptance.py`, `tests/test_beta_three_machine.py`, CLI code | Remove Python API calls for cache export/import from the acceptance path. Machine 1, 2, and 3 must use only documented CLI commands. |
| G2 | Blocker | Use `--reuse-only` in Machine 2 acceptance | `tests/test_three_machine_cli_acceptance.py`, CLI code | Machine 2 must run with CLI `--reuse-only`. A test that reuses cache without `--reuse-only` is not the beta proof. |
| G3 | Blocker | Fix subprocess CLI helper and migrate tests | `tests/conftest.py`, CLI tests | Create one helper that sets absolute `PYTHONPATH`, has a timeout, supports temp cwd, captures stdout and stderr, and prints useful failure output. Replace ad hoc `subprocess.run` calls in beta-relevant tests. |
| G4 | Blocker | Add clean wheel/install smoke | `pyproject.toml`, tests, CI | Build a wheel, install it in a clean venv, then run `husks doctor`, `husks init`, `husks check`, `husks run --stub`, `husks status --json`, and the stub three-machine proof. |
| G5 | Partial | Reconcile docs with CLI command names | `README.md`, `docs/liquid-beta.md`, `examples/beta_seed/README.md`, CLI code | Make docs, tests, and command parser agree. Fix stale command references and case-sensitive doc links. |
| G6 | Partial | Split doctor into core and live readiness | `src/husks/cli/commands.py`, doctor code, tests | Default `husks doctor` should pass for core and stub installs. Missing live-oracle dependencies should fail only under `doctor --live` or equivalent. |
| G7 | Partial | Standardize beta exit codes | `src/husks/cli/helpers.py`, `src/husks/cli/commands.py`, tests | Define stable exit codes for success, validation failure, build halt, reuse miss, verification failure, and internal error. Add tests only for beta commands. |
| G8 | Partial | Make JSON acceptance commands quiet | `src/husks/cli/commands.py`, tests | `run --json`, cache import/export JSON, status JSON, and compare-runs JSON should write parseable JSON only to stdout. |

Exit criteria:

```text
- The acceptance script can be copied from docs and run.
- The CLI produces parseable JSON for every acceptance step.
- A clean wheel install can run the stub beta proof.
- The test suite does not rely on accidental local import state.
```

# Gate H: Bloat control and consolidation

Goal:

```text
Pass beta without letting the codebase accrete a second implementation of every beta concept.
```

Current status:

```text
Yellow / Red. The code is not badly bloated by line count, but it is beginning to duplicate policy. This gate is not about deleting working code. It is about extracting the repeated beta invariants into one place each.
```

| Rank | Status | Task | Files to inspect | Claude Code prompt |
|---:|---|---|---|---|
| H1 | Blocker | Consolidate CLI subprocess execution in tests | `tests/conftest.py`, tests | Replace beta-relevant ad hoc subprocess calls with one helper. This reduces test bloat and fixes the PYTHONPATH subprocess failure. |
| H2 | Blocker | Centralize beta report schema | `src/husks/report.py`, `src/husks/cli/commands.py`, tests | Define one report contract consumed by `compare-runs`. Remove or avoid duplicate JSON assembly in CLI commands. |
| H3 | Blocker | Keep cache validation behind one cache API | `src/husks/build/cache.py`, `src/husks/build/eval.py`, tests | `eval.py` should ask cache for a verified hit. It should not reimplement cache schema checks. The cache module should own import safety, entry validation, provenance, and poisoning checks. |
| H4 | Partial | Split only the command code touched by beta | `src/husks/cli/commands.py`, `src/husks/cli/` | If cache and compare commands make `commands.py` worse, move them into small command modules. Do not perform a full CLI rewrite before beta. |
| H5 | Partial | Extract site input normalization | `src/husks/designs/ir.py`, `src/husks/build/site.py`, `src/husks/build/run.py` | Create one helper for resolving, validating, and materializing `site_inputs`. Avoid separate behavior in check, run, and tests. |
| H6 | Partial | Keep beta seed single-sourced | `examples/beta_seed`, `src/husks/setup.py`, tests | Avoid separate inline seed designs in multiple tests. Tests should reference or copy the canonical example. |
| H7 | Defer | Broad module splitting | all source | Do not split every large module before beta. Split only where it removes direct duplication on the acceptance path. |

Exit criteria:

```text
- One helper runs CLI subprocesses in tests.
- One report contract feeds acceptance comparison.
- One cache API validates imported residue.
- One site-input helper defines seed portability.
- One beta seed is used by docs and tests.
```

# Suggested implementation sequence from Husks-main (16)

Do this order:

```text
1. Add or fix the shared CLI subprocess helper and migrate beta-relevant tests.
2. Fix relative `site_inputs` and require declared inputs to exist.
3. Remove manual input copying from the three-machine tests.
4. Strengthen `examples/beta_seed` so it is stub-capable, live-capable, and deterministically validated.
5. Make Machine 2 use CLI `--reuse-only` in acceptance.
6. Make cache hits seal-validated before materialization.
7. Add cache poisoning regressions.
8. Reconcile cache CLI names across docs and tests.
9. Add `compare-runs --json` using only the beta report contract.
10. Centralize the beta report fields needed by acceptance.
11. Add a clean wheel/install smoke test.
12. Split `doctor` into core readiness and live readiness.
13. Optionally split touched CLI/cache/report helpers if the files become harder to audit.
```

This order deliberately puts bloat reduction where it pays for beta: tests, report schema, cache validation, site input resolution, and seed fixtures.

# Updated single Claude Code umbrella prompt

```text
Implement the next Husks beta pass against the three-machine proof, while reducing code accretion on the beta path.

Do not broaden scope. The target is:

Machine 1 receives a seed design, empty cache, and oracle access. It builds a valid artifact, reports paid oracle cost C1, and exports reusable residue.

Machine 2 receives the same seed design plus an imported cache from Machine 1. It runs with CLI --reuse-only, materializes a verified cache hit, reports reuse, reports zero paid oracle cost, and makes zero oracle calls.

Machine 3 receives only the same seed design, an empty cache, and oracle access. It independently builds a valid artifact and reports cost C3 comparable to C1.

Current repo state:

- Transactions are mostly done. Preserve them.
- Artifact identity is mostly done. Preserve it.
- Cache CLI and reuse-only exist in some form, but cache-hit validation is not strong enough.
- The beta seed exists, but it is not yet portable or live-capable enough.
- The CLI acceptance path is not fully CLI-only.
- Subprocess CLI tests still rely on accidental PYTHONPATH state.
- Report, cache, CLI, and test policy are beginning to duplicate beta concepts.

Implement in this order:

1. Create one shared CLI subprocess test helper that sets absolute PYTHONPATH, uses timeouts, captures output, and supports temp cwd. Migrate beta-relevant CLI tests to it.
2. Resolve relative site_inputs against the design file path and require declared site inputs to exist before execution.
3. Remove manual input copying from the three-machine tests. Use the canonical beta seed inputs.
4. Strengthen examples/beta_seed so it is stub-capable, live-capable, and validated by a deterministic contract.
5. Make the Machine 2 acceptance path use CLI --reuse-only.
6. Make cache hits verified residue. Store seal and output hashes by default, validate recipe digest, declared output names, output hashes, seal schema, and content availability before materialization.
7. Add a cache poisoning regression where outputs.json is modified and reuse-only must halt.
8. Reconcile cache command names across CLI, docs, and tests. Pick one canonical form.
9. Add compare-runs --json. It must consume m1.json, m2.json, and m3.json and check validity, roots or declared hashes, seal validity, Machine 2 reuse, Machine 2 zero oracle calls, and Machine 3 cost tolerance.
10. Define one beta report contract used by run --json and compare-runs. Avoid duplicate JSON assembly in CLI code.
11. Add a clean wheel/install smoke test for doctor, init, check, run --stub, status --json, and the stub three-machine proof.
12. Split doctor into core/stub readiness and live-oracle readiness.

Bloat constraints:

- Do not add another report schema.
- Do not add another cache schema.
- Do not add another beta seed fixture.
- Do not add another subprocess helper.
- Keep eval.py asking cache.py for verified hits rather than duplicating cache validation.
- Split files only when the split removes duplication on the beta path.

Preserve existing passing transaction, output policy, manifest, root verification, and import hardening tests. Add regressions for every fixed blocker.
```

# Non-goals before beta

Do not spend beta time on:

```text
- Making Husks a general agent framework.
- Remote registries.
- Blockchain storage.
- Complex UI or graph polish.
- Full documentation rewrite.
- Directory outputs.
- Elaborate shell environment modeling.
- Large plugin systems.
- Broad ergonomics beyond init, check, run, status, explain, cache, compare-runs, and doctor.
- Rich trial reporting unless the beta seed uses trials.
- Broad line-count reduction unrelated to the three-machine proof.
```

# Parking lot after beta

```text
- Remote cache registry.
- Merkle registry for CSE strings or residue.
- Advanced graph rendering.
- Directory-output support.
- Binary trial outputs.
- Rich report UI.
- Advanced shell environment capture.
- Multi-target graph visualization.
- Full plugin architecture.
- Release packaging polish beyond the beta wheel smoke.
- Full CLI module reorganization beyond beta-touched commands.
```
