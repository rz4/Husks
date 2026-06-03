# Husks — Exploration Backlog

Ranked by compound value: items near the top unblock or simplify the most downstream work.

---

## Tier 1 — Structural blockers (unblock everything downstream)

1. **Unify report generation.** Three separate report paths (`report.py`, `build.py:collect_hydrated_residue`, `build.py:collect_dry_residue`) produce overlapping but inconsistent data. One authoritative `Report` object should feed both JSON and visual output.

2. **Finalize the Beta 100 report contract.** The report JSON schema is referenced across `report.py`, `compare.py`, `cli/cmd/build.py`, and `liquid-beta.md` but never frozen as a single schema file. Add `spec/report-v1.json` and validate against it in CI.

3. **Resolve Blocker #10 — demo design quarantine.** Four tests in `test_SOLID_17_gate_a_husks_init.py` are skipped because `core-bootstrap` replaced the demo design. Either delete the demo or make `husks init` produce it as an alternate template.

4. **Resolve Blocker #8 — provenance metadata.** `eval.py:434,567` and `report.py:177,211` have incomplete provenance extraction (backend, model, config_hash, prompt_hash). Seals are executor-blind by design, but the Report should carry full provenance for audit.

5. **Consolidate cache-key generation.** `build/cache.py` and `build/identity.py` both compute recipe identity. One canonical path, one test.

## Tier 2 — Test coverage (confidence for everything else)

6. **Add dedicated test file for `history` command.** Currently no test_SOLID_*_history.py. The `_cmd_history` function in `inspect.py` is untested in isolation.

7. **Add test for `--report-json` sidecar.** Blocker #1 (`build.py:670`) — the flag exists but has no test exercising the write-to-file path.

8. **Add test for `--soft-fail`.** The flag is wired in `build.py` and documented in `liquid-beta.md` but has no CLI-level integration test.

9. **Add test for `--reuse-only` CLI contract.** The flag works in `run()` but the CLI path (error messages, JSON error shape) is untested.

10. **Test equivalence field behavior end-to-end.** `ir.py:121,347` defines it, `compare.py:275,284` uses it, but no test exercises `exact` vs `free` across a three-machine comparison.

12. **Cover the `verify` subcommand with a proper test.** Step 3 of the midas-loop work added `_cmd_verify` but it has no dedicated test file yet (only indirectly covered via SOLID_24 root verification).

## Tier 3 — CLI friction (the midas loop)

13. **Auto-site for `history` command.** Same pattern as the `run` auto-site — derive `/tmp/husks-<name>` from the design when `--site` is omitted.

14. **Simplify SKILL.md run example.** Now that auto-site exists, the example can drop `--site /tmp/husks-<name>` and just show `python -m husks.cli run design.json`.

15. **Add `husks init --list` to show available templates.** Currently you have to know the template name. A quick listing would reduce friction.

16. **Surface `--backend` in `husks run --help` more prominently.** The flag is buried. Consider grouping oracle-related flags (`--backend`, `--model`, `--stub`, `--reuse-only`) under a visual section in help.

17. **Add `husks run --dry` as alias for `--stub`.** "Dry run" is a more universally understood term. Keep `--stub` for backwards compatibility.

18. **Add `husks verify --all` for multi-husk sites.** Currently errors on multiple `.husk` files. `--all` could verify each and print a summary.

## Tier 4 — Oracle sandbox hardening

19. **Replace oracle tool globals with per-call context.** `tools.py:25-42` uses module-level `_site_root` and `_readonly_roots`. Pass a context object through the tool dispatch instead.

20. **Add audit logging for tool access.** Every `read-file`, `write-file`, `list-dir`, `tree` call should be recorded in the trace, not just oracle_start/oracle_done.

21. **Cap `read-file` size.** No limit on file size currently. A 500MB read would blow up the LLM context. Add a `_MAX_READ_SIZE` (e.g. 1MB) with a clear error.

22. **Validate filenames against a pattern.** Paths like `../../etc/passwd` are caught by the sandbox, but proactively rejecting suspicious patterns would give clearer errors.

23. **Add `nofollow` option for symlink traversal in readonly roots.** `tools.py:96-98` follows symlinks into readonly roots. This is by design for site_inputs, but should be opt-in per-rule.

## Tier 5 — Spec & docs

24. **Document the Blocker numbering system.** Blockers #1, #7, #8, #10 appear in source comments but the numbering scheme is undocumented. Add a tracking file or use GitHub issues.

25. **Write a migration guide: demo → core-bootstrap.** The transition happened but users following old docs will hit the quarantined demo.

26. **Document `equivalence` field semantics with examples.** `exact` vs `free` are mentioned in `ir.py` and `compare.py` but not explained in any user-facing doc.

27. **Document cost_tolerance in the Design IR section of SKILL.md.** The `ratio: [0.5, 2.0]` bounds appear in core-bootstrap but are never explained in the skill.

28. **Freeze the three-machine proof contract.** `docs/three-machine-proof.md` describes 8 gates but the doc itself is still evolving. Freeze it like CSE-v1.

29. **Add a "Husks for the impatient" quick-start.** The current docs assume you'll read theory first. A 30-second `init → check → run → verify` walkthrough would help.

## Tier 6 — Code quality & dedup

30. **Extract `collect_dry_residue` and `collect_hydrated_residue` from `build.py`.** They're 50+ lines each and belong in `residue.py` alongside the dataclasses they construct.

31. **Unify subprocess CLI helpers across tests.** `test_SOLID_10`, `test_SOLID_38`, `test_LIQUID_71`, `test_LIQUID_72` each define their own `run_husks_cli` wrapper. Put one in `conftest.py`.

32. **Remove manual input copying in tests.** Three-machine tests manually copy `site_inputs` files instead of using the IR's `site_inputs` resolution. This duplicates `ir.py:normalize_site_inputs` logic.

33. **Consolidate freshness state calculation.** Both `manifest.py` and `cli/cmd/inspect.py:18` compute freshness. One canonical function.

34. **Clean up the `explain` command's legacy flags.** `--graph` is `argparse.SUPPRESS` (backwards-compat no-op at `main.py:280`). If nothing uses it, delete it.

## Tier 7 — Build engine improvements

36. **Surface `trial` in SKILL.md.** The two-form vocabulary (action + oracle) is the skill's teaching model, but `trial` exists in the engine (`transport.py`, `eval.py:613`). Document when to use it.

37. **Improve trial branch failure diagnostics.** `eval.py:613` reports "trial: all branches failed" with no detail on which branch failed or why.

38. **Add `cond` and `let` to the Design IR.** They exist in the CSE spec (`transport.py` form tags) and engine but have no JSON surface in `ir.py`. This limits design expressiveness.

39. **Implement fuel reclamation.** When a sealed rule is skipped on re-run, its fuel is not returned to the global budget. This means re-runs of partially-complete builds waste budget on rules that won't fire.

40. **Add `--fuel-report` flag to show per-rule fuel consumption.** The data exists in the Store but isn't surfaced in the CLI unless you use `--json` and parse manually.

## Tier 8 — Verification & conformance

41. **Add a Python-only CSE reader conformance test.** `test_SOLID_8` tests JS cross-language verification. There's no test that the Python `core.py` reader passes the same conformance gate independently.

42. **Add a malformed-CSE fuzzer.** The 3 malformed vectors in `spec/conformance/` are hand-crafted. A property-based fuzzer (hypothesis) would find edge cases in `parse()`.

43. **Test `_MAX_PARSE_DEPTH` and `_MAX_ATOM_LENGTH` rejection.** The safety bounds in `core.py` are defined but their rejection behavior isn't tested.

44. **Add `husks doctor --conformance` to CI.** Currently only `--selftest` runs in CI. `--conformance` (external reader gate) could run in Solid Alpha.

45. **Verify that `.husk` files are bitwise-identical across platforms.** CSE is deterministic by spec, but endianness or newline handling could cause drift. Add a cross-platform golden vector.

## Tier 9 — Observability & DX

46. **Add `husks explain --trace <rule>` to show the full oracle transcript.** Currently you can see token counts and tool calls, but not the actual prompt/response exchange.

47. **Add progress estimation to `LiveFrameEmitter`.** The emitter shows elapsed time but not "3 of 7 rules complete". Simple ratio would help.

48. **Add `husks status --watch` for live site monitoring.** Poll the site directory and re-render on change. Useful during long oracle runs.

49. **Color-code fuel consumption in the DAG view.** Green for under-budget, yellow for near-limit, red for exhausted. The data is in `CliNode.fuel` / `CliNode.fuel_budget`.

50. **Add `husks explain --diff <rule>` between two sites.** Currently `--diff` shows sealed vs current artifacts in one site. Cross-site diff would support the three-machine workflow.
