"""test_validation.py -- Design validation tests."""

import pytest
from husks.locke import check, check_categorized, _resolve_targets, show, from_json, to_json, normalize_site_inputs


# ── Helpers ──────────────────────────────────────────────────────

def _minimal_design(**overrides):
    d = {
        "name": "test", "fuel": 10, "target": "w",
        "rules": [{"name": "w", "kind": "oracle", "outputs": ["out.txt"],
                    "prompt": "go", "fuel": 8}],
    }
    d.update(overrides)
    return d


# ── check: valid designs ─────────────────────────────────────────

class TestCheckValid:
    def test_minimal_valid(self):
        assert check(_minimal_design()) == []

    def test_action_with_run(self):
        d = _minimal_design(rules=[
            {"name": "w", "kind": "action", "outputs": ["out.txt"], "run": "echo hi"}])
        assert check(d) == []

    def test_commit_halt(self):
        d = _minimal_design(rules=[
            {"name": "ok", "kind": "commit", "value": "done"},
            {"name": "fail", "kind": "halt", "reason": "err"},
            {"name": "w", "kind": "oracle", "outputs": ["out.txt"], "prompt": "go", "fuel": 4},
        ])
        assert check(d) == []

    def test_let_rule(self):
        d = _minimal_design(target="alias", rules=[
            {"name": "base", "kind": "oracle", "outputs": ["out.txt"], "prompt": "go", "fuel": 4},
            {"name": "alias", "kind": "let", "bind": "base"},
        ])
        assert check(d) == []

    def test_cond_rule(self):
        d = _minimal_design(rules=[
            {"name": "ok", "kind": "commit", "value": "done"},
            {"name": "fail", "kind": "halt", "reason": "err"},
            {"name": "gate", "kind": "cond", "predicate": "file-exists:x", "then": "ok", "else": "fail"},
            {"name": "w", "kind": "oracle", "outputs": ["out.txt"], "prompt": "go", "fuel": 4},
        ], target="w")
        assert check(d) == []

    def test_trial_rule(self):
        d = _minimal_design(rules=[
            {"name": "t", "kind": "trial", "outputs": ["out.txt"],
             "branches": [{"kind": "oracle", "prompt": "a", "fuel": 4}]},
        ], target="t")
        assert check(d) == []

    def test_site_inputs_produce(self):
        d = _minimal_design(
            site_inputs={"data.txt": "/tmp/data.txt"},
            rules=[{"name": "w", "kind": "oracle", "outputs": ["out.txt"],
                     "inputs": ["data.txt"], "prompt": "go", "fuel": 4}])
        assert check(d) == []

    def test_equivalence_valid(self):
        d = _minimal_design(rules=[
            {"name": "w", "kind": "oracle", "outputs": ["a.txt", "b.txt"],
             "prompt": "go", "fuel": 4, "equivalence": {"a.txt": "free", "b.txt": "exact"}}])
        assert check(d) == []


# ── check: errors ────────────────────────────────────────────────

class TestCheckErrors:
    def test_no_name(self):
        d = _minimal_design(name=None)
        errs = check(d)
        assert any("no name" in e for e in errs)

    def test_no_fuel(self):
        d = _minimal_design(fuel=0)
        errs = check(d)
        assert any("no fuel" in e for e in errs)

    def test_no_rules(self):
        d = _minimal_design(rules=[])
        assert any("no rules" in e for e in check(d))

    def test_no_target(self):
        d = {"name": "t", "fuel": 10, "rules": [
            {"name": "w", "kind": "oracle", "outputs": ["out.txt"], "prompt": "go", "fuel": 4}]}
        assert any("no target" in e for e in check(d))

    def test_target_not_found(self):
        d = _minimal_design(target="nonexistent")
        assert any("does not match" in e for e in check(d))

    def test_duplicate_name(self):
        d = _minimal_design(rules=[
            {"name": "w", "kind": "oracle", "outputs": ["a.txt"], "prompt": "go", "fuel": 4},
            {"name": "w", "kind": "oracle", "outputs": ["b.txt"], "prompt": "go2", "fuel": 4},
        ])
        assert any("duplicate" in e for e in check(d))

    def test_no_outputs(self):
        d = _minimal_design(rules=[
            {"name": "w", "kind": "oracle", "outputs": [], "prompt": "go", "fuel": 4}])
        assert any("no declared outputs" in e for e in check(d))

    def test_duplicate_output(self):
        d = _minimal_design(rules=[
            {"name": "a", "kind": "oracle", "outputs": ["x.txt"], "prompt": "go", "fuel": 4},
            {"name": "w", "kind": "oracle", "outputs": ["x.txt"], "prompt": "go2", "fuel": 4},
        ])
        assert any("already produced" in e for e in check(d))

    def test_input_not_produced(self):
        d = _minimal_design(rules=[
            {"name": "w", "kind": "oracle", "outputs": ["out.txt"],
             "inputs": ["missing.txt"], "prompt": "go", "fuel": 4}])
        assert any("not produced" in e for e in check(d))

    def test_oracle_no_prompt(self):
        d = _minimal_design(rules=[
            {"name": "w", "kind": "oracle", "outputs": ["out.txt"], "fuel": 4}])
        assert any("no prompt" in e for e in check(d))

    def test_oracle_no_fuel(self):
        d = _minimal_design(rules=[
            {"name": "w", "kind": "oracle", "outputs": ["out.txt"], "prompt": "go"}])
        assert any("no fuel" in e for e in check(d))

    def test_unknown_kind(self):
        d = _minimal_design(rules=[{"name": "w", "kind": "bogus", "outputs": ["x"]}])
        assert any("kind must be" in e for e in check(d))

    def test_rule_name_with_slash(self):
        d = _minimal_design(rules=[
            {"name": "a/b", "kind": "oracle", "outputs": ["out.txt"], "prompt": "go", "fuel": 4}])
        assert any("path separator" in e for e in check(d))

    def test_output_path_traversal(self):
        d = _minimal_design(rules=[
            {"name": "w", "kind": "oracle", "outputs": ["../escape.txt"], "prompt": "go", "fuel": 4}])
        assert any("'..'" in e for e in check(d))

    def test_unknown_design_field(self):
        d = _minimal_design(bogus="x")
        assert any("unknown design field" in e for e in check(d))

    def test_unknown_rule_field(self):
        d = _minimal_design(rules=[
            {"name": "w", "kind": "oracle", "outputs": ["out.txt"],
             "prompt": "go", "fuel": 4, "bogus": "x"}])
        assert any("unknown field" in e for e in check(d))

    def test_commit_no_value(self):
        d = _minimal_design(rules=[{"name": "w", "kind": "commit"}], target="w")
        assert any("no value" in e for e in check(d))

    def test_halt_no_reason(self):
        d = _minimal_design(rules=[{"name": "w", "kind": "halt"}], target="w")
        assert any("no reason" in e for e in check(d))

    def test_let_no_bind(self):
        d = _minimal_design(rules=[
            {"name": "w", "kind": "oracle", "outputs": ["out.txt"], "prompt": "go", "fuel": 4},
            {"name": "alias", "kind": "let"},
        ])
        assert any("no bind" in e for e in check(d))

    def test_cond_missing_fields(self):
        d = _minimal_design(rules=[
            {"name": "w", "kind": "cond"},
            {"name": "a", "kind": "oracle", "outputs": ["out.txt"], "prompt": "go", "fuel": 4},
        ], target="a")
        errs = check(d)
        assert any("no predicate" in e for e in errs)

    def test_equivalence_invalid_relation(self):
        d = _minimal_design(rules=[
            {"name": "w", "kind": "oracle", "outputs": ["a.txt"],
             "prompt": "go", "fuel": 4, "equivalence": {"a.txt": "bogus"}}])
        assert any("'exact' or 'free'" in e for e in check(d))

    def test_forward_reference(self):
        d = _minimal_design(rules=[
            {"name": "w", "kind": "oracle", "outputs": ["out.txt"],
             "inputs": ["dep.txt"], "prompt": "go", "fuel": 4},
            {"name": "dep", "kind": "action", "outputs": ["dep.txt"], "run": "make"},
        ])
        assert any("forward reference" in e for e in check(d))

    def test_imports_collision(self):
        d = _minimal_design(
            imports={"out.txt": "/tmp/ext"},
            rules=[{"name": "w", "kind": "oracle", "outputs": ["out.txt"],
                     "prompt": "go", "fuel": 4}])
        assert any("collides" in e for e in check(d))


# ── check_categorized ────────────────────────────────────────────

class TestCheckCategorized:
    def test_valid_design(self):
        result = check_categorized(_minimal_design())
        assert result["ok"]
        assert result["errors"] == []

    def test_categorized_errors(self):
        d = _minimal_design(name=None, fuel=0)
        result = check_categorized(d)
        assert not result["ok"]
        assert len(result["errors"]) > 0
        assert any(not c["ok"] for c in result["categories"].values())


# ── _resolve_targets ─────────────────────────────────────────────

class TestResolveTargets:
    def test_target_string(self):
        assert _resolve_targets({"target": "w"}) == ["w"]

    def test_targets_list(self):
        assert _resolve_targets({"targets": ["a", "b"]}) == ["a", "b"]

    def test_no_target(self):
        assert _resolve_targets({}) is None


# ── show ─────────────────────────────────────────────────────────

class TestShow:
    def test_show_returns_string(self):
        d = _minimal_design()
        s = show(d)
        assert isinstance(s, str)
        assert "test" in s
        assert "oracle" in s

    def test_show_with_site_inputs(self):
        d = _minimal_design(site_inputs={"data.txt": "/tmp/data.txt"})
        s = show(d)
        assert "data.txt" in s


# ── I/O ──────────────────────────────────────────────────────────

class TestIO:
    def test_to_from_json(self, tmp_path):
        d = _minimal_design()
        p = tmp_path / "design.json"
        to_json(d, str(p))
        loaded = from_json(str(p))
        assert loaded["name"] == "test"
        assert "_source_path" in loaded

    def test_to_json_string(self):
        d = _minimal_design()
        s = to_json(d)
        import json
        assert json.loads(s)["name"] == "test"


class TestNormalizeSiteInputs:
    def test_none(self):
        assert normalize_site_inputs(None) == {}

    def test_absolute_list(self, tmp_path):
        f = tmp_path / "data.txt"
        f.write_text("x")
        result = normalize_site_inputs([str(f)])
        assert "data.txt" in result

    def test_dict_absolute(self, tmp_path):
        f = tmp_path / "data.txt"
        f.write_text("x")
        result = normalize_site_inputs({"input": str(f)})
        assert result["input"] == str(f.resolve())

    def test_relative_requires_source(self):
        with pytest.raises(ValueError, match="requires design source path"):
            normalize_site_inputs(["relative.txt"])

    def test_missing_file(self, tmp_path):
        with pytest.raises(ValueError, match="does not exist"):
            normalize_site_inputs([str(tmp_path / "nope.txt")])

    def test_relative_with_source(self, tmp_path):
        f = tmp_path / "data.txt"
        f.write_text("x")
        design_path = str(tmp_path / "design.json")
        result = normalize_site_inputs(["data.txt"], design_path)
        assert result["data.txt"] == str(f.resolve())
