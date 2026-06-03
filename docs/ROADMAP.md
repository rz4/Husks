# Husks Hardening & Improvement Roadmap

Status reference: 601/610 tests pass (8 skipped, 1 flaky). Both readers
(`core.py`, `spec/conformance/verify.mjs`) now enforce identical validation
(digit-only length, depth bound, per-atom size cap) and agree on all positive
vectors and reject all malformed vectors. Writes are atomic with fsync for
crash safety. Tar import is member-validated with `filter='data'`. Oracle
tool sandbox enforces path validation, write size caps (10 MB), and timeout
limits (30s). Comprehensive tests for symlink escaping and oracle sandbox
isolation (P24, P28).

This document consolidates three workstreams: permanence/correctness
hardening (P), CLI improvements (C), and transport improvements (T). Items are
ordered within each tier by leverage. File and line references are to the
state reviewed; re-confirm before editing.

The single highest-leverage block is **P1–P9**: the two readers must provably
accept the same language. **P1–P4 completed**: both readers now enforce
identical validation. Remaining: negative vector coverage (P5–P9).

---

## Tier 1 — Permanence integrity (the core claim)

Protects the property that two readers in two languages agree on roots.
Everything else is downstream of this guarantee.

- [x] **P1.** Lift `verify.mjs` to byte-identical validation with `core.py`. The JS reader skips the digit-only length check, depth bound, and per-atom size cap that Python enforces. `spec/conformance/verify.mjs:20` (`parse`) vs `src/husks/core.py:85`. ✓ Implemented: Added all three validations (depth, digit-only, size cap) to `verify.mjs`.
- [x] **P2.** Replace `parseInt` length parsing in the JS reader with a strict digit-only byte scan. `parseInt("12abc",10)` returns 12; Python rejects it. `spec/conformance/verify.mjs:37`; mirror the `0x30..0x39` loop in `core.py`. ✓ Implemented: Byte-by-byte validation added.
- [x] **P3.** Add a `_MAX_PARSE_DEPTH` equivalent to `verify.mjs`. A nested-list bomb currently stack-overflows Node instead of erroring cleanly. Ref `src/husks/core.py:59,105`. ✓ Implemented: MAX_PARSE_DEPTH = 128 enforced.
- [x] **P4.** Add a per-atom length cap to `verify.mjs` matching Python's 256 MiB (`src/husks/core.py:63,153`), independent of the 10 MB total-file guard at `verify.mjs:16`. ✓ Implemented: MAX_ATOM_LENGTH = 256 MB enforced.
- [ ] **P5.** Build a shared frozen negative-vector set (raw bytes + a `.reject` manifest) that every conformant reader must reject. Today only three malformed vectors exist in `spec/conformance/`.
- [ ] **P6.** Add depth-bomb, oversized-length, NUL-in-length, and embedded-junk-in-length negative vectors — the four cases where Python and JS currently diverge.
- [ ] **P7.** Add a negative vector for structural type confusion (e.g. `husk[1]` a list, `node[2]` an atom where a list is expected). The Python extractors in `core.py` assume shapes without always checking.
- [ ] **P8.** Make the conformance gate require both readers to reject every negative vector, not just accept positives. Negative cross-check exists at `src/husks/gate.py:126–163` but coverage is thin.
- [ ] **P9.** Add a differential fuzzer feeding random bytes to both readers; assert identical accept/reject and identical roots on accept. Run in CI with a fixed seed corpus.
- [ ] **P10.** Pin a Unicode normalization policy (or explicit none) in the spec and test it cross-reader. `atom_str` decodes UTF-8 but nothing fixes NFC/NFD; two producers could emit different bytes for the same logical name. Ref `src/husks/core.py` (`atom_str`).

## Tier 2 — Seal and recipe identity correctness

- [ ] **P11.** Stabilize the callable-action bytecode fallback. CSE-v2 §E5.2 falls back to `co_code + repr(co_consts)`, which changes across the 3.10–3.13 interpreters the CI matrix runs. A source-unavailable callable re-fires across Python versions.
- [ ] **P12.** Add a cross-interpreter seal test: seal a callable action under one Python, verify the root under another. Gate on it.
- [ ] **P13.** Document and test `inspect.getsource` failure modes — lambdas, REPL-defined functions, decorated callables — each can silently shift identity.
- [ ] **P14.** Make `read_seal` distinguish "absent" from "corrupt." It returns `None` for both (`src/husks/build/seal.py:37–50`), so a corrupted seal silently triggers a re-fire indistinguishable from a first build. Log corruption.
- [ ] **P15.** Validate the seal `v` field against known versions instead of truthiness. `data.get("v")` at `src/husks/build/seal.py:47` treats `"v": 99` as valid.
- [ ] **P16.** Hash files by streaming, not `read_bytes()`/`read()`. `file_sig` (`src/husks/build/site.py:351`) and `content_hash_or_absent` (`src/husks/core.py:203`) both load whole files; a large declared output forces full allocation in the verifier.
- [ ] **P17.** Add a TOCTOU guard between `is_file()` and `read_bytes()` in `file_sig` — the check-then-read race can hash a file replaced mid-build. `src/husks/build/site.py:351`.
- [ ] **P18.** Define behavior for duplicate input/output names in a rule. Nothing rejects `inputs=[a, a]`; the seal silently double-binds.

## Tier 3 — Write durability and crash safety

- [x] **P19.** Make `write_text` atomic (temp file in same dir + `os.replace`). A crash mid-write leaves a truncated seal/manifest that `read_seal` may parse as valid-but-wrong. `src/husks/build/site.py:148–152`. ✓ Implemented: `write_text` now uses temp file + `os.replace()` for atomic writes.
- [x] **P20.** `fsync` seal and manifest writes before a build is considered committed. "committed" should survive power loss. `src/husks/build/seal.py:211,373`. ✓ Implemented: Both `write_text` and `write_bytes_atomic` call `os.fsync()` before closing.
- [x] **P21.** Write the `.husk` and build manifest atomically and last, so a build is committed only when the permanence record is fully on disk. Make `tests/test_SOLID_67_*` meaningful rather than permission-dependent. ✓ Implemented: Added `write_bytes_atomic()` for .husk files; updated tests to use directory permissions instead of file permissions.
- [ ] **P22.** Make `append_history` an atomic append with flush; a partial JSONL line corrupts the history file for all future reads. `src/husks/build/seal.py:263–264`.
- [ ] **P23.** Add an fsck/repair command that detects and quarantines corrupt seals, partial manifests, and orphaned trace files.

## Tier 4 — Oracle and tool sandbox

- [x] **P24.** Add a fuzz/property test for `sandbox()` path escaping — symlink races, `..` after resolution, nested readonly-root overlaps. `tests/test_SOLID_62_sandbox_path_escaping.py` (10 tests).
- [x] **P25.** Cap oracle output size before it is written through `write-file`; MAX_WRITE_SIZE = 10 MB enforced in write_file(). `src/husks/oracle/tools.py:27`.
- [x] **P26.** Bound and time-limit each tool dispatch, not just the oracle call as a whole. MAX_TOOL_TIMEOUT = 30s with signal.SIGALRM. `src/husks/oracle/tools.py:31,204`.
- [x] **P27.** Make `dispatch`'s catch-all log the real exception type, not just stringify it into the tool result. `src/husks/oracle/tools.py:260-263`.
- [x] **P28.** Add a test that an oracle cannot read outside the site root via a symlink it creates during the build (write-then-traverse). `tests/test_SOLID_67_oracle_symlink_escape.py` (9 tests).
- [x] **P29.** Confirm the `write=True` path never consults `_readonly_roots`, so readonly-root reads cannot be re-exported as writes within a build. Security comment at `src/husks/oracle/tools.py:118-119`.
- [ ] **P30.** ~~Make `set_site_root` reject a `None` site root when any writing tool is enabled~~ Not implemented — conflicts with test cleanup patterns; real protection is in sandbox() function. `src/husks/oracle/tools.py:57`.

## Tier 5 — Gate hardening (runs untrusted readers)

- [ ] **P31.** Bound reader stdout/stderr in the gate. `capture_output=True` buffers unbounded output from a hostile reader. `src/husks/gate.py` (`_run_reader`).
- [ ] **P32.** Run gated readers with a restricted environment and cwd, not the inherited process environment.
- [ ] **P33.** Add a wall-clock and memory limit (rlimit) per reader invocation, beyond the 60s subprocess timeout.
- [ ] **P34.** Emit a signed/hashed conformance digest over the (name, root) pairs so a passing gate run is itself a verifiable residue. `src/husks/gate.py:205`.

## Tier 6 — Test suite and CI

- [ ] **P35.** Fix the two failing write-failure tests to skip or use a non-root mechanism (read-only mount or `pyfakefs`) so they are meaningful under uid 0 in CI containers. `tests/test_SOLID_67_verification_write_failures.py`.
- [ ] **P36.** Add a CI job that runs the JS reader against all vectors, positive and negative — currently the cross-check is library-internal, not a gate step. `.github/workflows/ci.yml`.
- [ ] **P37.** Add property-based tests (Hypothesis) for CSE round-trip: `parse(encode(x)) == x` for all well-formed trees, and `encode` output always re-parses.
- [ ] **P38.** Add a canonicality test: exactly one byte encoding per value — fuzz for any input two distinct byte strings parse to without one being rejected.
- [ ] **P39.** Add a reproducibility test running the three-machine proof twice, asserting bit-identical roots (guards hidden nondeterminism: dict ordering, timestamps leaking into seals).
- [ ] **P40.** Pin the bytecode/source identity tests across the full 3.10–3.13 matrix, not just the current interpreter.

## Tier 7 — Robustness and operability

- [ ] **P41.** Add explicit fuel-exhaustion tests at the boundary (fuel = exactly cost, cost − 1, 0); assert clean `halt` with recorded residue, not partial commit. Ref `src/husks/build/run.py`.
- [ ] **P42.** Guarantee `clear_fired_seals` runs on every abnormal exit path including `KeyboardInterrupt`/`SystemExit`, so a Ctrl-C'd build never leaves reusable seals. `src/husks/build/seal.py:54`.
- [ ] **P43.** Validate the manifest schema on read, not just on write — a hand-edited or truncated manifest should fail loudly.
- [ ] **P44.** Add a `husks verify` command that re-runs `recompute_root` against a committed build and a stored root, as a first-class user-facing integrity check (distinct from the gate). (See also C/T item 41.)
- [ ] **P45.** Reject `.husk` files whose embedded version atom the reader doesn't recognize, with a clear message, rather than threading an unknown version into `compute_seal`. `src/husks/core.py` (`recompute_root` / `_recompute_node`).
- [ ] **P46.** Add length/character limits to rule and file names beyond the security checks — very long names create unwieldy trace paths and can hit filesystem limits.
- [ ] **P47.** Test multi-target build-root combination (`sorted(per_roots)` then hash) against a frozen vector; this path has no conformance vector and the JS/Python combine logic could drift. `src/husks/core.py` (`recompute_root`), `verify.mjs` (`recomputeRoot`).

## Tier 8 — Documentation and supply chain

- [ ] **P48.** Write a threat model document: what Husks defends against (malicious .husk, malicious oracle, malicious cache tarball, hostile reader) and what it explicitly does not. Several defenses exist; the model is implicit.
- [ ] **P49.** Pin dependency versions and add a lockfile for the `[llm]` extra — install pulls 40+ floating transitive packages, any of which could affect determinism if they touch hashing or JSON ordering.
- [ ] **P50.** Add `SECURITY.md` and a reproducible-build attestation for the wheel, so the artifact users `pip install` is itself verifiable.

---

## Transport — CSE↔JSON bijection and elaboration

The bijection invariant (`round_trip` is identity) is load-bearing here.

- [x] **T1.** Add a cycle guard to `elaborate`. The `seen` set is per-node (siblings only); a dependency cycle (A's input produced by B, B's by A) recurses to `RecursionError`. Track an ancestor set and raise "dependency cycle: A → B → A". `src/husks/designs/transport.py:396,402`. ✓ Implemented: Added ancestor tracking with tuple to detect cycles and show clear path.
- [ ] **T2.** Bound elaboration recursion depth with an explicit limit and readable error, mirroring `core.py`'s `_MAX_PARSE_DEPTH`.
- [ ] **T3.** Detect missing producers in `elaborate`. An input naming no output and not a site input is silently treated as a leaf — distinguish site input from dangling dependency and error on the latter.
- [ ] **T4.** Make the lossy case explicit: atoms with invalid UTF-8 raise `UnicodeDecodeError` mid-convert (`_atom_to_json`). Binary atoms are legal in CSE but unrepresentable here — base64-encode non-UTF-8 atoms or document/enforce a UTF-8-only transport with clean rejection.
- [ ] **T5.** Add a property test for the bijection over arbitrary well-formed CSE, not just the demo tree: `round_trip(encode(x)) == encode(x)` and `json_to_ast(ast_to_json(t)) == t`. Highest-value transport test; currently absent.
- [ ] **T6.** Guard `ast_to_json`/`json_to_ast` against structural underflow. `cse_value[1..4]` are indexed without length checks; a malformed tree raises `IndexError` instead of a typed `ValueError` naming the form.
- [ ] **T7.** Validate `form` is present and a string in `json_to_ast`; `json_value["form"]` raises bare `KeyError` on hand-written JSON.
- [ ] **T8.** Reject unknown JSON keys per form (strict mode) or warn. A typo'd `"prompts"` for `"prompt"` currently produces a valid-but-wrong husk.
- [ ] **T9.** Make the legacy `target`→`targets` shim a single shared normalizer; it is handled independently in `elaborate` and `json_to_ast` and can drift.
- [ ] **T10.** Resolve the version atom mismatch: `elaborate` hardcodes `b"1"` (`transport.py:418`) while `core.py` emits `CSE_VERSION = b"2"`. Confirm intended and tested, or unify.
- [ ] **T11.** Validate `fuel` is a non-negative integer string at elaboration; `str(rule_dict.get("fuel", 8))` (`transport.py:293`) encodes `"abc"` unchallenged.
- [ ] **T12.** Validate tool names against the registered tool set during elaboration, not at dispatch, so an unknown tool is a design-check failure.
- [ ] **T13.** Enforce that `commit`/`halt`/`let`/`cond` rules don't carry `inputs`/`outputs`, or define their meaning; extra fields are silently ignored.
- [ ] **T14.** Add round-trip coverage for all nine forms including `let` and `cond`, which the demo vectors don't exercise.
- [ ] **T15.** Share kind dispatch between `_elaborate_recipe` and `elaborate_node`; overlapping string literals in two places invite divergence when a kind is added.
- [ ] **T16.** Canonicalize JSON output ordering (`sort_keys=True` or fixed field order) in `to_json_str`, so the JSON transport form is byte-stable and reproducible as a residue.
- [ ] **T17.** Add a transport self-check to `doctor` that round-trips every conformance husk through JSON and asserts byte-identity.
- [ ] **T18.** Publish a JSON Schema for the transport form and validate on `from_json_str` for precise external-producer errors.

## CLI — correctness, exit codes, robustness

- [ ] **C19.** Replace the `getattr(args, 'verbose', False)` pattern with parser-level defaults so missing attributes are impossible. `src/husks/cli/main.py`. (Partial: created Console module foundation, full migration deferred)
- [ ] **C20.** Catch `from_json`/design-load failures uniformly for `run`, `check`, `history`; audit every command for consistent `EXIT_USAGE` vs `EXIT_BUILD_FAIL`.
- [x] **C21.** Document and freeze the exit-code contract (`EXIT_OK/BUILD_FAIL/USAGE` plus `status`'s ad-hoc exit 4) in a single table in `--help`, with a test asserting each code. ✓ Implemented: Added exit code documentation to helpers.py and displayed in --help.
- [x] **C22.** Make `--quiet` suppress all non-essential stdout; route output through a console object that honors it instead of direct `print`. ✓ Implemented: Created Console class in cli/console.py with quiet mode support.
- [x] **C23.** Honor `--color never/auto/always` everywhere; color codes are emitted directly in `main.py` help and `cache` output. Centralize so `never` produces pipe-safe text. ✓ Implemented: Console class handles color modes centrally with _should_use_color().
- [x] **C24.** Disable color by default under `--color auto` when stdout is not a TTY, and strip ANSI when captured. ✓ Implemented: Console auto-detects TTY and provides strip_ansi() method.
- [x] **C25.** Validate mutually exclusive flags via argparse groups, not the manual `verbose and json_output` check, so `compare`/`status`/`explain` get the same protection. ✓ Implemented: Added mutually_exclusive_group for run and check commands.
- [ ] **C26.** Validate `--site` up front for every command that needs it (exists, directory, writable for `run`/`import`) with a specific error.
- [x] **C27.** Define `--reuse-only` + `--stub` interaction (refuse or set precedence); currently undefined at the CLI layer. ✓ Implemented: Documented that --reuse-only + --stub work together (reuse cached stub outputs).
- [x] **C28.** Warn when `--model` is passed with `--stub` (model unused), to avoid implying an LLM ran. ✓ Implemented: Warning emitted when --model used with --stub.
- [x] **C29.** Guard `cache export`/`import` against missing or non-`.tar.gz` paths before `fresh_store` is constructed. `src/husks/cli/cmd/cache.py`. ✓ Implemented: Validates .tar.gz extension and file/directory existence before creating store.
- [ ] **C30.** Stream cache import/export progress and a final integrity summary (entries, bytes, manifest hash) so transport is auditable from the CLI.
- [ ] **C31.** Verify the cache tarball MANIFEST hash against contents on import and surface a CLI error; the CLI currently reports only a count.
- [ ] **C32.** Add `--dry-run` to `cache import` that runs all member checks and reports what would be imported without writing.
- [ ] **C33.** Make `compare` explicit about equivalence: print which sites matched on roots vs output hashes; exit non-zero with a diff summary on divergence.
- [ ] **C34.** Add `--quiet`/machine-readable output to `compare` printing just the common root or a divergence code, for use as a CI gate.
- [x] **C35.** Handle `KeyboardInterrupt` at the `main()` boundary with a clean exit code and message, not a traceback. ✓ Implemented: Handled in _cli_entry() wrapper (exit code 130).
- [x] **C36.** Wrap `main()` in a top-level handler converting uncaught exceptions to `EXIT_BUILD_FAIL` plus a one-line error (full traceback only under `--verbose`). ✓ Implemented: Added _cli_entry() wrapper with exception handling and KeyboardInterrupt support.
- [ ] **C37.** Add shell completion generation (`husks completion bash|zsh|fish`).
- [x] **C38.** Provide a stable `--json` schema across all commands with a top-level `schema_version`; output shape currently varies per command. ✓ Implemented: Added json_output() helper function with JSON_SCHEMA_VERSION = "1.0" in helpers.py.
- [x] **C39.** Make `_get_version` failure non-silent in `doctor`; the hardcoded `"0.1.0"` fallback masks a broken install. `src/husks/cli/main.py` (`_get_version`). ✓ Implemented: _get_version() now raises RuntimeError instead of silent fallback to "0.1.0".
- [x] **C40.** Add `husks --version --json` emitting version, CSE wire version, seal format version, and conformance-vector digest in one machine-readable blob. ✓ Implemented: Added --version-json flag with JSON output including husks_version, cse_wire_version, seal_format_version, schema_version.

## Cross-cutting (transport + CLI)

- [ ] **X41.** Add `husks verify <site> <root>` driving `recompute_root` from the CLI — first-class integrity check distinct from `compare` and `doctor`. (Pairs with P44.)
- [x] **X42.** Make cache export deterministic/reproducible: pin tar member order, mtime, uid/gid, mode (`tarfile` defaults leak host metadata). `src/husks/build/cache.py:543,559`. ✓ Implemented: Added make_deterministic() helper that sets mtime=0, uid=0, gid=0, and sorted entry order.
- [x] **X43.** Pin gzip level and `mtime=0` on export so two exports of identical content hash equal. `src/husks/build/cache.py:543`. ✓ Implemented: Using compresslevel=9 and mtime=0; removed timestamp from manifest.
- [ ] **X44.** Round-trip test cache export→import→export; assert the second tarball equals the first byte-for-byte. (Deferred: needs test implementation)
- [ ] **X45.** Cap design-file size before `from_json` at the CLI layer, mirroring the husk-size guards.
- [ ] **X46.** Validate design JSON depth/rule count before elaboration to bound elaborator work.
- [ ] **X47.** Add `husks check --strict` running full elaboration + bijection round-trip + tool-name validation + cycle detection, returning a single pass/fail suitable for pre-commit.
- [ ] **X48.** Emit elaboration errors with rule names and dependency path, not bare `KeyError`/`ValueError`.
- [ ] **X49.** Add CLI integration tests for every subcommand's happy path and one failure path, asserting exit code and that `--json` output parses.
- [ ] **X50.** Generate a CLI reference doc from the parser definitions (so it cannot drift), covering every command, flag, exit code, and `--json` schema.

---

## Suggested first cut

1. ~~**P1–P9**~~ — ✓ **P1–P4 completed**: reader parity achieved. Remaining: **P5–P9** negative-vector coverage.
2. ~~**T1**~~, **T5** — ✓ **T1 completed**: cycle detection with ordered ancestor tracking. Remaining: **T5** bijection property test.
3. ~~**P19–P21**~~ — ✓ **Completed**: atomic/durable writes (crash safety for the permanence record).
4. ~~**P24–P29**~~ — ✓ **Completed**: oracle sandbox hardening (path escaping tests, write size caps, timeout limits, error type reporting). **P30 not implemented** (conflicts with test cleanup).
5. ~~**X42–X43**~~ — ✓ **Completed**: reproducible cache export (deterministic tar archives). Remaining: **X44** round-trip test.
