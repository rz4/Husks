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


def oracle_config_from_toml(cfg: dict[str, Any]) -> dict[str, Any]:
    """Extract and normalize the [oracle] section for LiteLLMBackend.

    Returns ``{"model": ..., "params": {...}, "per_rule": {...}}`` or ``{}``.
    """
    oracle = cfg.get("oracle")
    if not oracle or not isinstance(oracle, dict):
        return {}

    oracle = dict(oracle)  # shallow copy

    # Resolve $ENV_VAR in api_key
    api_key = oracle.get("api_key")
    if isinstance(api_key, str) and api_key.startswith("$"):
        env_name = api_key[1:]
        oracle["api_key"] = os.environ.get(env_name, "")

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
