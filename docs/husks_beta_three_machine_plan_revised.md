# Husks Beta Build Plan: Three-Machine Problem

Revised after review of `Husks-main (14).zip`.

This plan narrows the remaining beta work to the three-machine proof. It assumes the current repo already contains substantial machinery for transactions, artifact identity, cache internals, and an internal three-machine smoke test. The remaining work is to make the proof clean, secure, user-runnable, and installable.

## Beta acceptance target

Husks beta is reached when this workflow passes from a clean checkout or installed package:

```text
Machine 1: same seed design + empty cache + oracle access
  -> builds a valid artifact
  -> reports paid oracle cost C1
  -> exports reusable residue

Machine 2: same seed design + imported cache from Machine 1 + no oracle use
  -> rebuilds or materializes the same or equivalent artifact
  -> reports zero or near-zero oracle cost
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

## Current beta posture

```text
Gate A: Seed design portability                Red / Yellow
Gate B: Transactional execution                Green
Gate C: Artifact identity and equivalence      Green / Yellow
Gate D: Cache reuse                            Yellow
Gate E: Independent re-realization             Yellow
Gate F: Ledger and cost comparability          Yellow
Gate G: Release smoke and acceptance           Red / Yellow
```

The current code has most of the beta machinery. The beta proof is not yet a user-runnable gated workflow. The highest value work is now CLI wiring, seed portability, cache import safety, and release smoke testing.

## Beta definition

```text
Beta = seed portability
     + transactional execution
     + sealed artifact identity
     + cache reuse
     + independent re-realization
     + cost comparability
     + a user-runnable three-machine acceptance test
```

Do not broaden the scope beyond this proof.

## Development rule

Use the three-machine smoke test as the development spine.

The repo already has an internal three-machine test. The next step is to turn that into a CLI-level acceptance workflow that matches the intended beta proof.

Do not prioritize broad features, polish, remote registries, graph UI, or general agent framework ergonomics unless they directly support the three-machine proof.

# Revised Beta Gates and Task List

## Beta Gate A: Seed design portability

Goal:

```text
A seed design can move to a clean machine and build without repo-local assumptions, hidden state, or test-only fixtures.
```

Current status:

```text
Partial. `site_inputs` exist in lower-level build/check paths, but JSON design execution does not fully thread them from parse to build. Unknown fields are still accepted silently. `husks init` does not yet produce a seed that passes the default stub run.
```

| Rank | Status | Prior IDs | Task | Files to inspect | Claude Code prompt |
|---:|---|---|---|---|---|
| A1 | Blocker | 39 | Thread `site_inputs` from JSON design to build execution | `src/husks/designs/ir.py`, `src/husks/build/run.py`, `src/husks/build/site.py`, `src/husks/core.py`, tests | Make top-level `site_inputs` in JSON designs flow through parse, compile, run, check, and build. Support list and dict forms. Add CLI tests proving a seed design with declared site inputs builds from a clean site without repo-local files. |
| A2 | Blocker | 43 | Reject unknown design fields | `src/husks/designs/ir.py`, `src/husks/cli/commands.py`, tests | Define allowed top-level fields and rule-level fields. Fail validation on unknown fields. Add regressions for `ouputs`, `taget`, `fuell`, and unknown top-level fields. Error messages should name the bad field and the nearest valid field when obvious. |
| A3 | Partial | 41, 42 | Improve graph validation diagnostics | `src/husks/designs/ir.py`, tests | Keep current validation behavior, but improve messages for forward references, circular dependencies, and duplicate outputs. Duplicate output errors should name both producers. |
| A4 | Partial | 40 | Define conditional seed identity semantics | `src/husks/build/eval.py`, `src/husks/core.py`, `src/husks/designs/transport.py`, tests, docs | Decide and document whether conditionals bind both branches or only the executed branch into artifact identity. Add tests showing that a seed design remains portable under the chosen semantics. |
| A5 | Blocker | 47 | Make `husks init` produce a valid beta seed project | `src/husks/setup.py`, examples, tests | Fix the generated project so `husks init`, `husks check`, and `husks run --stub` all pass in a temp directory. Treat this as the default seed-design example for beta. |
| A6 | New | New | Add a canonical beta seed directory | `examples/`, `docs/`, tests | Create `examples/beta-seed/` with a minimal seed design, validator, expected output contract, and README. The example must work from a clean checkout and from an installed wheel. |

Exit criteria:

```text
- A JSON seed with declared site inputs builds from a clean directory.
- Unknown fields fail before execution.
- `husks init && husks check && husks run --stub` succeeds.
- The beta seed example is not embedded only in tests.
```

## Beta Gate B: Transactional execution

Goal:

```text
A build cannot corrupt the live site. Outputs commit only after validation.
```

Current status:

```text
Mostly complete. `BuildTransaction` exists. Staging, validation, promotion, rollback, live-site bypass blocking, regular-file output policy, import hardening, and shlex reader parsing are present. Keep this gate stable and add only beta-critical regressions.
```

| Rank | Status | Prior IDs | Task | Files to inspect | Claude Code prompt |
|---:|---|---|---|---|---|
| B1 | Done, keep tests | 1, 3 | Preserve `BuildTransaction` behavior | `src/husks/build/eval.py`, `src/husks/build/site.py`, tests | Do not redesign the transaction layer before beta. Preserve staging, validation, promotion, and rollback. Add regressions only if a later cache or CLI change touches transaction behavior. |
| B2 | Done, keep tests | 4, 5 | Preserve Python live-site bypass blocking | `src/husks/build/site.py`, `src/husks/build/eval.py`, tests | Keep the rule that successful Python actions cannot seal outputs written directly to the live site. Declared outputs must come through staged write paths. |
| B3 | Done, keep tests | 16, 38 | Preserve beta output policy | `src/husks/build/eval.py`, `src/husks/build/site.py`, `src/husks/designs/ir.py`, tests | Keep beta outputs limited to regular files. Directories, symlinks, broken symlinks, and special files must halt before sealing. |
| B4 | Done, keep tests | 23, 24 | Preserve import and symlink hardening | `src/husks/build/site.py`, `src/husks/designs/ir.py`, tests | Keep runtime validation for import local names, internal paths, path traversal, output collisions, and existing symlinks pointing to the wrong target. |
| B5 | Done, explicit policy | 36 | Keep trial outputs text-only for beta | `src/husks/build/eval.py`, tests | Preserve the explicit text-only beta policy unless binary trial outputs become necessary for the three-machine proof. Add clear errors for binary outputs. |
| B6 | Done, keep tests | 17 | Preserve `shlex.split()` reader command parsing | `src/husks/gate.py`, `src/husks/cli/commands.py`, tests | Keep quoted-command regressions. Avoid reintroducing raw `.split()`. |
| B7 | New blocker across B/D | New | Fix post-promotion cache write failure semantics | `src/husks/build/eval.py`, `src/husks/build/cache.py`, tests | If outputs have been promoted and sealed, a later cache write failure must not leave a confusing half-failed build. Either make cache population nonfatal after seal publication, or perform cache population before final seal publication, or roll back the seal and report the exact state. Add a regression. |

Exit criteria:

```text
- Failed validation commits no declared outputs and writes no seal.
- Live-site bypass cannot produce a sealed success.
- Cache failures cannot corrupt the transaction story.
```

## Beta Gate C: Artifact identity and equivalence

Goal:

```text
Outputs can be compared and verified across machines.
```

Current status:

```text
Mostly complete at the library level. Recipe identity, manifest validation, root verification, hashing semantics, CSE version language, and artifact comparison exist. Remaining work is sharper diagnostics and CLI exposure for acceptance.
```

| Rank | Status | Prior IDs | Task | Files to inspect | Claude Code prompt |
|---:|---|---|---|---|---|
| C1 | Done, audit once | 30 | Audit recipe identity correctness | `src/husks/build/identity.py`, `src/husks/build/nodes.py`, tests | Confirm shell command identity, Python action identity, oracle recipe identity, inputs, outputs, and parameters are all included in recipe digests. Add invalidation tests for any uncovered field. |
| C2 | Partial | 26 | Improve invalid manifest diagnostics | `src/husks/manifest.py`, `src/husks/build/seal.py`, tests | Keep strict manifest schema and version validation, but return or expose clearer invalid-state reasons. Unsupported or corrupt manifests should not silently degrade to an uninformative state. |
| C3 | Done, expose in acceptance | 27 | Use root verification in acceptance comparison | `src/husks/core.py`, `src/husks/manifest.py`, `src/husks/cli/commands.py`, tests | Preserve root recomputation and `status --json` root validity. Ensure the three-machine acceptance path fails if any site has an invalid root. |
| C4 | Done, keep tests | 37 | Preserve normalized file hashing semantics | `src/husks/core.py`, `src/husks/build/site.py`, `src/husks/manifest.py`, tests | Keep absent files, regular files, and unsupported paths represented consistently across seal, manifest, status, and verification. |
| C5 | Done, keep docs aligned | 29 | Preserve aligned CSE version language | `src/husks/core.py`, `src/husks/designs/transport.py`, `spec/`, docs | Keep wire version, spec labels, and code constants consistent. Update docs if future naming changes. |
| C6 | Partial | New | Expose artifact equivalence through a beta CLI command | `src/husks/cli/commands.py`, `src/husks/manifest.py`, `src/husks/core.py`, tests | Add `husks compare-runs` or equivalent. It should compare Machine 1, 2, and 3 JSON reports by artifact validity, output roots, declared output hashes, seal validity, cache reuse, oracle calls, and cost tolerance. |
| C7 | New | New | Make comparison output machine-readable and quiet | `src/husks/cli/commands.py`, `src/husks/report.py`, tests | `compare-runs --json` should emit valid JSON only. No console banners or mixed text. Include a concise failure reason for each failed acceptance invariant. |

Exit criteria:

```text
- Two sites or reports can be compared by output root, declared hashes, and seal validity.
- Three-machine comparison is available from the CLI.
- Invalid manifests and invalid roots fail the acceptance path with clear JSON.
```

## Beta Gate D: Cache reuse

Goal:

```text
Machine 2 can reuse Machine 1's realized residue at zero or near-zero oracle cost.
```

Current status:

```text
Partial. Cache layout, lookup, export/import functions, reuse-only internals, and reuse accounting exist. The missing beta work is CLI wiring, safe import, and stronger cache-hit validation.
```

| Rank | Status | Prior IDs | Task | Files to inspect | Claude Code prompt |
|---:|---|---|---|---|---|
| D1 | Done, keep format stable | New | Freeze the beta cache layout | `src/husks/build/cache.py`, `src/husks/build/run.py`, tests | Treat the current filesystem cache layout as the beta format unless a specific acceptance blocker appears. Document the minimal layout: realized outputs, seals, recipe identity, output hashes, and metadata. |
| D2 | Done, strengthen validation | New | Validate cache hits before materialization | `src/husks/build/eval.py`, `src/husks/build/cache.py`, tests | Before materializing a cache hit, verify recipe identity, declared output names, output hashes, seal schema, and content availability. Reject cache entries whose output set differs from the current rule. |
| D3 | Blocker | New | Add `husks cache export` and `husks cache import` | `src/husks/cli/main.py`, `src/husks/cli/commands.py`, `src/husks/build/cache.py`, tests | Wire cache export/import into the CLI exactly enough for the beta script. The commands should accept cache paths and tarball paths, emit JSON when requested, and return stable exit codes. |
| D4 | Blocker | New | Replace raw tar extraction with safe cache import | `src/husks/build/cache.py`, tests | Do not use raw `tar.extract(...)` for imported cache bundles. Reject absolute paths, `..`, symlinks, hardlinks, devices, unexpected file names, unexpected directory names, and oversized members. Add adversarial tar tests. |
| D5 | Blocker | New | Add `husks run --reuse-only` | `src/husks/cli/main.py`, `src/husks/cli/commands.py`, `src/husks/build/run.py`, tests | Expose reuse-only mode through the CLI. In reuse-only mode Husks may materialize valid cache hits, but must not call the oracle. A missing cache entry should halt clearly with a reuse-miss exit code. |
| D6 | Partial | 6, 22 | Record cache reuse in the report contract | `src/husks/build/eval.py`, `src/husks/report.py`, usage code, tests | Ensure a cache-satisfied rule reports `reused=true`, `paid_cost=0`, `oracle_calls=0`, source cache identity, and output root. This should be present in `run --json`. |
| D7 | New | New | Add cache provenance to exported bundles | `src/husks/build/cache.py`, `src/husks/report.py`, tests | Include a small export manifest with cache format version, created timestamp, entry count, entry roots, and optional source site root. Validate this manifest on import. |

Exit criteria:

```text
- Machine 1 can export a portable cache bundle by CLI.
- Machine 2 can import it by CLI.
- Machine 2 can run with `--reuse-only` and make no oracle calls.
- Cache import is safe against malicious tar members.
- Cache hits are validated before materialization.
```

## Beta Gate E: Independent re-realization

Goal:

```text
Machine 3 can build from the same seed design with an empty cache and achieve a valid result at cost comparable to Machine 1.
```

Current status:

```text
Partial. The repo has an internal three-machine test under stub behavior. The seed is still test-local, cost comparability is synthetic, and the proof is not yet exposed as a clean CLI workflow.
```

| Rank | Status | Prior IDs | Task | Files to inspect | Claude Code prompt |
|---:|---|---|---|---|---|
| E1 | Blocker | New | Promote the beta seed from test fixture to example | `examples/`, `src/husks/setup.py`, tests | Create a deterministic beta seed example that requires an oracle or stub oracle under normal mode, validates output deterministically, and can be run twice with comparable cost. Do not keep the only seed inside `tests/test_beta_three_machine.py`. |
| E2 | Partial | New | Add clean-machine CLI re-realization test | `tests/test_beta_three_machine.py`, CLI helpers | Extend the current test so Machine 1 and Machine 3 run through the CLI in separate temp directories with separate empty caches. Assert both produce valid outputs and comparable oracle-call count or synthetic cost. |
| E3 | Done, keep tests | 35 | Preserve missing-output failure behavior | `src/husks/build/eval.py`, tests | Keep the rule that an oracle or trial winner that omits any declared output halts, writes no seal, and promotes no partial artifacts. |
| E4 | Partial | 21 | Make model selection explicit for live beta runs | `src/husks/cli/main.py`, `src/husks/cli/commands.py`, `src/husks/oracle/llm.py`, doctor code | Ensure Machine 1 and Machine 3 can run with the same model configuration. `doctor --live` should accept a model or provider setting and validate that live oracle path separately from stub/core readiness. |
| E5 | Partial | New | Define cost-comparability tolerance | `src/husks/report.py`, beta tests, compare command | Add a beta comparison helper that checks Machine 3 cost against Machine 1 using a configurable tolerance. For stub tests, compare oracle-call count or synthetic cost. For live tests, allow a documented tolerance. |
| E6 | New | New | Add optional live three-machine test marker | `tests/test_beta_three_machine_live.py`, docs | Add a skipped-by-default or marker-gated live version of the three-machine proof. It should use the same seed and report schema as the stub test, but require explicit environment configuration. |

Exit criteria:

```text
- The beta seed exists outside tests.
- Machine 1 and Machine 3 independently build valid artifacts from the same seed.
- Machine 3 cost is comparable to Machine 1 by an explicit tolerance.
- Live-model configuration is reproducible enough for the proof.
```

## Beta Gate F: Ledger and cost comparability

Goal:

```text
Each run emits a machine-readable report proving cost, reuse, validity, and comparability.
```

Current status:

```text
Partial. Usage accounting is much better than before, and JSON reports expose useful fields. The remaining issue is that cost, trace, history, reuse, and report assembly are not yet derived from one explicit ledger object.
```

| Rank | Status | Prior IDs | Task | Files to inspect | Claude Code prompt |
|---:|---|---|---|---|---|
| F1 | Blocker for auditability | 6, 22 | Introduce or emulate `BuildLedger` as the report authority | `src/husks/report.py`, `src/husks/build/eval.py`, `src/husks/oracle/kernel.py`, `src/husks/oracle/llm.py`, usage code | Create a single ledger object, or a clearly centralized equivalent, for rule events, oracle events, trial events, cache reuse, fuel, and cost. Reports should derive from this source rather than stitching together globals, traces, and history files. |
| F2 | Partial | 10, 11 | Separate build-rule fuel from oracle tool-step fuel | `src/husks/build/eval.py`, `src/husks/oracle/kernel.py`, `src/husks/report.py`, tests | Report build-rule fuel and oracle tool-step fuel as distinct fields. Do not mix them in history, JSON reports, or beta comparison. |
| F3 | Partial | 12 | Keep trial branch usage local and explicit | `src/husks/build/eval.py`, tests | Trial branches should return explicit usage. Avoid scanning trace internals for cost. Document whether reports include winning-trial usage, total-trial usage, or both. |
| F4 | Done, keep tests | 13 | Preserve trace reset per build | `src/husks/build/run.py`, `src/husks/utils/events.py`, tests | Keep trace reset behavior and maintain a regression showing that two builds in one Python process cannot contaminate one another's reports. |
| F5 | Defer unless needed | 14 | Add trial summaries only if beta seed uses trials | `src/husks/report.py`, `src/husks/build/eval.py` | If the beta seed does not use trials, keep rich trial reporting post-beta. If trials affect beta cost, add concise trial summaries to JSON reports. |
| F6 | Partial | 15 | Ensure failed builds produce machine-readable reports | `src/husks/report.py`, `src/husks/cli/commands.py`, tests | A failed Machine 1, 2, or 3 run should produce JSON explaining failed rule, stale reason, error, cost so far, whether any outputs were committed, and whether the failure was validation, reuse miss, or internal error. |
| F7 | New | New | Make `run --json` quiet and acceptance-safe | `src/husks/cli/commands.py`, `src/husks/report.py`, tests | Ensure `husks run --json` emits valid JSON only. No banners, progress glyphs, or mixed text on stdout. Human output can go to stderr or non-JSON mode. |

Exit criteria:

```text
- `run --json` is sufficient evidence for cost, validity, reuse, and failures.
- Cost comparability is computed from explicit report fields.
- Cache reuse reports zero paid oracle calls and zero paid oracle cost.
- Failed runs still produce useful JSON.
```

## Beta Gate G: Release smoke and three-machine acceptance

Goal:

```text
The beta proof can be run from a clean checkout or installed package.
```

Current status:

```text
Partial to blocking. The internal three-machine test exists, but the planned CLI workflow does not yet exist. There is no `husks cache` command, no CLI `--reuse-only`, no `compare-runs`, no shared subprocess helper, and no wheel/install smoke test.
```

| Rank | Status | Prior IDs | Task | Files to inspect | Claude Code prompt |
|---:|---|---|---|---|---|
| G1 | Partial | New | Convert the internal three-machine test into a CLI acceptance test | `tests/test_beta_three_machine.py`, CLI/build/cache/report code | Add one end-to-end test simulating Machine 1, Machine 2, and Machine 3 in separate temp directories using only CLI commands. Machine 1 builds with cost. Machine 2 imports cache and reuses with zero oracle cost. Machine 3 builds from seed with empty cache and comparable cost. |
| G2 | Blocker | 20 | Stabilize JSON CLI contracts needed by acceptance | `src/husks/cli/commands.py`, tests | Ensure `run --json`, `status --json`, cache commands, and `compare-runs --json` emit valid machine-readable JSON with no console noise. |
| G3 | Blocker | 18 | Add shared subprocess CLI helper | `tests/conftest.py`, CLI tests | Create a shared subprocess helper using absolute `PYTHONPATH`, timeouts, temp cwd support, and output capture. Replace ad hoc subprocess calls. This should make direct pytest and subprocess CLI tests agree. |
| G4 | Partial | 19 | Make tests root-safe | permission tests, `tests/conftest.py` | Skip or rework chmod/write-denial tests when running as root. The beta suite should distinguish real failures from privileged-runner artifacts. |
| G5 | Blocker | 48, 49 | Add wheel/install smoke test | `pyproject.toml`, resource code, CI/tests | Build a wheel, install it in a clean venv, and run `husks doctor`, `husks init`, `husks check`, `husks run --stub`, `husks status --json`, and the stub beta seed demo. |
| G6 | Partial | 50 | Standardize beta exit codes | `src/husks/cli/helpers.py`, `src/husks/cli/commands.py`, tests | Define stable exit codes for success, validation failure, build halt, reuse miss, verification failure, and internal error. Add tests for beta commands. |
| G7 | New | New | Reconcile docs with actual CLI | `README.md`, `docs/cli.md`, `docs/`, CLI code | Either add compatibility aliases for documented commands or update docs to match real commands. Remove or fix references to missing commands such as `husks selftest`, `husks graph`, `husks diff`, and top-level `husks gate` unless they are actually supported. Fix case-sensitive doc links. |
| G8 | New | New | Split `doctor` into core and live checks | `src/husks/cli/commands.py`, doctor code, tests | Default `husks doctor` should pass for a core/stub install. Missing `litellm` should fail only under `husks doctor --live` or equivalent. This is required for clean beta smoke on machines without live oracle credentials. |

Exit criteria:

```text
- The acceptance script can be copied from docs and run.
- The CLI produces parseable JSON for every acceptance step.
- A clean wheel install can run the stub beta proof.
- The full test suite does not rely on accidental local import state.
```

# Updated three-machine acceptance script

The beta acceptance test should converge on this script shape:

```bash
# Machine 1: original realization
husks run examples/beta-seed/seed.json \
  --site m1-site \
  --cache m1-cache \
  --json > m1.json

# Export cache from Machine 1
husks cache export \
  --cache m1-cache \
  --output husks-cache.tgz \
  --json > cache-export.json

# Machine 2: cached reuse
husks cache import \
  --cache m2-cache \
  --input husks-cache.tgz \
  --json > cache-import.json

husks run examples/beta-seed/seed.json \
  --site m2-site \
  --cache m2-cache \
  --reuse-only \
  --json > m2.json

# Machine 3: independent re-realization
husks run examples/beta-seed/seed.json \
  --site m3-site \
  --cache m3-cache \
  --json > m3.json

# Compare
husks compare-runs \
  m1.json m2.json m3.json \
  --json > beta-comparison.json
```

Expected result:

```text
Machine 1:
  built = true
  artifact_valid = true
  oracle_cost = C1
  oracle_calls > 0
  cache_exported = true

Machine 2:
  reused = true
  artifact_valid = true
  oracle_cost = 0 or near 0
  oracle_calls = 0
  output_root == Machine 1, or equivalence passes

Machine 3:
  built = true
  artifact_valid = true
  oracle_cost = C3
  oracle_calls comparable to Machine 1
  C3 within tolerance of C1
```

# Suggested implementation sequence from current repo state

Start here:

```text
1. Fix JSON `site_inputs` threading.
2. Fix `husks init` so the default stub run succeeds.
3. Reject unknown design fields.
4. Add `husks cache export` and `husks cache import`.
5. Replace raw tar extraction with safe cache import.
6. Add `husks run --reuse-only`.
7. Add cache-hit schema, output-set, and hash validation before materialization.
8. Add `husks compare-runs` with JSON output.
9. Add a shared subprocess CLI helper with timeouts and absolute `PYTHONPATH`.
10. Convert the three-machine proof into a CLI-level acceptance test.
11. Make `run --json` and acceptance commands emit clean JSON only.
12. Add a clean wheel/install smoke test.
13. Split `doctor` into core/stub readiness and live-oracle readiness.
14. Centralize ledger/report fields needed for cost, reuse, and failure diagnosis.
```

This order intentionally puts user-runnable proof ahead of broader refactoring. The ledger cleanup matters, but it should not delay basic CLI cache reuse and acceptance if the current report fields can be stabilized first.

# Single Claude Code umbrella prompt

```text
Implement the remaining Husks beta path around the three-machine problem.

Do not broaden scope. The acceptance target is:

Machine 1 receives a seed design, empty cache, and oracle access. It builds a valid artifact and reports paid oracle cost C1.

Machine 2 receives the same seed design plus an imported/shared Husks cache from Machine 1. It rebuilds or materializes the artifact with zero or near-zero oracle cost, reports cache reuse, and makes no oracle calls under reuse-only mode.

Machine 3 receives only the same seed design, an empty cache, and oracle access. It independently builds a valid artifact and reports cost C3 comparable to C1.

The current repo already has much of the transaction, identity, cache, and internal smoke-test machinery. Focus the next pass on:

1. JSON seed portability, especially `site_inputs`.
2. Unknown-field rejection in designs.
3. A valid `husks init` beta seed.
4. CLI cache export/import.
5. Safe cache tar import.
6. CLI `--reuse-only`.
7. Cache-hit validation before materialization.
8. CLI `compare-runs`.
9. Clean JSON contracts for acceptance.
10. A shared subprocess CLI test helper.
11. A wheel/install smoke test.
12. Core-vs-live `doctor` behavior.
13. Centralized report or ledger fields for cost, reuse, failures, and comparability.

Preserve existing working transaction and artifact identity behavior. Add regression tests for every fixed bug. The three-machine CLI acceptance test is the spine: every beta task should move that test closer to green.
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
```
