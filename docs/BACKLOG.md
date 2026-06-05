# Husks Backlog

Consolidated from the hardening roadmap and exploration backlog.
Items are unchecked work remaining after the hardening pass.
File references are to the pre-hardened layout; re-confirm against
the hardened source (`kernel.py`, `forms.py`, `seal.py`, `engine.py`,
`oracle.py`, `locke.py`, `report.py`, `cli.py`).

---

## Layer rules

1. Dependencies point strictly downward. L(n) may only import from L(0..n-1).
2. Each layer's Locke design is the contract. Source must satisfy it. Tests must verify it.
3. Work proceeds bottom-up. A layer is not hardened until its Locke design seals.
4. Keep the code as minimal as possible, use functional programming.

---

## Permanence integrity

- [ ] **P5.** Build a shared frozen negative-vector set (raw bytes + a `.reject` manifest) that every conformant reader must reject.
- [ ] **P6.** Add depth-bomb, oversized-length, NUL-in-length, and embedded-junk-in-length negative vectors.
- [ ] **P7.** Add a negative vector for structural type confusion (e.g. `husk[1]` a list, `node[2]` an atom where a list is expected).
- [ ] **P8.** Make the conformance gate require both readers to reject every negative vector, not just accept positives.
- [ ] **P9.** Add a differential fuzzer feeding random bytes to both readers; assert identical accept/reject and identical roots on accept.
- [ ] **P10.** Pin a Unicode normalization policy (or explicit none) in the spec and test it cross-reader.

## Seal and recipe identity

- [ ] **P11.** Stabilize the callable-action bytecode fallback across Python 3.10–3.13.
- [ ] **P12.** Add a cross-interpreter seal test: seal a callable action under one Python, verify the root under another.
- [ ] **P13.** Document and test `inspect.getsource` failure modes: lambdas, REPL-defined functions, decorated callables.
- [ ] **P14.** Make `read_seal` distinguish "absent" from "corrupt." Log corruption.
- [ ] **P15.** Validate the seal `v` field against known versions instead of truthiness.
- [ ] **P16.** Hash files by streaming, not `read_bytes()`/`read()`.
- [ ] **P17.** Add a TOCTOU guard between `is_file()` and `read_bytes()` in file_sig.
- [ ] **P18.** Define behavior for duplicate input/output names in a rule.

## Write durability and crash safety

- [ ] **P22.** Make `append_history` an atomic append with flush.
- [ ] **P23.** Add an fsck/repair command that detects and quarantines corrupt seals, partial manifests, and orphaned trace files.

## Gate hardening

- [ ] **P31.** Bound reader stdout/stderr in the gate.
- [ ] **P32.** Run gated readers with a restricted environment and cwd.
- [ ] **P33.** Add a wall-clock and memory limit (rlimit) per reader invocation.
- [ ] **P34.** Emit a signed/hashed conformance digest over the (name, root) pairs.

## Test suite and CI

- [ ] **P35.** Fix the two failing write-failure tests to skip or use a non-root mechanism.
- [ ] **P36.** Add a CI job that runs the JS reader against all vectors, positive and negative.
- [ ] **P37.** Add property-based tests (Hypothesis) for CSE round-trip: `parse(encode(x)) == x`.
- [ ] **P38.** Add a canonicality test: exactly one byte encoding per value.
- [ ] **P39.** Add a reproducibility test running the three-machine proof twice, asserting bit-identical roots.
- [ ] **P40.** Pin the bytecode/source identity tests across the full 3.10–3.13 matrix.

## Robustness and operability

- [ ] **P41.** Add explicit fuel-exhaustion tests at the boundary (fuel = exactly cost, cost − 1, 0).
- [ ] **P42.** Guarantee `clear_fired_seals` runs on every abnormal exit path including `KeyboardInterrupt`/`SystemExit`.
- [ ] **P43.** Validate the manifest schema on read, not just on write.
- [ ] **P44.** Add a `husks verify` command as a first-class user-facing integrity check.
- [ ] **P45.** Reject `.husk` files whose embedded version atom the reader doesn't recognize.
- [ ] **P46.** Add length/character limits to rule and file names.
- [ ] **P47.** Test multi-target build-root combination against a frozen vector.

## Documentation and supply chain

- [ ] **P48.** Write a threat model document.
- [ ] **P49.** Pin dependency versions and add a lockfile for the `[llm]` extra.
- [ ] **P50.** Add `SECURITY.md` and a reproducible-build attestation for the wheel.

---

## Transport: CSE↔JSON bijection and elaboration

- [ ] **T2.** Bound elaboration recursion depth with an explicit limit.
- [ ] **T3.** Detect missing producers in `elaborate`: distinguish site input from dangling dependency.
- [ ] **T4.** Make the lossy case explicit: binary atoms are legal in CSE but unrepresentable in JSON.
- [ ] **T5.** Add a property test for the bijection over arbitrary well-formed CSE.
- [ ] **T6.** Guard `ast_to_json`/`json_to_ast` against structural underflow.
- [ ] **T7.** Validate `form` is present and a string in `json_to_ast`.
- [ ] **T8.** Reject unknown JSON keys per form (strict mode) or warn.
- [ ] **T9.** Make the legacy `target`→`targets` shim a single shared normalizer.
- [ ] **T10.** Resolve the version atom mismatch between `elaborate` and the CSE codec.
- [ ] **T11.** Validate `fuel` is a non-negative integer string at elaboration.
- [ ] **T12.** Validate tool names against the registered tool set during elaboration, not at dispatch.
- [ ] **T13.** Enforce that `commit`/`halt`/`let`/`cond` rules don't carry `inputs`/`outputs`, or define their meaning.
- [ ] **T14.** Add round-trip coverage for all nine forms including `let` and `cond`.
- [ ] **T15.** Share kind dispatch between `_elaborate_recipe` and `elaborate_node`.
- [ ] **T16.** Canonicalize JSON output ordering so the JSON transport form is byte-stable.
- [ ] **T17.** Add a transport self-check to `doctor`.
- [ ] **T18.** Publish a JSON Schema for the transport form.

---

## CLI

- [ ] **C19.** Replace `getattr(args, 'verbose', False)` with parser-level defaults.
- [ ] **C20.** Catch design-load failures uniformly; audit every command for consistent exit codes.
- [ ] **C26.** Validate `--site` up front for every command that needs it.
- [ ] **C30.** Stream cache import/export progress and a final integrity summary.
- [ ] **C31.** Verify the cache tarball MANIFEST hash against contents on import.
- [ ] **C32.** Add `--dry-run` to `cache import`.
- [ ] **C33.** Make `compare` explicit about equivalence; exit non-zero with a diff summary on divergence.
- [ ] **C34.** Add `--quiet`/machine-readable output to `compare`.
- [ ] **C37.** Add shell completion generation (`husks completion bash|zsh|fish`).

---

## Cross-cutting

- [ ] **X41.** Add `husks verify <site> <root>` driving `recompute_root` from the CLI.
- [ ] **X44.** Round-trip test cache export→import→export; assert byte-identical tarballs.
- [ ] **X45.** Cap design-file size before loading at the CLI layer.
- [ ] **X46.** Validate design JSON depth/rule count before elaboration.
- [ ] **X47.** Add `husks check --strict` for pre-commit validation.
- [ ] **X48.** Emit elaboration errors with rule names and dependency path.
- [ ] **X49.** Add CLI integration tests for every subcommand's happy path and one failure path.
- [ ] **X50.** Generate a CLI reference doc from the parser definitions.

---

## Exploration

Items from the exploration backlog not already covered above.

### Structural

1. **Unify report generation.** One authoritative `Report` object should feed both JSON and visual output.
2. **Finalize the Beta 100 report contract.** Add `spec/report-v1.json` and validate against it in CI.
3. **Resolve provenance metadata.** Seals are executor-blind by design, but the Report should carry full provenance for audit.
4. **Consolidate cache-key generation.** One canonical path for recipe identity, one test.

### Test coverage

5. **Add dedicated test file for `history` command.**
6. **Add test for `--report-json` sidecar.**
7. **Add test for `--soft-fail`.**
8. **Add test for `--reuse-only` CLI contract.**
9. **Test equivalence field behavior end-to-end** (`exact` vs `free` across three-machine comparison).
10. **Cover the `verify` subcommand with a proper test.**

### CLI friction

11. **Auto-site for `history` command.**
12. **Simplify SKILL.md run example** (auto-site removes `--site` need).
13. **Surface `--backend` in `husks run --help` more prominently.**
14. **Add `husks run --dry` as alias for `--stub`.**
15. **Add `husks verify --all` for multi-husk sites.**

### Oracle sandbox

16. **Add audit logging for tool access** (every read/write/list/tree in the trace).
17. **Cap `read-file` size** (e.g. 1 MB) with a clear error.
18. **Add `nofollow` option for symlink traversal in readonly roots.**

### Spec & docs

19. **Document the Blocker numbering system.**
20. **Write a migration guide: demo → core-bootstrap.**
21. **Document `equivalence` field semantics with examples.**
22. **Document cost_tolerance in the Design IR section.**
23. **Freeze the three-machine proof contract.**
24. **Add a "Husks for the impatient" quick-start.**

### Code quality

25. **Unify subprocess CLI helpers across tests** (one `run_husks_cli` in `conftest.py`).
26. **Remove manual input copying in tests** (use IR's `site_inputs` resolution).
27. **Consolidate freshness state calculation** (one canonical function).

### Build engine

28. **Surface `trial` in docs.**
29. **Improve trial branch failure diagnostics.**
30. **Add `cond` and `let` to the Design IR.**
31. **Implement fuel reclamation** (return fuel for sealed rules on re-run).
32. **Add `--fuel-report` flag.**

### Verification

33. **Add a Python-only CSE reader conformance test.**
34. **Verify `.husk` files are bitwise-identical across platforms.**

### Observability

35. **Add `husks explain --trace <rule>` for full oracle transcript.**
36. **Add `husks status --watch` for live site monitoring.**
37. **Add `husks explain --diff <rule>` between two sites.**
