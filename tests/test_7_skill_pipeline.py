"""
test_7_skill_pipeline.py -- Skill output verifies against the frozen reader.

Gate: the skill's workflow (flat design -> elaborate -> encode -> .husk)
produces artifacts that the frozen reader can parse and verify.

This tests the programmatic pathway the skill relies on, not the
skill prompt itself. The skill is volatile; the pathway is permanent.
"""

import os
import tempfile

import pytest

from conftest import DEMO_SITE, load_demo
from husks.core import encode, parse, recompute_root, verify
from husks.designs.transport import elaborate, ast_to_json

SKILL_PATH = os.path.join(os.path.dirname(__file__), "..",
                          "skills", "husks", "SKILL.md")


# -- Gate: skill workflow produces verifiable .husk ----------------------------

class TestSkillWorkflowVerifies:
    """The skill's design -> elaborate -> encode -> verify pathway works."""

    def test_elaborate_encode_parse_roundtrip(self):
        """A skill-authored flat design elaborates to parseable CSE."""
        design = {
            "name": "skill-test",
            "fuel": 5,
            "target": "write-greeting",
            "rules": [
                {
                    "name": "write-greeting",
                    "kind": "oracle",
                    "inputs": [],
                    "outputs": ["greeting.txt"],
                    "prompt": "Write a greeting to greeting.txt.",
                    "tools": ["write-file"],
                    "fuel": 3,
                },
            ],
        }
        tree = elaborate(design)
        husk_bytes = encode(tree)
        # The frozen reader can parse the skill's output
        parsed = parse(husk_bytes)
        assert parsed == tree

    def test_elaborate_produces_valid_husk_structure(self):
        """Elaborated design has the correct CSE form structure."""
        design = {
            "name": "my-build",
            "fuel": 10,
            "target": "done",
            "rules": [
                {
                    "name": "generate",
                    "kind": "oracle",
                    "inputs": [],
                    "outputs": ["result.txt"],
                    "prompt": "Generate a result.",
                    "tools": ["read-file", "write-file"],
                    "fuel": 5,
                },
                {
                    "name": "done",
                    "kind": "action",
                    "inputs": ["result.txt"],
                    "outputs": [".complete"],
                },
            ],
        }
        tree = elaborate(design)
        j = ast_to_json(tree)

        # Top-level husk form
        assert j["form"] == "husk"
        assert j["version"] == "1"

        # Build
        assert j["build"]["form"] == "build"
        assert j["build"]["name"] == "my-build"
        assert j["build"]["fuel"] == "10"

        # Target rule
        target = j["build"]["targets"][0]
        assert target["form"] == "rule"
        assert target["name"] == "done"
        assert target["recipe"] == {"form": "action"}
        assert target["inputs"] == ["result.txt"]
        assert target["outputs"] == [".complete"]

        # Child rule (generate)
        assert len(target["children"]) == 1
        gen = target["children"][0]
        assert gen["name"] == "generate"
        assert gen["recipe"]["form"] == "oracle"
        assert gen["recipe"]["prompt"] == "Generate a result."

    def test_golden_vector_verifies(self):
        """The demo.husk verifies against the frozen reader -- the
        fundamental gate that proves permanence."""
        husk_bytes, expected_root = load_demo()
        assert verify(husk_bytes, DEMO_SITE, expected_root)

    def test_elaborate_demo_design_verifies(self):
        """A flat design matching demo.husk elaborates to bytes that
        verify against the frozen reader."""
        _, expected_root = load_demo()
        design = {
            "name": "demo",
            "fuel": 10,
            "target": "combine",
            "site_inputs": ["config.txt", "greeting.txt"],
            "rules": [
                {
                    "name": "greet",
                    "kind": "action",
                    "inputs": ["config.txt", "greeting.txt"],
                    "outputs": ["hello.txt"],
                },
                {
                    "name": "combine",
                    "kind": "oracle",
                    "inputs": ["hello.txt"],
                    "outputs": ["result.txt"],
                    "prompt": "Combine the files.",
                    "tools": ["read-file", "write-file"],
                    "fuel": 3,
                },
            ],
        }
        husk_bytes = encode(elaborate(design))
        assert verify(husk_bytes, DEMO_SITE, expected_root)

    def test_husk_file_written_to_disk_verifies(self):
        """Writing .husk bytes to disk and reading them back
        reproduces the same root -- the file is self-contained."""
        husk_bytes, expected_root = load_demo()

        with tempfile.NamedTemporaryFile(suffix=".husk", delete=False) as f:
            f.write(husk_bytes)
            tmp_path = f.name

        try:
            with open(tmp_path, "rb") as f:
                loaded = f.read()
            assert loaded == husk_bytes
            root = recompute_root(loaded, DEMO_SITE)
            assert root == expected_root
        finally:
            os.unlink(tmp_path)


# -- Two-form vocabulary -------------------------------------------------------

class TestTwoFormVocabulary:
    """action and oracle are sufficient for any decomposition."""

    def test_action_only_design(self):
        """A design with only action rules elaborates correctly."""
        design = {
            "name": "actions-only",
            "fuel": 1,
            "target": "copy",
            "site_inputs": ["input.txt"],
            "rules": [
                {
                    "name": "copy",
                    "kind": "action",
                    "inputs": ["input.txt"],
                    "outputs": ["output.txt"],
                },
            ],
        }
        tree = elaborate(design)
        j = ast_to_json(tree)
        assert j["build"]["targets"][0]["recipe"] == {"form": "action"}
        # Parseable by reader
        assert parse(encode(tree)) == tree

    def test_oracle_only_design(self):
        """A design with only oracle rules elaborates correctly."""
        design = {
            "name": "oracle-only",
            "fuel": 8,
            "target": "generate",
            "rules": [
                {
                    "name": "generate",
                    "kind": "oracle",
                    "inputs": [],
                    "outputs": ["out.txt"],
                    "prompt": "Generate content.",
                    "tools": ["write-file"],
                    "fuel": 5,
                },
            ],
        }
        tree = elaborate(design)
        j = ast_to_json(tree)
        recipe = j["build"]["targets"][0]["recipe"]
        assert recipe["form"] == "oracle"
        assert recipe["prompt"] == "Generate content."
        assert parse(encode(tree)) == tree

    def test_mixed_action_oracle_design(self):
        """The common pattern: oracle produces, action verifies."""
        design = {
            "name": "produce-and-verify",
            "fuel": 10,
            "target": "validate",
            "rules": [
                {
                    "name": "write-code",
                    "kind": "oracle",
                    "inputs": [],
                    "outputs": ["code.py"],
                    "prompt": "Write a Python function.",
                    "tools": ["write-file"],
                    "fuel": 5,
                },
                {
                    "name": "validate",
                    "kind": "action",
                    "inputs": ["code.py"],
                    "outputs": ["test-results.txt"],
                },
            ],
        }
        tree = elaborate(design)
        j = ast_to_json(tree)

        # Target is action (validates)
        assert j["build"]["targets"][0]["recipe"] == {"form": "action"}
        # Child is oracle (produces)
        assert j["build"]["targets"][0]["children"][0]["recipe"]["form"] == "oracle"
        assert parse(encode(tree)) == tree


# -- Convergence properties ----------------------------------------------------

class TestConvergenceProperties:
    """Sealed rules produce stable hashes; recipe changes alter the root."""

    def test_same_design_same_root(self):
        """Elaborating the same design twice produces identical bytes."""
        design = {
            "name": "stable",
            "fuel": 5,
            "target": "r",
            "rules": [
                {
                    "name": "r",
                    "kind": "oracle",
                    "inputs": [],
                    "outputs": ["out.txt"],
                    "prompt": "Do it.",
                    "tools": ["write-file"],
                    "fuel": 3,
                },
            ],
        }
        a = encode(elaborate(design))
        b = encode(elaborate(design))
        assert a == b

    def test_prompt_change_changes_bytes(self):
        """Changing the oracle prompt changes the CSE bytes (and thus
        the recipe-digest and seal). This is the convergence signal:
        a prompt edit re-fires the rule."""
        design_a = {
            "name": "b",
            "fuel": 5,
            "target": "r",
            "rules": [
                {
                    "name": "r",
                    "kind": "oracle",
                    "inputs": [],
                    "outputs": ["out.txt"],
                    "prompt": "Write version 1.",
                    "tools": ["write-file"],
                    "fuel": 3,
                },
            ],
        }
        design_b = dict(design_a)
        design_b["rules"] = [dict(design_a["rules"][0])]
        design_b["rules"][0]["prompt"] = "Write version 2."

        a = encode(elaborate(design_a))
        b = encode(elaborate(design_b))
        assert a != b

    def test_fuel_change_changes_bytes(self):
        """Changing oracle fuel changes the recipe and thus the seal."""
        design_a = {
            "name": "b",
            "fuel": 10,
            "target": "r",
            "rules": [
                {
                    "name": "r",
                    "kind": "oracle",
                    "inputs": [],
                    "outputs": ["out.txt"],
                    "prompt": "Do.",
                    "tools": ["write-file"],
                    "fuel": 3,
                },
            ],
        }
        design_b = {
            "name": "b",
            "fuel": 10,
            "target": "r",
            "rules": [
                {
                    "name": "r",
                    "kind": "oracle",
                    "inputs": [],
                    "outputs": ["out.txt"],
                    "prompt": "Do.",
                    "tools": ["write-file"],
                    "fuel": 5,
                },
            ],
        }
        a = encode(elaborate(design_a))
        b = encode(elaborate(design_b))
        assert a != b


# -- Skill document conformance ------------------------------------------------

class TestSkillDocument:
    """The SKILL.md document meets Phase 5 requirements."""

    def setup_method(self):
        with open(SKILL_PATH, "r") as f:
            self.skill = f.read()

    def test_mentions_two_forms(self):
        assert "action" in self.skill
        assert "oracle" in self.skill
        assert "Two Forms" in self.skill

    def test_mentions_verification(self):
        assert "verify" in self.skill.lower() or "recompute_root" in self.skill

    def test_mentions_convergence(self):
        assert "Convergence" in self.skill or "convergence" in self.skill
        assert "sealed" in self.skill.lower()

    def test_mentions_cse_permanence(self):
        assert "CSE" in self.skill or "canonical s-expression" in self.skill.lower()
        assert "permanent" in self.skill.lower() or "outlives" in self.skill.lower()

    def test_mentions_elaborate(self):
        assert "elaborate" in self.skill.lower()

    def test_workflow_includes_verify_step(self):
        """The workflow must include a verification step after build."""
        assert "recompute_root" in self.skill
