"""Configuration file loading for .husks.toml."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any


def load_config(start: Path | None = None) -> dict[str, Any]:
    """Walk from *start* (default cwd) upward looking for .husks.toml.

    Returns the parsed dict, or {} if no file is found.
    """
    cur = Path(start or Path.cwd()).resolve()
    while True:
        candidate = cur / ".husks.toml"
        if candidate.is_file():
            return _parse_toml(candidate)
        parent = cur.parent
        if parent == cur:
            break
        cur = parent
    return {}


def _parse_toml(path: Path) -> dict[str, Any]:
    """Parse a TOML file, using tomllib (3.11+) or tomli as fallback."""
    if sys.version_info >= (3, 11):
        import tomllib
    else:
        try:
            import tomli as tomllib  # type: ignore[no-redef]
        except ModuleNotFoundError:
            raise ModuleNotFoundError(
                "tomli is required for .husks.toml on Python < 3.11. "
                "Install it with: pip install tomli"
            ) from None
    with open(path, "rb") as f:
        return tomllib.load(f)


# ── Environment variable expansion ───────────────────────────────

def _expand_env_vars(value: Any) -> Any:
    """Recursively walk dicts/lists replacing ``$VAR`` strings from os.environ.

    Only strings whose first character is ``$`` are treated as env references.
    Missing variables resolve to the empty string.
    """
    if isinstance(value, str):
        if value.startswith("$"):
            return os.environ.get(value[1:], "")
        return value
    if isinstance(value, dict):
        return {k: _expand_env_vars(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_expand_env_vars(item) for item in value]
    return value


# ── Config validation ────────────────────────────────────────────

KNOWN_ORACLE_KEYS: dict[str, type | tuple[type, ...]] = {
    "model": str,
    "api_key": str,
    "api_base": str,
    "timeout": (int, float),
    "max_retries": int,
    "temperature": (int, float),
    "max_tokens": int,
    "params": dict,
    "rules": dict,
    "backend": str,
}


def validate_oracle_config(oracle: dict[str, Any]) -> list[str]:
    """Check for unknown keys and type mismatches.

    Returns a list of warning strings (empty if config is clean).
    Warnings only — never raises.
    """
    warnings: list[str] = []
    for key, value in oracle.items():
        if key not in KNOWN_ORACLE_KEYS:
            warnings.append(f"unknown key '{key}' in [oracle]")
            continue
        expected = KNOWN_ORACLE_KEYS[key]
        if not isinstance(value, expected):
            warnings.append(
                f"[oracle] key '{key}': expected {expected.__name__ if isinstance(expected, type) else expected}, "
                f"got {type(value).__name__}"
            )
    # Range check for temperature
    temp = oracle.get("temperature")
    if isinstance(temp, (int, float)) and not (0.0 <= temp <= 2.0):
        warnings.append(f"[oracle] temperature={temp} is outside the typical 0.0–2.0 range")
    return warnings


def oracle_config_from_toml(cfg: dict[str, Any]) -> dict[str, Any]:
    """Extract and normalize the [oracle] section for LiteLLMBackend.

    Returns ``{"model": ..., "params": {...}, "per_rule": {...}}`` or ``{}``.
    """
    oracle = cfg.get("oracle")
    if not oracle or not isinstance(oracle, dict):
        return {}

    oracle = dict(oracle)  # shallow copy

    # Expand $ENV_VAR references throughout the entire oracle dict
    oracle = _expand_env_vars(oracle)

    # Validate and emit warnings to stderr
    warnings = validate_oracle_config(oracle)
    for w in warnings:
        print(f"husks: warning: {w}", file=sys.stderr)

    result: dict[str, Any] = {}

    # model stays at top level
    if "model" in oracle:
        result["model"] = oracle.pop("model")

    # per_rule from rules
    rules = oracle.pop("rules", None)
    if rules and isinstance(rules, dict):
        result["per_rule"] = dict(rules)

    # Extra [oracle.params] merged with direct litellm kwargs
    extra_params = oracle.pop("params", None) or {}
    params: dict[str, Any] = {}
    for key in ("api_base", "api_key", "timeout", "max_retries",
                "temperature", "max_tokens"):
        if key in oracle:
            params[key] = oracle.pop(key)
    params.update(extra_params)
    if params:
        result["params"] = params

    return result
