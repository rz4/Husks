"""
Phase 5 gate tests — Skill output verifies against the frozen reader.

Gate: the skill's workflow (flat plan → elaborate → encode → .husk)
produces artifacts that the frozen reader can parse and verify.

This tests the programmatic pathway the skill relies on, not the
skill prompt itself. The skill is volatile; the pathway is permanent.
"""

import os
import sys
import tempfile

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from husks.core import encode, parse, recompute_root, verify
from husks.transport import elaborate, ast_to_json

SPEC_DIR = os.path.join(os.path.dirname(__file__), "..", "spec", "conformance")
DEMO_HUSK = os.path.join(SPEC_DIR, "demo.husk")
DEMO_ROOT = os.path.join(SPEC_DIR, "demo.root")
DEMO_SITE = os.path.join(SPEC_DIR, "demo.site")
SKILL_PATH = os.path.join(os.path.dirname(__file__), "..",
                          "skills", "husks", "SKILL.md")


def _load_demo():
    with open(DEMO_HUSK, "rb") as f:
        husk_bytes = f.read()
    with open(DEMO_ROOT, "r") as f:
        root = f.read().strip()
    return husk_bytes, root


# ── Gate: skill workflow produces verifiable .husk ────────────────

class TestSkillWorkflowVerifies:
    """The skill's plan → elaborate → encode → verify pathway works."""

    def test_elaborate_encode_parse_roundtrip(self):
        """A skill-authored flat plan elaborates to parseable CSE."""
        plan = {
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
        tree = elaborate(plan)
        husk_bytes = encode(tree)
        # The frozen reader can parse the skill's output
        parsed = parse(husk_bytes)
        assert parsed == tree

    def test_elaborate_produces_valid_husk_structure(self):
        """Elaborated plan has the correct CSE form structure."""
        plan = {
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
        tree = elaborate(plan)
        j = ast_to_json(tree)

        # Top-level husk form
        assert j["form"] == "husk"
        assert j["version"] == "1"

        # Build
        assert j["build"]["form"] == "build"
        assert j["build"]["name"] == "my-build"
        assert j["build"]["fuel"] == "10"

        # Target rule
        target = j["build"]["target"]
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
        """The demo.husk verifies against the frozen reader — the
        fundamental gate that proves permanence."""
        husk_bytes, expected_root = _load_demo()
        assert verify(husk_bytes, DEMO_SITE, expected_root)

    def test_elaborate_demo_plan_verifies(self):
        """A flat plan matching demo.husk elaborates to bytes that
        verify against the frozen reader."""
        _, expected_root = _load_demo()
        plan = {
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
        husk_bytes = encode(elaborate(plan))
        assert verify(husk_bytes, DEMO_SITE, expected_root)

    def test_husk_file_written_to_disk_verifies(self):
        """Writing .husk bytes to disk and reading them back
        reproduces the same root — the file is self-contained."""
        husk_bytes, expected_root = _load_demo()

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


# ── Two-form vocabulary ──────────────────────────────────────────

class TestTwoFormVocabulary:
    """action and oracle are sufficient for any decomposition."""

    def test_action_only_plan(self):
        """A plan with only action rules elaborates correctly."""
        plan = {
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
        tree = elaborate(plan)
        j = ast_to_json(tree)
        assert j["build"]["target"]["recipe"] == {"form": "action"}
        # Parseable by reader
        assert parse(encode(tree)) == tree

    def test_oracle_only_plan(self):
        """A plan with only oracle rules elaborates correctly."""
        plan = {
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
        tree = elaborate(plan)
        j = ast_to_json(tree)
        recipe = j["build"]["target"]["recipe"]
        assert recipe["form"] == "oracle"
        assert recipe["prompt"] == "Generate content."
        assert parse(encode(tree)) == tree

    def test_mixed_action_oracle_plan(self):
        """The common pattern: oracle produces, action verifies."""
        plan = {
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
        tree = elaborate(plan)
        j = ast_to_json(tree)

        # Target is action (validates)
        assert j["build"]["target"]["recipe"] == {"form": "action"}
        # Child is oracle (produces)
        assert j["build"]["target"]["children"][0]["recipe"]["form"] == "oracle"
        assert parse(encode(tree)) == tree


# ── Convergence properties ───────────────────────────────────────

class TestConvergenceProperties:
    """Sealed rules produce stable hashes; recipe changes alter the root."""

    def test_same_plan_same_root(self):
        """Elaborating the same plan twice produces identical bytes."""
        plan = {
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
        a = encode(elaborate(plan))
        b = encode(elaborate(plan))
        assert a == b

    def test_prompt_change_changes_bytes(self):
        """Changing the oracle prompt changes the CSE bytes (and thus
        the recipe-digest and seal). This is the convergence signal:
        a prompt edit re-fires the rule."""
        plan_a = {
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
        plan_b = dict(plan_a)
        plan_b["rules"] = [dict(plan_a["rules"][0])]
        plan_b["rules"][0]["prompt"] = "Write version 2."

        a = encode(elaborate(plan_a))
        b = encode(elaborate(plan_b))
        assert a != b

    def test_fuel_change_changes_bytes(self):
        """Changing oracle fuel changes the recipe and thus the seal."""
        plan_a = {
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
        plan_b = {
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
        a = encode(elaborate(plan_a))
        b = encode(elaborate(plan_b))
        assert a != b


# ── Skill document conformance ───────────────────────────────────

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
