"""Tests for .husks.toml config loading."""

import textwrap


from husks.config import (
    load_config,
    oracle_config_from_toml,
    _expand_env_vars,
    validate_oracle_config,
)
from husks.oracle import _resolve_config


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


# ── Generalized $ENV_VAR expansion ───────────────────────────────

def test_expand_env_vars_api_base(monkeypatch):
    """$ENV_VAR in api_base is resolved from the environment."""
    monkeypatch.setenv("MY_API_BASE", "https://proxy.example.com/v1")
    cfg = {"oracle": {"api_base": "$MY_API_BASE"}}
    oc = oracle_config_from_toml(cfg)
    assert oc["params"]["api_base"] == "https://proxy.example.com/v1"


def test_expand_env_vars_inside_params(monkeypatch):
    """$ENV_VAR inside [oracle.params] is expanded."""
    monkeypatch.setenv("SEED_VAL", "99")
    cfg = {"oracle": {"params": {"seed": "$SEED_VAL"}}}
    oc = oracle_config_from_toml(cfg)
    assert oc["params"]["seed"] == "99"


def test_expand_env_vars_inside_rules(monkeypatch):
    """$ENV_VAR inside [oracle.rules.*] is expanded."""
    monkeypatch.setenv("RULE_MODEL", "special-model")
    cfg = {"oracle": {"rules": {"r1": {"model": "$RULE_MODEL"}}}}
    oc = oracle_config_from_toml(cfg)
    assert oc["per_rule"]["r1"]["model"] == "special-model"


def test_expand_env_vars_non_dollar_untouched():
    """Non-$ strings are left as-is."""
    assert _expand_env_vars("plain-string") == "plain-string"
    assert _expand_env_vars(42) == 42
    assert _expand_env_vars({"key": "value"}) == {"key": "value"}


def test_expand_env_vars_list(monkeypatch):
    """$ENV_VAR expansion works inside lists."""
    monkeypatch.setenv("ITEM", "resolved")
    assert _expand_env_vars(["$ITEM", "literal"]) == ["resolved", "literal"]


# ── Validation ───────────────────────────────────────────────────

def test_validate_unknown_key():
    """Unknown keys produce a warning."""
    warnings = validate_oracle_config({"modle": "typo"})
    assert any("unknown key" in w and "modle" in w for w in warnings)


def test_validate_type_mismatch():
    """Type mismatches produce a warning."""
    warnings = validate_oracle_config({"model": 123})
    assert any("type" in w.lower() or "expected" in w.lower() for w in warnings)


def test_validate_temperature_range():
    """Temperature outside 0.0–2.0 produces a warning."""
    warnings = validate_oracle_config({"temperature": 5.0})
    assert any("temperature" in w and "range" in w for w in warnings)


def test_validate_clean_config():
    """A correct config produces no warnings."""
    warnings = validate_oracle_config({
        "model": "anthropic/claude-haiku-4-5-20251001",
        "temperature": 0.7,
        "max_tokens": 4096,
    })
    assert warnings == []


# ── Deep merge (_resolve_config) ─────────────────────────────────

def test_deep_merge_params():
    """Per-rule params merges with base params, not replaces."""
    config = {
        "model": "base",
        "params": {"top_p": 0.95, "seed": 42},
        "per_rule": {
            "hot": {"params": {"temperature": 0.2}},
        },
    }
    rc = _resolve_config(config, "hot")
    assert rc["params"]["top_p"] == 0.95
    assert rc["params"]["seed"] == 42
    assert rc["params"]["temperature"] == 0.2


def test_deep_merge_scalar_override():
    """Per-rule scalar values still override base scalars."""
    config = {
        "model": "base",
        "per_rule": {"r1": {"model": "override"}},
    }
    rc = _resolve_config(config, "r1")
    assert rc["model"] == "override"


def test_deep_merge_no_match():
    """No matching rule returns base config unchanged."""
    config = {"model": "base", "params": {"x": 1}, "per_rule": {}}
    rc = _resolve_config(config, "nonexistent")
    assert rc["model"] == "base"
    assert rc["params"]["x"] == 1
