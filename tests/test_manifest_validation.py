"""
test_manifest_validation.py -- Beta Gate C2: Manifest schema validation.

Validates that manifest and seal files are strictly validated on read.
Unsupported or corrupt manifests/seals return None with clear errors
rather than silently degrading.

Tests cover:
- Manifest schema validation
- Seal version validation
- Missing required fields
- Invalid field types
- Unsupported versions
"""

import json
import tempfile
import shutil
from pathlib import Path


def test_valid_manifest_accepted():
    """Valid v1 manifest is accepted."""
    from husks.manifest import read_manifest

    tmpdir = tempfile.mkdtemp(prefix="c2-manifest-")
    try:
        site = Path(tmpdir) / "site"
        traces = site / ".traces"
        traces.mkdir(parents=True)

        manifest = {
            "schema": "husks.build.manifest.v1",
            "name": "test-build",
            "root": "abc123",
            "site": str(site),
            "run_id": "uuid-1234",
            "rules": [],
        }
        (traces / "build.manifest.json").write_text(json.dumps(manifest))

        result = read_manifest(str(site))
        assert result is not None, "valid manifest should be accepted"
        assert result["schema"] == "husks.build.manifest.v1"

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_manifest_missing_schema_rejected():
    """Manifest without schema field is rejected."""
    from husks.manifest import read_manifest

    tmpdir = tempfile.mkdtemp(prefix="c2-no-schema-")
    try:
        site = Path(tmpdir) / "site"
        traces = site / ".traces"
        traces.mkdir(parents=True)

        manifest = {
            "name": "test-build",
            "root": "abc123",
            "site": str(site),
            "run_id": "uuid-1234",
            "rules": [],
        }
        (traces / "build.manifest.json").write_text(json.dumps(manifest))

        result = read_manifest(str(site))
        assert result is None, "manifest without schema should be rejected"

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_manifest_unsupported_schema_rejected():
    """Manifest with unsupported schema is rejected."""
    from husks.manifest import read_manifest

    tmpdir = tempfile.mkdtemp(prefix="c2-bad-schema-")
    try:
        site = Path(tmpdir) / "site"
        traces = site / ".traces"
        traces.mkdir(parents=True)

        manifest = {
            "schema": "husks.build.manifest.v999",
            "name": "test-build",
            "root": "abc123",
            "site": str(site),
            "run_id": "uuid-1234",
            "rules": [],
        }
        (traces / "build.manifest.json").write_text(json.dumps(manifest))

        result = read_manifest(str(site))
        assert result is None, "manifest with unsupported schema should be rejected"

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_manifest_missing_required_field_rejected():
    """Manifest missing required field is rejected."""
    from husks.manifest import read_manifest

    tmpdir = tempfile.mkdtemp(prefix="c2-missing-field-")
    try:
        site = Path(tmpdir) / "site"
        traces = site / ".traces"
        traces.mkdir(parents=True)

        # Missing 'rules' field
        manifest = {
            "schema": "husks.build.manifest.v1",
            "name": "test-build",
            "root": "abc123",
            "site": str(site),
            "run_id": "uuid-1234",
        }
        (traces / "build.manifest.json").write_text(json.dumps(manifest))

        result = read_manifest(str(site))
        assert result is None, "manifest missing required field should be rejected"

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_manifest_rules_not_list_rejected():
    """Manifest with rules not a list is rejected."""
    from husks.manifest import read_manifest

    tmpdir = tempfile.mkdtemp(prefix="c2-bad-rules-")
    try:
        site = Path(tmpdir) / "site"
        traces = site / ".traces"
        traces.mkdir(parents=True)

        manifest = {
            "schema": "husks.build.manifest.v1",
            "name": "test-build",
            "root": "abc123",
            "site": str(site),
            "run_id": "uuid-1234",
            "rules": "not-a-list",
        }
        (traces / "build.manifest.json").write_text(json.dumps(manifest))

        result = read_manifest(str(site))
        assert result is None, "manifest with invalid rules type should be rejected"

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_manifest_corrupt_json_rejected():
    """Manifest with corrupt JSON is rejected."""
    from husks.manifest import read_manifest

    tmpdir = tempfile.mkdtemp(prefix="c2-corrupt-")
    try:
        site = Path(tmpdir) / "site"
        traces = site / ".traces"
        traces.mkdir(parents=True)

        # Write invalid JSON
        (traces / "build.manifest.json").write_text("{ invalid json }")

        result = read_manifest(str(site))
        assert result is None, "corrupt JSON manifest should be rejected"

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_valid_seal_accepted():
    """Valid v1 seal is accepted."""
    from husks.manifest import read_seal

    tmpdir = tempfile.mkdtemp(prefix="c2-seal-")
    try:
        site = Path(tmpdir) / "site"
        traces = site / ".traces"
        traces.mkdir(parents=True)

        seal = {
            "v": 1,
            "seal": "seal-data",
            "recipe_digest": "abc123",
            "inputs": {"input.txt": "hash1"},
            "outputs": {"output.txt": "hash2"},
        }
        (traces / "test.seal").write_text(json.dumps(seal))

        result = read_seal(str(site), "test")
        assert result is not None, "valid seal should be accepted"
        assert result["v"] == 1

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_seal_missing_version_rejected():
    """Seal without version field is rejected."""
    from husks.manifest import read_seal

    tmpdir = tempfile.mkdtemp(prefix="c2-no-version-")
    try:
        site = Path(tmpdir) / "site"
        traces = site / ".traces"
        traces.mkdir(parents=True)

        seal = {
            "seal": "seal-data",
            "recipe_digest": "abc123",
            "inputs": {},
        }
        (traces / "test.seal").write_text(json.dumps(seal))

        result = read_seal(str(site), "test")
        assert result is None, "seal without version should be rejected"

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_seal_unsupported_version_rejected():
    """Seal with unsupported version is rejected."""
    from husks.manifest import read_seal

    tmpdir = tempfile.mkdtemp(prefix="c2-bad-version-")
    try:
        site = Path(tmpdir) / "site"
        traces = site / ".traces"
        traces.mkdir(parents=True)

        seal = {
            "v": 999,
            "seal": "seal-data",
            "recipe_digest": "abc123",
            "inputs": {},
        }
        (traces / "test.seal").write_text(json.dumps(seal))

        result = read_seal(str(site), "test")
        assert result is None, "seal with unsupported version should be rejected"

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_seal_missing_required_field_rejected():
    """Seal missing required field is rejected."""
    from husks.manifest import read_seal

    tmpdir = tempfile.mkdtemp(prefix="c2-seal-missing-")
    try:
        site = Path(tmpdir) / "site"
        traces = site / ".traces"
        traces.mkdir(parents=True)

        # Missing 'recipe_digest'
        seal = {
            "v": 1,
            "seal": "seal-data",
            "inputs": {},
        }
        (traces / "test.seal").write_text(json.dumps(seal))

        result = read_seal(str(site), "test")
        assert result is None, "seal missing required field should be rejected"

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_seal_inputs_not_dict_rejected():
    """Seal with inputs not a dict is rejected."""
    from husks.manifest import read_seal

    tmpdir = tempfile.mkdtemp(prefix="c2-seal-bad-inputs-")
    try:
        site = Path(tmpdir) / "site"
        traces = site / ".traces"
        traces.mkdir(parents=True)

        seal = {
            "v": 1,
            "seal": "seal-data",
            "recipe_digest": "abc123",
            "inputs": "not-a-dict",
        }
        (traces / "test.seal").write_text(json.dumps(seal))

        result = read_seal(str(site), "test")
        assert result is None, "seal with invalid inputs type should be rejected"

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_seal_outputs_not_dict_rejected():
    """Seal with outputs not a dict is rejected."""
    from husks.manifest import read_seal

    tmpdir = tempfile.mkdtemp(prefix="c2-seal-bad-outputs-")
    try:
        site = Path(tmpdir) / "site"
        traces = site / ".traces"
        traces.mkdir(parents=True)

        seal = {
            "v": 1,
            "seal": "seal-data",
            "recipe_digest": "abc123",
            "inputs": {},
            "outputs": "not-a-dict",
        }
        (traces / "test.seal").write_text(json.dumps(seal))

        result = read_seal(str(site), "test")
        assert result is None, "seal with invalid outputs type should be rejected"

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_seal_without_outputs_accepted():
    """Seal without outputs field is valid (outputs optional)."""
    from husks.manifest import read_seal

    tmpdir = tempfile.mkdtemp(prefix="c2-seal-no-outputs-")
    try:
        site = Path(tmpdir) / "site"
        traces = site / ".traces"
        traces.mkdir(parents=True)

        seal = {
            "v": 1,
            "seal": "seal-data",
            "recipe_digest": "abc123",
            "inputs": {},
        }
        (traces / "test.seal").write_text(json.dumps(seal))

        result = read_seal(str(site), "test")
        assert result is not None, "seal without outputs should be accepted"

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_seal_version_non_integer_rejected():
    """Seal with non-integer version is rejected."""
    from husks.manifest import read_seal

    tmpdir = tempfile.mkdtemp(prefix="c2-seal-version-str-")
    try:
        site = Path(tmpdir) / "site"
        traces = site / ".traces"
        traces.mkdir(parents=True)

        seal = {
            "v": "1",  # String instead of int
            "seal": "seal-data",
            "recipe_digest": "abc123",
            "inputs": {},
        }
        (traces / "test.seal").write_text(json.dumps(seal))

        result = read_seal(str(site), "test")
        assert result is None, "seal with non-integer version should be rejected"

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)
