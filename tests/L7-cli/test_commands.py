"""test_commands.py -- Residue collectors, commands, argparse."""

import json
import sys
import pytest
from pathlib import Path
from husks.cli import (
    collect_dry_residue, collect_hydrated_residue,
    _cmd_doctor, _cmd_status, _cmd_history, _cmd_compare, _cmd_verify,
    _cmd_cache_export, _cmd_cache_import,
    main, _cli_entry, resolve_design,
    EXIT_OK, EXIT_BUILD_FAIL, EXIT_USAGE, EXIT_MISSING_DEP,
)
from husks.report import CliResidue, CliNode
from conftest import _write_manifest, _write_seal, _write_history


# ── assemble() round-trip ─────────────────────────────────────

class TestAssembleRoundTrip:
    """Verify that engine trace events produce non-empty report nodes via assemble()."""

    def test_engine_events_to_report(self, tmp_site, minimal_design):
        """Engine node_done/rule_start/artifact events produce non-empty assemble() output."""
        from husks.report import assemble
        site = str(tmp_site)
        S = {
            "site": site, "status": "committed", "build-root": "root123",
            "fuel": 7, "run-id": "run-1",
            "usage": {
                "total_cost_usd": 0.01,
                "total_input_tokens": 100,
                "total_output_tokens": 50,
                "by_rule": {
                    "w": {"cost_usd": 0.01, "input_tokens": 100, "output_tokens": 50,
                          "fuel_consumed": 3, "cached": False,
                          "backend": "litellm", "model": "claude-haiku",
                          "config_hash": None, "prompt_hash": None},
                },
            },
            "trace": [
                {"event": "rule_start", "rule": "w", "stale_reason": "no_seal"},
                {"event": "fired", "rule": "w", "outputs": ["out.txt"]},
                {"event": "artifact", "path": "out.txt", "hash": "abc123"},
                {"event": "node_done", "name": "w", "state": "fired", "elapsed": 1.5},
            ],
        }
        report = assemble(S, S["trace"], minimal_design)
        assert len(report["nodes"]) == 1
        nd = report["nodes"][0]
        assert nd["name"] == "w"
        assert nd["state"] == "fired"
        assert nd["tokens"]["input"] == 100
        assert nd["tokens"]["output"] == 50
        assert nd.get("backend") == "litellm"
        assert nd.get("model") == "claude-haiku"

    def test_sealed_node_produces_report_node(self, tmp_site, minimal_design):
        """Engine sealed + node_done(reused) produces a report node."""
        from husks.report import assemble
        site = str(tmp_site)
        S = {
            "site": site, "status": "committed", "build-root": "root123",
            "fuel": 10, "run-id": "run-1",
            "usage": {"total_cost_usd": 0.0, "by_rule": {}},
            "trace": [
                {"event": "sealed", "rule": "w"},
                {"event": "node_done", "name": "w", "state": "reused", "elapsed": 0.0},
            ],
        }
        report = assemble(S, S["trace"], minimal_design)
        assert len(report["nodes"]) == 1
        assert report["nodes"][0]["state"] == "sealed"

    def test_halted_node_has_diagnosis(self, tmp_site, minimal_design):
        """Engine rule-halted + node_done(failed) produces diagnosis."""
        from husks.report import assemble
        site = str(tmp_site)
        S = {
            "site": site, "status": "halted", "build-root": None,
            "fuel": 0, "run-id": "run-1",
            "usage": {"total_cost_usd": 0.0, "by_rule": {}},
            "trace": [
                {"event": "rule_start", "rule": "w", "stale_reason": "no_seal"},
                {"event": "rule-halted", "rule": "w", "error": "timeout"},
                {"event": "rule_halted", "rule": "w", "reason": "timeout"},
                {"event": "node_done", "name": "w", "state": "failed", "elapsed": 5.0},
            ],
        }
        report = assemble(S, S["trace"], minimal_design)
        assert len(report["nodes"]) == 1
        nd = report["nodes"][0]
        assert nd["state"] == "failed"
        assert nd["diagnosis"]["error"] == "timeout"
        assert nd["diagnosis"]["stale_reason"] == "no_seal"


# ── §6 Residue collectors ────────────────────────────────────

class TestCollectDryResidue:
    def test_basic(self, minimal_design):
        r = collect_dry_residue(minimal_design)
        assert isinstance(r, CliResidue)
        assert r.command == "check"
        assert r.status == "dry"
        assert len(r.nodes) == 1
        assert r.nodes[0].name == "w"
        assert r.nodes[0].state == "unrealized"

    def test_multi_rule(self, multi_rule_design):
        r = collect_dry_residue(multi_rule_design)
        assert len(r.nodes) == 2
        # Target w should be first
        assert r.nodes[0].name == "w"
        # w depends on dep (dep's outputs overlap w's inputs)
        assert "dep" in r.nodes[0].children

    def test_fuel_budget(self, minimal_design):
        r = collect_dry_residue(minimal_design)
        assert r.fuel_budget == 10

    def test_no_target(self):
        design = {"name": "test", "fuel": 5,
                  "rules": [{"name": "a", "kind": "action", "outputs": []}]}
        r = collect_dry_residue(design)
        assert r.target is None

    def test_passes(self, minimal_design):
        r = collect_dry_residue(minimal_design)
        assert "checks" in r.passes


class TestCollectHydratedResidue:
    def test_committed(self, tmp_site, minimal_design):
        S = {"site": str(tmp_site), "status": "committed",
             "build-root": "rootabc", "fuel": 7,
             "usage": {"total_cost_usd": 0.01, "by_rule": {
                 "w": {"cost_usd": 0.01, "input_tokens": 100, "output_tokens": 50}}},
             "trace": [{"event": "fired", "rule": "w"}]}
        r = collect_hydrated_residue(S, minimal_design)
        assert r.command == "run"
        assert r.status == "committed"
        assert r.root == "rootabc"
        assert r.fuel_used == 3  # 10 - 7
        assert len(r.nodes) == 1
        assert r.nodes[0].state == "sealed"  # fired -> sealed
        assert "run" in r.passes

    def test_halted(self, tmp_site, minimal_design):
        S = {"site": str(tmp_site), "status": "halted", "fuel": 0,
             "usage": {},
             "trace": [{"event": "rule-halted", "rule": "w", "error": "timeout"}]}
        r = collect_hydrated_residue(S, minimal_design)
        assert r.status == "halted"
        assert r.nodes[0].state == "failed"
        assert r.nodes[0].diagnosis == "timeout"
        assert "run" in r.fails

    def test_cached(self, tmp_site, minimal_design):
        S = {"site": str(tmp_site), "status": "committed",
             "build-root": "rootabc", "fuel": 10,
             "usage": {"by_rule": {"w": {"cached": True}}},
             "trace": [{"event": "sealed", "rule": "w"}]}
        r = collect_hydrated_residue(S, minimal_design)
        assert r.nodes[0].state == "cached"
        assert r.nodes[0].cache is True
        assert "cache" in r.passes

    def test_multi_rule(self, tmp_site, multi_rule_design):
        S = {"site": str(tmp_site), "status": "committed",
             "build-root": "root", "fuel": 5,
             "usage": {"by_rule": {}},
             "trace": [{"event": "fired", "rule": "dep"},
                       {"event": "fired", "rule": "w"}]}
        r = collect_hydrated_residue(S, multi_rule_design)
        assert len(r.nodes) == 2
        # Target w should be first
        assert r.nodes[0].name == "w"

    def test_husk_hash(self, tmp_site, minimal_design):
        (tmp_site / "test.husk").write_bytes(b"husk-data")
        S = {"site": str(tmp_site), "status": "committed",
             "build-root": "root", "fuel": 10,
             "usage": {}, "trace": []}
        r = collect_hydrated_residue(S, minimal_design)
        assert r.husk_hash is not None
        assert len(r.husk_hash) == 64  # SHA-256 hex


# ── §7 Commands ───────────────────────────────────────────────

class TestCmdDoctor:
    def test_basic(self, capsys):
        args = _make_args(json_output=False, selftest=False)
        _cmd_doctor(args)
        out = capsys.readouterr().out
        assert out == ""

    def test_json(self, capsys):
        args = _make_args(json_output=True, selftest=False)
        _cmd_doctor(args)
        out = capsys.readouterr().out
        data = json.loads(out)
        assert "checks" in data
        assert all(c["ok"] for c in data["checks"])

    def test_arch_clean(self, capsys):
        args = _make_args(json_output=True, selftest=False, arch=True)
        _cmd_doctor(args)
        data = json.loads(capsys.readouterr().out)
        assert "arch" in data
        # The shipped package must satisfy its own layer contract.
        assert data["arch"]["status"] == "ok", data["arch"]
        assert data["arch"]["violations"] == []
        assert data["arch"]["unassigned"] == []

    def test_arch_detects_violation(self, tmp_path, monkeypatch):
        # A layers.toml that puts two import-related modules on the same
        # layer must be reported as a strict-lower violation.
        from husks import cli as _cli
        bad = tmp_path / "layers.toml"
        bad.write_text(
            "[layers]\n"
            '"husks.kernel" = 0\n'
            '"husks.forms" = 0\n'
        )
        monkeypatch.setattr(_cli, "_find_layers_toml", lambda: bad)
        report = _cli._arch_check()
        assert report["status"] == "violations"
        assert any(v["module"] == "husks.forms"
                   and v["imports"] == "husks.kernel"
                   for v in report["violations"])


class TestCmdStatus:
    def test_basic(self, tmp_site, write_manifest, write_seal, capsys):
        (tmp_site / "out.txt").write_text("data")
        from husks.report import file_hash
        h = file_hash(str(tmp_site / "out.txt"))
        write_manifest(tmp_site)
        write_seal(tmp_site, "w", outputs={"out.txt": h})
        args = _make_args(site=str(tmp_site), json_output=False, verbose=False,
                          fail_if_dirty=False, fail_if_stale=False)
        _cmd_status(args)
        out = capsys.readouterr().out
        assert "test" in out

    def test_json(self, tmp_site, write_manifest, capsys):
        write_manifest(tmp_site)
        args = _make_args(site=str(tmp_site), json_output=True, verbose=False,
                          fail_if_dirty=False, fail_if_stale=False)
        _cmd_status(args)
        out = capsys.readouterr().out
        data = json.loads(out)
        assert data["name"] == "test"

    def test_husk_hash_when_sealed(self, tmp_site, write_manifest, write_seal, capsys):
        (tmp_site / "out.txt").write_text("data")
        from husks.report import file_hash
        h = file_hash(str(tmp_site / "out.txt"))
        write_manifest(tmp_site)
        write_seal(tmp_site, "w", outputs={"out.txt": h})
        # Write a .husk file
        (tmp_site / "test.husk").write_bytes(b"husk-data")
        args = _make_args(site=str(tmp_site), json_output=True, verbose=False,
                          fail_if_dirty=False, fail_if_stale=False)
        _cmd_status(args)
        data = json.loads(capsys.readouterr().out)
        assert data["husk"] is not None
        assert len(data["husk"]) == 64

    def test_cost_from_report(self, tmp_site, write_manifest, capsys):
        write_manifest(tmp_site)
        report = {"cost": {"paid": 0.0345}, "fuel": {"start": 5, "end": 3}}
        (tmp_site / ".traces" / "report.json").write_text(json.dumps(report))
        args = _make_args(site=str(tmp_site), json_output=True, verbose=False,
                          fail_if_dirty=False, fail_if_stale=False)
        _cmd_status(args)
        data = json.loads(capsys.readouterr().out)
        assert data["cost"] == pytest.approx(0.0345)
        assert data["fuel_used"] == 2

    def test_cost_from_history(self, tmp_site, write_manifest, write_history, capsys):
        """Falls back to history entries when no report.json."""
        write_manifest(tmp_site)
        write_history(tmp_site, "w", [
            {"cost_usd": 0.031, "fuel_consumed": 3},
        ])
        args = _make_args(site=str(tmp_site), json_output=True, verbose=False,
                          fail_if_dirty=False, fail_if_stale=False)
        _cmd_status(args)
        data = json.loads(capsys.readouterr().out)
        assert data["cost"] == pytest.approx(0.031)
        assert data["fuel_used"] == 3

    def test_verbose_shows_dag_and_expense(self, tmp_site, write_manifest, write_seal, write_history, capsys):
        """Verbose status shows full DAG tree with per-node expense."""
        (tmp_site / "out.txt").write_text("data")
        (tmp_site / "dep.txt").write_text("dep-data")
        from husks.report import file_hash
        h_out = file_hash(str(tmp_site / "out.txt"))
        h_dep = file_hash(str(tmp_site / "dep.txt"))
        rules = [
            {"name": "w", "kind": "oracle", "outputs": ["out.txt"],
             "inputs": ["dep.txt"], "children": ["dep"]},
            {"name": "dep", "kind": "action", "outputs": ["dep.txt"], "inputs": []},
        ]
        write_manifest(tmp_site, rules=rules)
        write_seal(tmp_site, "w", outputs={"out.txt": h_out})
        write_seal(tmp_site, "dep", outputs={"dep.txt": h_dep})
        write_history(tmp_site, "w", [
            {"cost_usd": 0.031, "fuel_consumed": 3, "tokens_in": 15420,
             "tokens_out": 3143, "elapsed_s": 24.0},
        ])
        args = _make_args(site=str(tmp_site), json_output=False, verbose=True,
                          fail_if_dirty=False, fail_if_stale=False)
        _cmd_status(args)
        out = capsys.readouterr().out
        assert "w" in out
        assert "dep" in out
        assert "15.4kin" in out
        assert "3.1kout" in out
        assert "24.0s" in out

    def test_fail_if_stale(self, tmp_site, write_manifest):
        write_manifest(tmp_site)
        # No seal, so rules are stale
        args = _make_args(site=str(tmp_site), json_output=False, verbose=False,
                          fail_if_dirty=False, fail_if_stale=True)
        with pytest.raises(SystemExit) as exc:
            _cmd_status(args)
        assert exc.value.code == 4


class TestCmdHistory:
    def test_single_rule(self, tmp_site, write_manifest, write_history, capsys):
        write_manifest(tmp_site)
        write_history(tmp_site, "w", [
            {"fuel_consumed": 3, "output_hashes": ["h1"]},
        ])
        args = _make_args(site=str(tmp_site), rule="w", n=5, json_output=False)
        _cmd_history(args)
        out = capsys.readouterr().out
        assert "w" in out

    def test_json(self, tmp_site, write_manifest, write_history, capsys):
        write_manifest(tmp_site)
        write_history(tmp_site, "w", [
            {"fuel_consumed": 3, "output_hashes": ["h1"]},
        ])
        args = _make_args(site=str(tmp_site), rule="w", n=5, json_output=True)
        _cmd_history(args)
        out = capsys.readouterr().out
        data = json.loads(out)
        assert data["classification"] in ("stable", "converging", "no-data")

    def test_all_rules(self, tmp_site, write_manifest, write_history, capsys):
        write_manifest(tmp_site)
        write_history(tmp_site, "w", [
            {"fuel_consumed": 3, "output_hashes": ["h1"]},
        ])
        args = _make_args(site=str(tmp_site), rule=None, n=5, json_output=False)
        _cmd_history(args)
        out = capsys.readouterr().out
        # Renders as a status card with convergence on right
        assert "w" in out
        assert "history" in out  # stage label
        assert "fuel" in out

    def test_all_rules_dag(self, tmp_site, write_history, capsys):
        """Multi-rule history renders as status card with DAG tree and convergence trends."""
        rules = [
            {"name": "w", "kind": "oracle", "outputs": ["out.txt"],
             "inputs": ["dep.txt"], "children": ["dep"]},
            {"name": "dep", "kind": "action", "outputs": ["dep.txt"], "inputs": []},
        ]
        _write_manifest(tmp_site, rules=rules)
        write_history(tmp_site, "dep", [
            {"fuel_consumed": 1, "output_hashes": ["d1"]},
        ])
        write_history(tmp_site, "w", [
            {"fuel_consumed": 3, "output_hashes": ["h1"]},
            {"fuel_consumed": 3, "output_hashes": ["h1"]},
        ])
        args = _make_args(site=str(tmp_site), rule=None, n=5, json_output=False)
        _cmd_history(args)
        out = capsys.readouterr().out
        assert "w" in out
        assert "dep" in out
        # Tree connector present (dep is child of w)
        assert "\u2514" in out or "\u251c" in out
        # Classification labels present
        assert "stable" in out or "converging" in out or "no-data" in out


class TestCmdCompare:
    def test_identical_sites(self, tmp_site, write_manifest, write_seal, capsys):
        (tmp_site / "out.txt").write_text("data")
        from husks.report import file_hash
        h = file_hash(str(tmp_site / "out.txt"))
        write_manifest(tmp_site)
        write_seal(tmp_site, "w", outputs={"out.txt": h})
        args = _make_args(sites=[str(tmp_site), str(tmp_site)],
                          json_output=False, roots_only=False, hashes_only=False)
        _cmd_compare(args)
        out = capsys.readouterr().out
        assert "\u2713" in out

    def test_json(self, tmp_site, write_manifest, write_seal, capsys):
        write_manifest(tmp_site)
        args = _make_args(sites=[str(tmp_site), str(tmp_site)],
                          json_output=True, roots_only=False, hashes_only=False)
        _cmd_compare(args)
        out = capsys.readouterr().out
        data = json.loads(out)
        assert "equivalent" in data

    def test_visual_shows_site_cards(self, tmp_site, write_manifest, write_seal, write_history, capsys):
        """Compare renders each site like status verbose."""
        (tmp_site / "out.txt").write_text("data")
        from husks.report import file_hash
        h = file_hash(str(tmp_site / "out.txt"))
        write_manifest(tmp_site)
        write_seal(tmp_site, "w", outputs={"out.txt": h})
        write_history(tmp_site, "w", [
            {"cost_usd": 0.03, "fuel_consumed": 3, "tokens_in": 15000,
             "tokens_out": 3000, "elapsed_s": 24.0},
        ])
        args = _make_args(sites=[str(tmp_site), str(tmp_site)],
                          json_output=False, roots_only=False, hashes_only=False)
        _cmd_compare(args)
        out = capsys.readouterr().out
        # Should show site cards with expense
        assert "15.0kin" in out
        assert "3.0kout" in out
        # Should show equivalence section
        assert "equivalence" in out
        assert "\u2713" in out  # pass symbol

    def test_three_machine_proof(self, tmp_path, capsys):
        """Three sites triggers proof checks."""
        from husks.report import file_hash
        husk_data = b"identical-husk-content"
        sites = []
        for label in ["m1", "m2", "m3"]:
            site = tmp_path / label
            site.mkdir()
            (site / ".traces").mkdir()
            (site / "out.txt").write_text("data")
            (site / "test.husk").write_bytes(husk_data)
            h = file_hash(str(site / "out.txt"))
            _write_manifest(site, root="same_root")
            _write_seal(site, "w", outputs={"out.txt": h})
            if label == "m2":
                _write_history(site, "w", [
                    {"cost_usd": 0.0, "fuel_consumed": 0, "tokens_in": 0,
                     "tokens_out": 0, "elapsed_s": 0.1, "cached": True},
                ])
            else:
                _write_history(site, "w", [
                    {"cost_usd": 0.03, "fuel_consumed": 3, "tokens_in": 15000,
                     "tokens_out": 3000, "elapsed_s": 24.0},
                ])
            sites.append(str(site))
        args = _make_args(sites=sites, json_output=False,
                          roots_only=False, hashes_only=False)
        try:
            _cmd_compare(args)
        except SystemExit:
            pass  # equivalence may fail on temp paths
        out = capsys.readouterr().out
        assert "three-machine proof" in out
        assert "husk identical" in out
        assert "root identical" in out
        # Synthetic .husk files can't pass root validity, so proof may not be satisfied.
        # Just verify the proof structure renders.
        assert "root valid" in out

    def test_three_machine_json(self, tmp_path, capsys):
        """Three-machine proof in JSON mode includes proof field."""
        from husks.report import file_hash
        husk_data = b"identical-husk-content"
        sites = []
        for label in ["m1", "m2", "m3"]:
            site = tmp_path / label
            site.mkdir()
            (site / ".traces").mkdir()
            (site / "out.txt").write_text("data")
            (site / "test.husk").write_bytes(husk_data)
            h = file_hash(str(site / "out.txt"))
            _write_manifest(site, root="same_root")
            _write_seal(site, "w", outputs={"out.txt": h})
            is_m2 = (label == "m2")
            _write_history(site, "w", [
                {"cost_usd": 0.0 if is_m2 else 0.03,
                 "fuel_consumed": 0 if is_m2 else 3,
                 "tokens_in": 0 if is_m2 else 15000,
                 "tokens_out": 0 if is_m2 else 3000,
                 "elapsed_s": 1.0,
                 "cached": True if is_m2 else False},
            ])
            sites.append(str(site))
        args = _make_args(sites=sites, json_output=True,
                          roots_only=False, hashes_only=False)
        try:
            _cmd_compare(args)
        except SystemExit:
            pass
        data = json.loads(capsys.readouterr().out)
        assert "proof" in data
        # Synthetic .husk files can't pass root validity recomputation, so proof
        # is not fully satisfied. Verify structural invariants pass and required
        # checks are present.
        checks = {c["label"]: c for c in data["proof"]["checks"]}
        assert checks["M1\u2194M2\u2194M3 husk identical"]["ok"] is True
        assert checks["M1\u2194M2 root identical"]["ok"] is True
        assert checks["M1\u2194M3 acceptance equivalent"]["ok"] is True
        # Root validity checks are required but fail with synthetic data
        for label in ("M1 root valid", "M2 root valid", "M3 root valid"):
            assert label in checks
            assert checks[label]["required"] is True
        # Oracle evidence checks are required and pass
        assert checks["M1 fired oracles"]["ok"] is True
        assert checks["M2 cache reuse"]["ok"] is True
        assert checks["M3 fired oracles"]["ok"] is True

    def test_too_few_sites(self, capsys):
        args = _make_args(sites=["/tmp/a"], json_output=False,
                          roots_only=False, hashes_only=False)
        with pytest.raises(SystemExit) as exc:
            _cmd_compare(args)
        assert exc.value.code == 2


class TestCmdVerify:
    def test_missing_site(self, capsys):
        args = _make_args(site="/tmp/nonexistent_husks_site_xyz", name=None,
                          json_output=False)
        with pytest.raises(SystemExit) as exc:
            _cmd_verify(args)
        assert exc.value.code == 2

    def test_no_husk_files(self, tmp_site, capsys):
        args = _make_args(site=str(tmp_site), name=None, json_output=False)
        with pytest.raises(SystemExit) as exc:
            _cmd_verify(args)
        assert exc.value.code == 1

    def test_root_mismatch(self, tmp_site, write_manifest, capsys, monkeypatch):
        """Verify fails when recomputed root != manifest root."""
        (tmp_site / "test.husk").write_bytes(b"fake")
        write_manifest(tmp_site, root="manifest_root_that_will_not_match")
        import husks.kernel
        monkeypatch.setattr(husks.kernel, "recompute_root", lambda _b, _s: "recomputed_abc123")
        args = _make_args(site=str(tmp_site), name=None, json_output=False, verbose=True)
        with pytest.raises(SystemExit) as exc:
            _cmd_verify(args)
        assert exc.value.code == EXIT_BUILD_FAIL
        err = capsys.readouterr().out
        assert "root mismatch" in err

    def test_root_mismatch_json(self, tmp_site, write_manifest, capsys, monkeypatch):
        """Verify JSON mode reports errors on mismatch."""
        (tmp_site / "test.husk").write_bytes(b"fake")
        write_manifest(tmp_site, root="wrong_root")
        import husks.kernel
        monkeypatch.setattr(husks.kernel, "recompute_root", lambda _b, _s: "recomputed_abc123")
        args = _make_args(site=str(tmp_site), name=None, json_output=True)
        with pytest.raises(SystemExit) as exc:
            _cmd_verify(args)
        assert exc.value.code == EXIT_BUILD_FAIL
        data = json.loads(capsys.readouterr().out)
        assert data["status"] == "failed"
        assert len(data["errors"]) >= 1

    def test_no_manifest(self, tmp_path, capsys, monkeypatch):
        """Verify fails when no manifest exists."""
        site = tmp_path / "empty_site"
        site.mkdir()
        (site / ".traces").mkdir()
        (site / "test.husk").write_bytes(b"fake")
        import husks.kernel
        monkeypatch.setattr(husks.kernel, "recompute_root", lambda _b, _s: "some_root_hash")
        args = _make_args(site=str(site), name=None, json_output=False, verbose=True)
        with pytest.raises(SystemExit) as exc:
            _cmd_verify(args)
        assert exc.value.code == EXIT_BUILD_FAIL
        err = capsys.readouterr().out
        assert "no manifest" in err

    def test_husk_parse_error(self, tmp_site, capsys):
        """Verify fails gracefully on unparseable .husk file."""
        (tmp_site / "test.husk").write_bytes(b"not-valid-cse")
        args = _make_args(site=str(tmp_site), name=None, json_output=False, verbose=True)
        with pytest.raises(SystemExit) as exc:
            _cmd_verify(args)
        assert exc.value.code == EXIT_BUILD_FAIL
        err = capsys.readouterr().out
        assert "parse error" in err


# ── Cache export/import ───────────────────────────────────────

class TestCmdCacheExport:
    def _populate_cache(self, site):
        """Write a minimal servable cache entry."""
        from husks.seal import fresh_store
        from husks.engine import cache_put
        S = fresh_store(str(site), fuel=1)
        recipe = {"type": "oracle", "prompt": "go", "tools": []}
        cache_put(S, recipe, [], {"out.txt": "hello"})
        return S

    def test_export_round_trip(self, tmp_site, capsys):
        self._populate_cache(tmp_site)
        export_path = str(tmp_site / "cache.tar.gz")
        args = _make_args(site=str(tmp_site), file=export_path, json_output=False, verbose=True)
        with pytest.raises(SystemExit) as exc:
            _cmd_cache_export(args)
        assert exc.value.code == 0
        out = capsys.readouterr().out
        assert "exported" in out
        assert Path(export_path).is_file()

    def test_export_json(self, tmp_site, capsys):
        self._populate_cache(tmp_site)
        export_path = str(tmp_site / "cache.tar.gz")
        args = _make_args(site=str(tmp_site), file=export_path, json_output=True)
        with pytest.raises(SystemExit) as exc:
            _cmd_cache_export(args)
        assert exc.value.code == 0
        data = json.loads(capsys.readouterr().out)
        assert data["status"] == "exported"
        assert isinstance(data["entries"], int)

    def test_export_bad_extension(self, tmp_site):
        args = _make_args(site=str(tmp_site), file="cache.zip", json_output=False)
        with pytest.raises(SystemExit) as exc:
            _cmd_cache_export(args)
        assert exc.value.code == 2

    def test_export_missing_site(self):
        args = _make_args(site="/tmp/nonexistent_husks_xyz", file="c.tar.gz",
                          json_output=False)
        with pytest.raises(SystemExit) as exc:
            _cmd_cache_export(args)
        assert exc.value.code == 2

    def test_export_empty_cache(self, tmp_site, capsys):
        export_path = str(tmp_site / "cache.tar.gz")
        args = _make_args(site=str(tmp_site), file=export_path, json_output=True)
        with pytest.raises(SystemExit) as exc:
            _cmd_cache_export(args)
        assert exc.value.code == 0
        data = json.loads(capsys.readouterr().out)
        assert data["entries"] == 0


class TestCmdCacheImport:
    def _export_from(self, site):
        """Populate cache and export to tarball, return path."""
        from husks.seal import fresh_store
        from husks.engine import cache_put, cache_export
        S = fresh_store(str(site), fuel=1)
        recipe = {"type": "oracle", "prompt": "go", "tools": []}
        cache_put(S, recipe, [], {"out.txt": "hello"})
        p = str(site / "cache.tar.gz")
        cache_export(S, p)
        return p

    def test_import_round_trip(self, tmp_path, capsys):
        src = tmp_path / "src_site"
        src.mkdir(); (src / ".traces").mkdir()
        tarball = self._export_from(src)
        dst = tmp_path / "dst_site"
        dst.mkdir(); (dst / ".traces").mkdir()
        args = _make_args(site=str(dst), file=tarball, no_merge=False,
                          json_output=True)
        with pytest.raises(SystemExit) as exc:
            _cmd_cache_import(args)
        assert exc.value.code == 0
        data = json.loads(capsys.readouterr().out)
        assert data["status"] == "imported"
        assert data["entries"] >= 1

    def test_import_missing_file(self, tmp_site):
        args = _make_args(site=str(tmp_site), file="/tmp/nonexistent.tar.gz",
                          no_merge=False, json_output=False)
        with pytest.raises(SystemExit) as exc:
            _cmd_cache_import(args)
        assert exc.value.code == 2

    def test_import_bad_extension(self, tmp_site):
        args = _make_args(site=str(tmp_site), file="cache.zip",
                          no_merge=False, json_output=False)
        with pytest.raises(SystemExit) as exc:
            _cmd_cache_import(args)
        assert exc.value.code == 2


# ── Reuse-only flag ──────────────────────────────────────────

class TestCollectHydratedResidueReuseOnly:
    def test_reuse_only_flag_in_store(self, tmp_site, minimal_design):
        """Verify --reuse-only sets cache-reuse-only in Store."""
        S = {"site": str(tmp_site), "status": "committed",
             "build-root": "root", "fuel": 10, "cache-reuse-only": True,
             "usage": {"by_rule": {"w": {"cached": True}}},
             "trace": [{"event": "sealed", "rule": "w"}]}
        r = collect_hydrated_residue(S, minimal_design)
        assert r.nodes[0].cache is True
        assert r.nodes[0].state == "cached"


# ── §8 Main / argparse ───────────────────────────────────────

class TestResolveDesign:
    def test_explicit(self):
        args = _make_args(design="my.locke")
        assert resolve_design(args) == "my.locke"

    def test_auto_locke(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        (tmp_path / "design.locke").write_text("test")
        args = _make_args(design=None)
        assert resolve_design(args) == "design.locke"

    def test_auto_json(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        (tmp_path / "design.json").write_text("{}")
        args = _make_args(design=None)
        assert resolve_design(args) == "design.json"

    def test_no_design(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        args = _make_args(design=None)
        with pytest.raises(SystemExit) as exc:
            resolve_design(args)
        assert exc.value.code == 2


class TestMainArgparse:
    def test_help(self, monkeypatch, capsys):
        monkeypatch.setattr(sys, "argv", ["husks", "--help"])
        with pytest.raises(SystemExit) as exc:
            main()
        assert exc.value.code == 0
        out = capsys.readouterr().out
        assert "husks" in out

    def test_version(self, monkeypatch, capsys):
        monkeypatch.setattr(sys, "argv", ["husks", "--version"])
        with pytest.raises(SystemExit) as exc:
            main()
        assert exc.value.code == 0
        out = capsys.readouterr().out
        assert out.startswith("husks ")
        # A resolved version, not a placeholder.
        assert "hardened" not in out
        assert any(ch.isdigit() for ch in out)

    def test_no_command(self, monkeypatch, capsys):
        monkeypatch.setattr(sys, "argv", ["husks"])
        with pytest.raises(SystemExit) as exc:
            main()
        assert exc.value.code == 2

    def test_doctor(self, monkeypatch, capsys):
        monkeypatch.setattr(sys, "argv", ["husks", "doctor"])
        _cmd_doctor(_make_args(json_output=False, selftest=False))
        out = capsys.readouterr().out
        assert out == ""


class TestCliEntry:
    def test_keyboard_interrupt(self, monkeypatch):
        def _raise(*a, **kw): raise KeyboardInterrupt()
        monkeypatch.setattr("husks.cli.main", _raise)
        with pytest.raises(SystemExit) as exc:
            _cli_entry()
        assert exc.value.code == 130

    def test_unexpected_error(self, monkeypatch):
        def _raise(*a, **kw): raise RuntimeError("boom")
        monkeypatch.setattr("husks.cli.main", _raise)
        monkeypatch.setattr(sys, "argv", ["husks"])
        with pytest.raises(SystemExit) as exc:
            _cli_entry()
        assert exc.value.code == 5


# ── Helpers ───────────────────────────────────────────────────

class _Args:
    """Simple namespace for faking argparse results."""
    def __init__(self, **kw):
        for k, v in kw.items():
            setattr(self, k, v)


def _make_args(**kw):
    return _Args(**kw)
