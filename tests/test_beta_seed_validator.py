"""
test_beta_seed_validator.py -- Task 5/Gate E: Strengthened beta_seed validator.

Tests that the beta_seed validator properly enforces structured output format
and rejects malformed responses.
"""

import tempfile
import shutil
from pathlib import Path
import sys
import os

# Add examples/beta_seed to path to import validate
sys.path.insert(0, str(Path(__file__).parent.parent / "examples" / "beta_seed"))
from validate import validate_response

import pytest


@pytest.mark.beta


@pytest.mark.gate_a


@pytest.mark.gate_c


@pytest.mark.gate_e


def test_validator_accepts_correct_live_answer():
    """Validator accepts correctly formatted live answer."""
    valid, message = validate_response("ANSWER: Paris")
    assert valid is True, f"Should accept correct answer: {message}"
    assert message == "PASS"


@pytest.mark.beta


@pytest.mark.gate_a


@pytest.mark.gate_c


@pytest.mark.gate_e


def test_validator_accepts_case_insensitive():
    """Validator accepts case variations of correct answer."""
    valid, message = validate_response("ANSWER: paris")
    assert valid is True, f"Should accept lowercase: {message}"

    valid, message = validate_response("answer: PARIS")
    assert valid is True, f"Should accept case variations: {message}"


@pytest.mark.beta


@pytest.mark.gate_a


@pytest.mark.gate_c


@pytest.mark.gate_e


def test_validator_accepts_stub_output():
    """Validator accepts stub oracle placeholder."""
    valid, message = validate_response("ANSWER: Stub oracle output")
    assert valid is True, f"Should accept stub output: {message}"

    valid, message = validate_response("ANSWER: Oracle output placeholder")
    assert valid is True, f"Should accept placeholder: {message}"


@pytest.mark.beta


@pytest.mark.gate_a


@pytest.mark.gate_c


@pytest.mark.gate_e


def test_validator_rejects_missing_answer_prefix():
    """Validator rejects response without ANSWER: prefix (Task 5)."""
    valid, message = validate_response("Paris")
    assert valid is False, "Should reject answer without prefix"
    assert "FAIL" in message
    assert "Expected 'ANSWER:" in message


@pytest.mark.beta


@pytest.mark.gate_a


@pytest.mark.gate_c


@pytest.mark.gate_e


def test_validator_rejects_malformed_format():
    """Validator rejects various malformed formats."""
    # Just the word "Paris" without structure
    valid, message = validate_response("The capital of France is Paris.")
    assert valid is False, "Should reject prose without structure"
    assert "FAIL" in message

    # Empty response
    valid, message = validate_response("")
    assert valid is False, "Should reject empty response"
    assert "Empty response" in message

    # Wrong answer with correct format
    valid, message = validate_response("ANSWER: London")
    assert valid is False, "Should reject wrong answer"
    assert "Invalid answer" in message


@pytest.mark.beta


@pytest.mark.gate_a


@pytest.mark.gate_c


@pytest.mark.gate_e


def test_validator_accepts_whitespace_variations():
    """Validator handles whitespace variations gracefully."""
    valid, message = validate_response("ANSWER:   Paris   ")
    assert valid is True, f"Should handle extra whitespace: {message}"

    valid, message = validate_response("  ANSWER: Paris  ")
    assert valid is True, f"Should handle leading/trailing whitespace: {message}"


@pytest.mark.beta


@pytest.mark.gate_a


@pytest.mark.gate_c


@pytest.mark.gate_e


def test_validator_rejects_incorrect_answer():
    """Validator rejects incorrect answer even with correct format."""
    valid, message = validate_response("ANSWER: Berlin")
    assert valid is False, "Should reject Berlin (wrong answer)"
    assert "Invalid answer" in message
    assert "Berlin" in message


@pytest.mark.beta


@pytest.mark.gate_a


@pytest.mark.gate_c


@pytest.mark.gate_e


def test_validator_with_multiline_response():
    """Validator handles multiline responses correctly."""
    # Valid multiline (answer on first line)
    valid, message = validate_response("ANSWER: Paris\nSome extra text")
    assert valid is True, f"Should accept multiline with valid answer: {message}"

    # Invalid multiline (answer not on first line)
    valid, message = validate_response("Some preamble\nANSWER: Paris")
    assert valid is False, "Should reject answer not at start"
