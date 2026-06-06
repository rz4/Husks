"""test_manifest.py -- Manifest I/O, schema validation, freshness tests."""

import json
from husks.report import (
    validate_manifest_schema, validate_seal_schema,
    read_manifest, read_seal, read_trial_report,
    file_hash, compute_rule_state, compute_rule_states,
    compute_artifact_states,
)


# ── Schema validation ───────────────────────────────────────────

class TestManifestSchema:
    def test_valid(self):
        ok, err = validate_manifest_schema({
            "schema": "husks.build.manifest.v1",
            "name": "t", "root": "abc", "site": "/tmp",
            "run_id": "r1", "rules": [],
        })
        assert ok and err is None

    def test_missing_schema(self):
        ok, err = validate_manifest_schema({"name": "t"})
        assert not ok and "schema" in err

    def test_unsupported_schema(self):
        ok, err = validate_manifest_schema({
            "schema": "unknown.v99",
            "name": "t", "root": "abc", "site": "/tmp",
            "run_id": "r1", "rules": [],
        })
        assert not ok and "unsupported" in err

    def test_missing_field(self):
        ok, err = validate_manifest_schema({
            "schema": "husks.build.manifest.v1",
            "name": "t",
        })
        assert not ok and "missing" in err

    def test_wrong_type(self):
        ok, err = validate_manifest_schema({
            "schema": "husks.build.manifest.v1",
            "name": "t", "root": "abc", "site": "/tmp",
            "run_id": "r1", "rules": "not-a-list",
        })
        assert not ok and "list" in err


class TestSealSchema:
    def test_valid(self):
        ok, err = validate_seal_schema({
            "v": 1, "seal": "s", "recipe_digest": "rd",
            "inputs": {}, "outputs": {},
        })
        assert ok

    def test_missing_version(self):
        ok, err = validate_seal_schema({"seal": "s"})
        assert not ok

    def test_wrong_version_type(self):
        ok, _ = validate_seal_schema({
            "v": "1", "seal": "s", "recipe_digest": "rd",
            "inputs": {}, "outputs": {},
        })
        assert not ok

    def test_unsupported_version(self):
        ok, _ = validate_seal_schema({
            "v": 99, "seal": "s", "recipe_digest": "rd",
            "inputs": {}, "outputs": {},
        })
        assert not ok


# ── Manifest I/O ────────────────────────────────────────────────

class TestReadManifest:
    def test_read_valid(self, tmp_site, write_manifest):
        write_manifest(tmp_site)
        m = read_manifest(str(tmp_site))
        assert m is not None
        assert m["name"] == "test"

    def test_missing(self, tmp_path):
        assert read_manifest(str(tmp_path)) is None

    def test_corrupt(self, tmp_site):
        (tmp_site / ".traces" / "build.manifest.json").write_text("not json")
        assert read_manifest(str(tmp_site)) is None

    def test_invalid_schema(self, tmp_site):
        (tmp_site / ".traces" / "build.manifest.json").write_text(
            json.dumps({"schema": "bad", "name": "t"}))
        assert read_manifest(str(tmp_site)) is None


class TestReadSeal:
    def test_read_valid(self, tmp_site, write_seal):
        write_seal(tmp_site, "w")
        s = read_seal(str(tmp_site), "w")
        assert s is not None
        assert s["seal"] == "s1"

    def test_missing(self, tmp_site):
        assert read_seal(str(tmp_site), "w") is None

    def test_corrupt(self, tmp_site):
        (tmp_site / ".traces" / "w.seal").write_text("bad")
        assert read_seal(str(tmp_site), "w") is None


class TestReadTrialReport:
    def test_read(self, tmp_site):
        data = {"winner": "b1", "branches": []}
        (tmp_site / ".traces" / "t.trial.json").write_text(json.dumps(data))
        assert read_trial_report(str(tmp_site), "t")["winner"] == "b1"

    def test_missing(self, tmp_site):
        assert read_trial_report(str(tmp_site), "t") is None


# ── Freshness ───────────────────────────────────────────────────

class TestFileHash:
    def test_existing_file(self, tmp_path):
        f = tmp_path / "a.txt"
        f.write_text("hello")
        h = file_hash(str(f))
        assert h is not None and len(h) == 64

    def test_missing_file(self, tmp_path):
        assert file_hash(str(tmp_path / "nope")) is None


class TestComputeRuleState:
    def test_fresh(self, tmp_site, write_seal):
        (tmp_site / "out.txt").write_text("data")
        h = file_hash(str(tmp_site / "out.txt"))
        write_seal(tmp_site, "w", outputs={"out.txt": h})
        rule = {"name": "w", "outputs": ["out.txt"]}
        state, reason = compute_rule_state(str(tmp_site), rule,
                                           read_seal(str(tmp_site), "w"))
        assert state == "fresh"
        assert reason is None

    def test_output_missing(self, tmp_site, write_seal):
        write_seal(tmp_site, "w")
        rule = {"name": "w", "outputs": ["out.txt"]}
        state, reason = compute_rule_state(str(tmp_site), rule,
                                           read_seal(str(tmp_site), "w"))
        assert state == "missing"
        assert "output_missing" in reason

    def test_no_seal(self, tmp_site):
        (tmp_site / "out.txt").write_text("data")
        rule = {"name": "w", "outputs": ["out.txt"]}
        state, reason = compute_rule_state(str(tmp_site), rule, None)
        assert state == "stale" and reason == "no_seal"

    def test_input_changed(self, tmp_site, write_seal):
        (tmp_site / "out.txt").write_text("data")
        out_h = file_hash(str(tmp_site / "out.txt"))
        write_seal(tmp_site, "w", inputs={"in.txt": "old_hash"},
                   outputs={"out.txt": out_h})
        (tmp_site / "in.txt").write_text("new data")
        rule = {"name": "w", "outputs": ["out.txt"]}
        state, reason = compute_rule_state(str(tmp_site), rule,
                                           read_seal(str(tmp_site), "w"))
        assert state == "stale" and "input_changed" in reason

    def test_output_tampered(self, tmp_site, write_seal):
        (tmp_site / "out.txt").write_text("original")
        write_seal(tmp_site, "w", outputs={"out.txt": "wrong_hash"})
        rule = {"name": "w", "outputs": ["out.txt"]}
        state, reason = compute_rule_state(str(tmp_site), rule,
                                           read_seal(str(tmp_site), "w"))
        assert state == "dirty" and "output_hash_changed" in reason


class TestComputeRuleStates:
    def test_all_fresh(self, tmp_site, write_manifest, write_seal):
        (tmp_site / "out.txt").write_text("data")
        h = file_hash(str(tmp_site / "out.txt"))
        write_manifest(tmp_site)
        write_seal(tmp_site, "w", outputs={"out.txt": h})
        states = compute_rule_states(str(tmp_site),
                                     read_manifest(str(tmp_site)))
        assert all(s["state"] == "fresh" for s in states)


class TestComputeArtifactStates:
    def test_fresh_artifact(self, tmp_site, write_manifest, write_seal):
        (tmp_site / "out.txt").write_text("data")
        h = file_hash(str(tmp_site / "out.txt"))
        write_manifest(tmp_site)
        write_seal(tmp_site, "w", outputs={"out.txt": h})
        arts = compute_artifact_states(str(tmp_site),
                                       read_manifest(str(tmp_site)))
        assert arts[0]["state"] == "fresh"
        assert arts[0]["sealed_hash"] == h

    def test_missing_artifact(self, tmp_site, write_manifest):
        write_manifest(tmp_site)
        arts = compute_artifact_states(str(tmp_site),
                                       read_manifest(str(tmp_site)))
        assert arts[0]["state"] == "missing"

    def test_modified_artifact(self, tmp_site, write_manifest, write_seal):
        (tmp_site / "out.txt").write_text("data")
        write_manifest(tmp_site)
        write_seal(tmp_site, "w", outputs={"out.txt": "old_hash"})
        arts = compute_artifact_states(str(tmp_site),
                                       read_manifest(str(tmp_site)))
        assert arts[0]["state"] == "modified"
