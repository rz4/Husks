# Husks Beta Build Plan: Three-Machine Problem

This document is a scoped implementation plan for getting Husks to beta. The beta target is not a complete product. The beta target is the three-machine proof.

## Beta acceptance target

Husks beta is reached when this passes:

```text
Machine 1: seed design + empty cache + oracle access
  -> builds a valid artifact
  -> reports paid oracle cost C1

Machine 2: same seed design + imported/shared cache from Machine 1
  -> rebuilds or materializes the same/equivalent artifact
  -> reports zero or near-zero oracle cost
  -> reports cache reuse

Machine 3: same seed design + empty cache + oracle access
  -> independently builds a valid artifact
  -> reports paid oracle cost C3 comparable to C1
```

The key proof is:

```text
Machine 2 proves reuse.
Machine 3 proves portable re-realization from the seed design.
```

Machine 3 does not receive the shared cache. It receives the seed design and independently realizes a valid build at comparable cost to Machine 1.

## Beta definition

```text
Beta = seed portability
     + transactional execution
     + sealed artifact identity
     + cache reuse
     + independent re-realization
     + cost comparability
     + a three-machine smoke test
```

Do not broaden the scope beyond this proof.

## Core implementation abstractions

### BuildTransaction

Protects the live site.

Responsibilities:

```text
- prepare inputs
- create quarantine/staging area
- expose safe read/write paths
- run rule action
- validate declared outputs
- promote outputs only after validation
- roll back on failure
- prevent live-site bypass
```

Invariant:

```text
A rule may observe committed inputs, but it may not mutate committed state until all declared outputs pass validation.
```

### BuildSeal

Binds artifact to cause.

Responsibilities:

```text
- bind output content hashes
- bind rule identity
- bind recipe identity
- bind input signatures
- bind build semantics
- support verification and comparison
```

Invariant:

```text
A sealed output must prove what recipe, inputs, rule, and content produced it.
```

### BuildCache

Stores reusable residue.

Responsibilities:

```text
- store sealed outputs
- store recipe identity
- store output hashes
- store usage metadata
- export/import cache bundles
- materialize valid cache hits into a site
```

Invariant:

```text
A cache hit is only valid if its seal and recipe identity match the current seed design.
```

### BuildLedger

Explains the build.

Responsibilities:

```text
- rule events
- oracle events
- trial events
- cache reuse events
- fuel accounting
- cost accounting
- report assembly
```

Invariant:

```text
Every nondeterministic or expensive event is recorded once, in one place, and reports are derived from that ledger.
```

## Development rule

Use the three-machine smoke test as the development spine.

It may start as skipped or expected-fail. Every beta task should move that test closer to green.

Do not prioritize broad features, polish, or new abstractions unless they directly support the three-machine proof.

# Beta Gates and Task List

## Beta Gate A: Seed design portability

Goal:

```text
A seed design can move to a clean machine and build without repo-local assumptions or hidden state.
```

| Rank | Prior IDs | Task | Files to inspect | Claude Code prompt |
|---:|---|---|---|---|
| A1 | 39 | Make `site_inputs` work from JSON designs | `src/husks/designs/ir.py`, `src/husks/build/run.py`, `src/husks/build/site.py`, tests | Thread `site_inputs` from JSON design parsing through `compile()` and `run()` into `build()`. Validate list and dict forms. Add CLI tests proving a seed design with declared site inputs builds from a clean site. |
| A2 | 43 | Reject unknown design fields | `src/husks/designs/ir.py`, `src/husks/cli/commands.py`, tests | Define allowed top-level and rule-level fields. Fail or warn on unknown fields. Add tests for misspellings such as `ouputs`, `taget`, and `fuell`. |
| A3 | 41, 42 | Improve graph validation diagnostics | `src/husks/designs/ir.py`, tests | Add clear diagnostics for forward references, circular dependencies, and duplicate outputs. Duplicate output errors should name both producers. |
| A4 | 40 | Define conditional seed semantics | `src/husks/build/eval.py`, `src/husks/core.py`, `src/husks/designs/transport.py`, tests | Decide whether conditional designs bind both branches or only the executed branch into identity. Add tests documenting the chosen seed portability semantics. |
| A5 | 47 | Make `husks init` produce a valid seed project | `src/husks/setup.py`, tests | Fix the generated project so `husks init`, `husks check`, and `husks run --stub` all pass in a temp directory. Treat this as the default seed-design example. |

## Beta Gate B: Transactional execution

Goal:

```text
A build cannot corrupt the live site. Outputs commit only after validation.
```

| Rank | Prior IDs | Task | Files to inspect | Claude Code prompt |
|---:|---|---|---|---|
| B1 | 1, 3 | Formalize `BuildTransaction` | `src/husks/build/eval.py`, `src/husks/build/site.py`, tests | Introduce a `BuildTransaction` abstraction that owns staging, safe write paths, validation, promotion, and rollback. Refactor rule execution to commit outputs only after validation succeeds. |
| B2 | 4, 5 | Block Python live-site bypass | `src/husks/build/site.py`, `src/husks/build/eval.py`, tests | Make successful Python actions unable to seal outputs written directly to the live site. Require staged write APIs for declared outputs. Add a regression where a Python action writes without `write=True` and must halt. |
| B3 | 16, 38 | Define output type policy | `src/husks/build/eval.py`, `src/husks/build/site.py`, `src/husks/designs/ir.py`, tests | For beta, declared outputs should be regular files only. Reject directories, symlinks, broken symlinks, and special files before sealing. |
| B4 | 23, 24 | Harden imports and symlink collisions | `src/husks/build/site.py`, `src/husks/designs/ir.py`, tests | Validate import local names at runtime. Reject internal paths, path traversal, collisions with outputs, and existing symlinks pointing to the wrong target. |
| B5 | 36 | Make trial outputs binary-safe or explicitly text-only | `src/husks/build/eval.py`, tests | Stop using `read_text()` for trial output collection unless beta explicitly limits trial outputs to text. Either handle bytes safely or reject binary trial outputs with a clear error. |
| B6 | 17 | Use `shlex.split()` for reader commands | `src/husks/gate.py`, `src/husks/cli/commands.py`, tests | Replace `.split()` with `shlex.split()` for reader commands. Add quoted-command regression tests. |

## Beta Gate C: Artifact identity and equivalence

Goal:

```text
Outputs can be compared and verified across machines.
```

| Rank | Prior IDs | Task | Files to inspect | Claude Code prompt |
|---:|---|---|---|---|
| C1 | 30 | Audit recipe identity correctness | `src/husks/build/identity.py`, `src/husks/build/nodes.py`, tests | Confirm shell command identity, Python action identity, oracle recipe identity, inputs, outputs, and parameters are all included in recipe digests. Add invalidation tests for each field. |
| C2 | 26 | Validate manifest schema on read | `src/husks/manifest.py`, `src/husks/build/seal.py`, tests | Add strict manifest schema/version validation. Unsupported or corrupt manifests should return a clear invalid state, not silently degrade. |
| C3 | 27 | Verify `.husk` root in `status` and compare | `src/husks/core.py`, `src/husks/manifest.py`, `src/husks/cli/commands.py`, tests | Add recomputation of `.husk` roots against the live site. Expose root validity in `status --json` and use it for cross-machine comparison. |
| C4 | 37 | Normalize file hashing semantics | `src/husks/core.py`, `src/husks/build/site.py`, `src/husks/manifest.py`, tests | Ensure absent files, regular files, and unsupported paths have one consistent signature representation across seal, manifest, status, and verification. |
| C5 | 29 | Align CSE version language | `src/husks/core.py`, `src/husks/designs/transport.py`, `spec/`, docs | Resolve the v1/v2 naming mismatch. Make wire version, spec labels, and code constants consistent. |
| C6 | New | Add artifact equivalence command or library function | `src/husks/cli/commands.py`, `src/husks/manifest.py`, `src/husks/core.py`, tests | Add a small comparison function that compares two build reports/sites by output root, declared output hashes, and seal validity. This will be used by the three-machine smoke test. |

## Beta Gate D: Cache reuse

Goal:

```text
Machine 2 can reuse Machine 1's realized residue at zero or near-zero oracle cost.
```

| Rank | Prior IDs | Task | Files to inspect | Claude Code prompt |
|---:|---|---|---|---|
| D1 | New | Define beta cache layout | `src/husks/cache.py` if present, otherwise new `src/husks/build/cache.py`, `src/husks/build/run.py`, tests | Define a minimal beta cache format that stores realized outputs, seals, recipe identity, output hashes, and usage metadata. Keep it file-system based and deterministic. |
| D2 | New | Implement cache lookup before oracle execution | `src/husks/build/eval.py`, cache module, tests | Before running an oracle-backed rule, check whether a matching sealed output exists in cache. If valid, materialize it into the site and record reuse with zero paid cost. |
| D3 | New | Add cache export/import | `src/husks/cli/main.py`, `src/husks/cli/commands.py`, cache module, tests | Add `husks cache export` and `husks cache import` for a portable cache tarball. Include integrity checks and reject unsafe paths on import. |
| D4 | New | Add reuse-only mode | `src/husks/cli/main.py`, `src/husks/cli/commands.py`, `src/husks/build/run.py`, tests | Add `--reuse-only` or equivalent. In reuse-only mode, Husks may materialize cache hits but must not call the oracle. Missing cache entries should halt clearly. |
| D5 | 6, 22 | Record cache reuse in the ledger | `src/husks/build/eval.py`, `src/husks/report.py`, ledger/usage code, tests | When a rule is satisfied from cache, record `reused=true`, `paid_cost=0`, source cache identity, and output root in the build report. |

## Beta Gate E: Independent re-realization

Goal:

```text
Machine 3 can build from the same seed design with an empty cache and achieve a valid result at cost comparable to Machine 1.
```

| Rank | Prior IDs | Task | Files to inspect | Claude Code prompt |
|---:|---|---|---|---|
| E1 | New | Add deterministic beta seed example | `examples/`, `src/husks/setup.py`, tests | Create a small seed design that requires an oracle under normal mode, validates its output deterministically, and is stable enough to run twice with comparable cost. |
| E2 | New | Add clean-machine re-realization test | `tests/test_beta_three_machine.py` | Simulate Machine 1 and Machine 3 with separate temp sites and empty caches. Run the same seed design twice and assert both produce valid outputs with comparable oracle-call count and cost. |
| E3 | 35 | Add missing-output test for oracle/trial winners | `src/husks/build/eval.py`, tests | Ensure an oracle or trial winner that omits any declared output halts, writes no seal, and does not promote partial artifacts. |
| E4 | 21 | Make model selection explicit for live/doctor workflows | `src/husks/cli/main.py`, `src/husks/cli/commands.py`, `src/husks/oracle/llm.py` | Ensure the same model configuration can be used for Machine 1 and Machine 3. `doctor --live` should accept `--model` and validate the selected provider. |
| E5 | New | Define cost-comparability tolerance | `src/husks/report.py`, beta test files | Add a beta comparison helper that checks Machine 3 cost against Machine 1 using a configurable tolerance. For stub tests, compare oracle-call count or synthetic cost. |

## Beta Gate F: Ledger and cost comparability

Goal:

```text
Each run emits a machine-readable report proving cost, reuse, validity, and comparability.
```

| Rank | Prior IDs | Task | Files to inspect | Claude Code prompt |
|---:|---|---|---|---|
| F1 | 6, 22 | Introduce `BuildLedger` | `src/husks/report.py`, `src/husks/build/eval.py`, `src/husks/oracle/kernel.py`, `src/husks/oracle/llm.py` | Create a single ledger object for rule events, oracle events, trial events, cache reuse, fuel, and cost. Reports should derive from the ledger, not global usage trackers. |
| F2 | 10, 11 | Separate rule fuel from oracle tool-step fuel | `src/husks/build/eval.py`, `src/husks/oracle/kernel.py`, `src/husks/report.py`, tests | Report build-rule fuel and oracle tool-step fuel as distinct fields. Avoid mixing them in history or cost reporting. |
| F3 | 12 | Keep trial branch usage local and explicit | `src/husks/build/eval.py`, tests | Ensure trial branches return explicit usage. Do not scan trace internals for cost. Merge winning and/or total trial usage according to a documented policy. |
| F4 | 13 | Keep trace reset per build | `src/husks/build/run.py`, `src/husks/utils/events.py`, tests | Preserve the current trace reset behavior and add a regression that two builds in one Python process cannot contaminate one another's reports. |
| F5 | 14 | Add trial summaries only if needed for beta reports | `src/husks/report.py`, `src/husks/build/eval.py` | Add concise trial summaries to reports if trial selection affects beta cost. Otherwise defer rich trial reporting until post-beta. |
| F6 | 15 | Ensure failed builds produce machine-readable reports | `src/husks/report.py`, `src/husks/cli/commands.py`, tests | A failed Machine 1, 2, or 3 run should produce JSON explaining failed rule, stale reason, error, cost so far, and whether any outputs were committed. |

## Beta Gate G: Release smoke and three-machine acceptance

Goal:

```text
The beta proof can be run from a clean checkout or installed package.
```

| Rank | Prior IDs | Task | Files to inspect | Claude Code prompt |
|---:|---|---|---|---|
| G1 | New | Add the three-machine smoke test | `tests/test_beta_three_machine.py`, CLI/build/cache/report code | Add one end-to-end test simulating Machine 1, Machine 2, and Machine 3 in separate temp directories. Machine 1 builds with cost. Machine 2 imports cache and reuses with zero oracle cost. Machine 3 builds from seed with empty cache and comparable cost. |
| G2 | 20 | Stabilize JSON CLI contracts needed by the smoke test | `src/husks/cli/commands.py`, tests | Ensure `run --json`, `status --json`, `explain --json`, cache commands, and compare output emit valid machine-readable JSON with no console noise. |
| G3 | 18 | Add subprocess CLI helper | `tests/conftest.py`, CLI tests | Create a shared subprocess helper using absolute `PYTHONPATH`, timeouts, temp cwd support, and output capture. Replace ad hoc subprocess calls. |
| G4 | 19 | Make tests root-safe | permission tests, `tests/conftest.py` | Skip or rework chmod/write-denial tests when running as root. The beta suite should distinguish real failures from privileged-runner artifacts. |
| G5 | 48, 49 | Add wheel/install smoke test | `pyproject.toml`, resource code, CI/tests | Build a wheel, install it in a clean venv, and run `husks doctor --selftest`, `husks init`, and the stub beta seed demo. |
| G6 | 50 | Standardize beta exit codes | `src/husks/cli/helpers.py`, `src/husks/cli/commands.py`, tests | Define stable exit codes for success, validation failure, build halt, reuse miss, verification failure, and internal error. Add tests for beta commands. |

# Post-beta parking lot

These are useful, but should not block beta unless they directly affect the three-machine proof.

```text
- Rich graph polish for multi-target designs.
- Successful stderr capture.
- Advanced shell environment modeling.
- Configurable command timeout unless needed for tests.
- Full structured validation taxonomy.
- Blockchain or remote registry ideas.
- Large documentation rewrite.
- Complex trial reporting UX.
- Directory-output support.
- Broad agent-framework ergonomics.
```

# Three-machine smoke test sketch

The beta smoke test should simulate three machines using separate temp directories.

```bash
# Machine 1: original realization
husks run seed.json   --site m1-site   --cache m1-cache   --json > m1.json

# Export cache from Machine 1
husks cache export m1-cache husks-cache.tgz

# Machine 2: cached reuse
husks cache import husks-cache.tgz   --cache m2-cache

husks run seed.json   --site m2-site   --cache m2-cache   --reuse-only   --json > m2.json

# Machine 3: independent re-realization
husks run seed.json   --site m3-site   --cache m3-cache   --json > m3.json

# Compare
husks compare-runs m1.json m2.json m3.json
```

Expected result:

```text
Machine 1:
  built = true
  artifact_valid = true
  oracle_cost = C1
  oracle_calls > 0

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

# Single Claude Code umbrella prompt

```text
Implement the Husks beta path around the three-machine problem.

Do not broaden scope. The acceptance target is:

Machine 1 receives a seed design, empty cache, and oracle access. It builds a valid artifact and reports paid oracle cost C1.

Machine 2 receives the same seed design plus an imported/shared Husks cache from Machine 1. It rebuilds or materializes the artifact with zero or near-zero oracle cost and reports cache reuse.

Machine 3 receives only the same seed design, an empty cache, and oracle access. It independently builds a valid artifact and reports cost C3 comparable to C1.

Organize the implementation around:
1. BuildTransaction for safe staged execution.
2. BuildSeal / artifact identity for output verification.
3. BuildCache for export/import and reuse.
4. BuildLedger for cost, oracle calls, fuel, and reuse.
5. A three-machine end-to-end smoke test.

Preserve existing behavior where possible, but prioritize the beta invariant over backwards compatibility.

Use the three-machine smoke test as the development spine. It may begin as skipped or expected-fail, but every beta change should move that test closer to green.
```

# Suggested first implementation sequence

Start here:

```text
1. Add `tests/test_beta_three_machine.py` as skipped or expected-fail.
2. Fix `site_inputs` from JSON designs.
3. Make `husks init` produce a seed project that passes `check` and `run --stub`.
4. Introduce `BuildTransaction`.
5. Block Python live-site bypass.
6. Define output policy as regular files only.
7. Implement minimal cache layout.
8. Implement cache export/import.
9. Implement reuse-only mode.
10. Introduce `BuildLedger` or equivalent single source of truth for cost/reuse.
11. Add report fields required by the three-machine comparison.
12. Turn the three-machine smoke test green under stub/synthetic cost.
```

# Non-goals before beta

Do not spend beta time on:

```text
- Making Husks a general agent framework.
- Remote registries.
- Blockchain storage.
- Complex UI/graph output.
- Full documentation rewrite.
- Directory outputs.
- Elaborate environment modeling.
- Large plugin systems.
- Broad user ergonomics beyond `init`, `run`, `status`, `explain`, `cache`, and `compare-runs`.
```
