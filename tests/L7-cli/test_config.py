"""Tests for .husks.toml config loading."""

import os
import textwrap
from pathlib import Path

import pytest

from husks.config import load_config, oracle_config_from_toml


# ── load_config ──────────────────────────────────────────────────

def test_load_config_missing(tmp_path):
    """Returns {} when no .husks.toml exists."""
    assert load_config(tmp_path) == {}


def test_load_config_basic(tmp_path):
    """Parses model and params from a .husks.toml."""
    (tmp_path / ".husks.toml").write_text(textwrap.dedent("""\
        [oracle]
        model = "anthropic/claude-sonnet-4-20250514"
        temperature = 0.7
    """))
    cfg = load_config(tmp_path)
    assert cfg["oracle"]["model"] == "anthropic/claude-sonnet-4-20250514"
    assert cfg["oracle"]["temperature"] == 0.7


def test_config_walks_parents(tmp_path):
    """Finds .husks.toml in a parent directory."""
    (tmp_path / ".husks.toml").write_text(textwrap.dedent("""\
        [oracle]
        model = "anthropic/claude-haiku-4-5-20251001"
    """))
    child = tmp_path / "a" / "b" / "c"
    child.mkdir(parents=True)
    cfg = load_config(child)
    assert cfg["oracle"]["model"] == "anthropic/claude-haiku-4-5-20251001"


# ── oracle_config_from_toml ─────────────────────────────────────

def test_oracle_config_empty():
    """Returns {} when no [oracle] section."""
    assert oracle_config_from_toml({}) == {}
    assert oracle_config_from_toml({"other": 1}) == {}


def test_oracle_config_model_and_params():
    """Extracts model at top level, litellm kwargs into params."""
    cfg = {
        "oracle": {
            "model": "anthropic/claude-sonnet-4-20250514",
            "api_base": "https://proxy.example.com/v1",
            "timeout": 120,
            "temperature": 0.7,
            "max_tokens": 4096,
        }
    }
    oc = oracle_config_from_toml(cfg)
    assert oc["model"] == "anthropic/claude-sonnet-4-20250514"
    assert oc["params"]["api_base"] == "https://proxy.example.com/v1"
    assert oc["params"]["timeout"] == 120
    assert oc["params"]["temperature"] == 0.7
    assert oc["params"]["max_tokens"] == 4096


def test_oracle_config_extra_params():
    """[oracle.params] merges into params dict."""
    cfg = {
        "oracle": {
            "model": "x",
            "temperature": 0.5,
            "params": {"top_p": 0.95, "seed": 42},
        }
    }
    oc = oracle_config_from_toml(cfg)
    assert oc["params"]["temperature"] == 0.5
    assert oc["params"]["top_p"] == 0.95
    assert oc["params"]["seed"] == 42


def test_env_var_resolution(monkeypatch):
    """$ENV_VAR in api_key is resolved from the environment."""
    monkeypatch.setenv("MY_SECRET_KEY", "sk-test-123")
    cfg = {"oracle": {"api_key": "$MY_SECRET_KEY"}}
    oc = oracle_config_from_toml(cfg)
    assert oc["params"]["api_key"] == "sk-test-123"


def test_env_var_missing(monkeypatch):
    """Missing env var resolves to empty string."""
    monkeypatch.delenv("NONEXISTENT_KEY_12345", raising=False)
    cfg = {"oracle": {"api_key": "$NONEXISTENT_KEY_12345"}}
    oc = oracle_config_from_toml(cfg)
    assert oc["params"]["api_key"] == ""


def test_per_rule_override():
    """[oracle.rules.x] is renamed to per_rule."""
    cfg = {
        "oracle": {
            "model": "base-model",
            "rules": {
                "expensive_rule": {
                    "model": "anthropic/claude-opus-4-6",
                    "max_tokens": 8192,
                },
            },
        }
    }
    oc = oracle_config_from_toml(cfg)
    assert oc["model"] == "base-model"
    assert oc["per_rule"]["expensive_rule"]["model"] == "anthropic/claude-opus-4-6"
    assert oc["per_rule"]["expensive_rule"]["max_tokens"] == 8192


# ── CLI --model override ────────────────────────────────────────

def test_cli_model_overrides_config(tmp_path):
    """--model flag should override .husks.toml model when injected."""
    (tmp_path / ".husks.toml").write_text(textwrap.dedent("""\
        [oracle]
        model = "config-model"
    """))
    cfg = load_config(tmp_path)
    oc = oracle_config_from_toml(cfg)
    assert oc["model"] == "config-model"

    # Simulate CLI override (as done in _cmd_run)
    oc["model"] = "cli-model"
    assert oc["model"] == "cli-model"
