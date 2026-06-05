"""Security validation tests -- path/name injection prevention."""

import pytest
from kernel import _validate_rule_name, _validate_husk_path


class TestValidateRuleName:
    def test_valid_names(self):
        for name in ["combine", "greet", "my-rule", "rule_1", "CamelCase"]:
            _validate_rule_name(name)  # should not raise

    def test_empty_name(self):
        with pytest.raises(ValueError, match="empty rule name"):
            _validate_rule_name("")

    def test_slash_rejected(self):
        with pytest.raises(ValueError, match="path separator"):
            _validate_rule_name("foo/bar")

    def test_backslash_rejected(self):
        with pytest.raises(ValueError, match="path separator"):
            _validate_rule_name("foo\\bar")

    def test_dotdot_rejected(self):
        with pytest.raises(ValueError, match="\\.\\."):
            _validate_rule_name("..")

    def test_dotdot_prefix_rejected(self):
        with pytest.raises(ValueError, match="\\.\\."):
            _validate_rule_name("..sneaky")

    def test_control_char_null(self):
        with pytest.raises(ValueError, match="control character"):
            _validate_rule_name("foo\x00bar")

    def test_control_char_newline(self):
        with pytest.raises(ValueError, match="control character"):
            _validate_rule_name("foo\nbar")

    def test_control_char_tab(self):
        with pytest.raises(ValueError, match="control character"):
            _validate_rule_name("foo\tbar")

    def test_control_char_del(self):
        with pytest.raises(ValueError, match="control character"):
            _validate_rule_name("foo\x7fbar")

    def test_reserved_name_build_manifest(self):
        with pytest.raises(ValueError, match="internal file"):
            _validate_rule_name("build.manifest")

    def test_reserved_extension_seal(self):
        with pytest.raises(ValueError, match="reserved extension"):
            _validate_rule_name("foo.seal")

    def test_reserved_extension_trial(self):
        with pytest.raises(ValueError, match="reserved extension"):
            _validate_rule_name("foo.trial")

    def test_reserved_extension_history(self):
        with pytest.raises(ValueError, match="reserved extension"):
            _validate_rule_name("foo.history")


class TestValidateHuskPath:
    def test_valid_paths(self):
        for path in ["hello.txt", "src/main.py", "a:b().txt", "in put.txt"]:
            _validate_husk_path(path)  # should not raise

    def test_empty_path(self):
        with pytest.raises(ValueError, match="empty path"):
            _validate_husk_path("")

    def test_absolute_unix(self):
        with pytest.raises(ValueError, match="absolute path"):
            _validate_husk_path("/etc/passwd")

    def test_traversal_simple(self):
        with pytest.raises(ValueError, match="path traversal"):
            _validate_husk_path("../secret")

    def test_traversal_nested(self):
        with pytest.raises(ValueError, match="path traversal"):
            _validate_husk_path("foo/../../secret")

    def test_reserved_traces(self):
        with pytest.raises(ValueError, match="reserved path"):
            _validate_husk_path(".traces/foo.seal")

    def test_reserved_husks(self):
        with pytest.raises(ValueError, match="reserved path"):
            _validate_husk_path(".husks/bar")

    def test_husk_extension_rejected(self):
        with pytest.raises(ValueError, match="\\.husk file"):
            _validate_husk_path("evil.husk")

    def test_husk_extension_nested_rejected(self):
        with pytest.raises(ValueError, match="\\.husk file"):
            _validate_husk_path("dir/evil.husk")
