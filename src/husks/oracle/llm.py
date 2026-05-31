"""
llm.py -- LiteLLM wrapper with cumulative usage tracking.

Uniform calling interface for LLM providers via litellm.completion().
Per-UsageTracker instance token/cost accumulation.  No husks imports;
only external dependency is litellm.

Beta 100: Adds provenance hashing for config and prompt reproducibility.
"""

from __future__ import annotations

from typing import Any
import hashlib
import json


def _litellm():
    """Lazy import of litellm — only needed for live oracle calls."""
    try:
        import litellm
        return litellm
    except ModuleNotFoundError:
        raise ModuleNotFoundError(
            "litellm is required for live oracle calls. "
            "Install it with: pip install litellm"
        ) from None

# ── Default model ─────────────────────────────────────────────────

DEFAULT_MODEL: str = "anthropic/claude-haiku-4-5-20251001"


# ── Provenance hashing (Beta 100) ────────────────────────────────

def compute_config_hash(
    model: str,
    max_tokens: int,
    temperature: float | None = None,
    tools: list[dict] | None = None,
) -> str:
    """Compute deterministic config hash for oracle provenance.

    Beta 100: Hash stable config fields for M1/M3 comparability.

    Parameters
    ----------
    model : str
        LiteLLM model identifier
    max_tokens : int
        Maximum output tokens
    temperature : float, optional
        Sampling temperature
    tools : list of dicts, optional
        Tool definitions (we hash tool names only, not implementations)

    Returns
    -------
    str
        SHA-256 hex hash of config (lowercase)
    """
    # Build stable config dict
    config = {
        "backend": "litellm",
        "model": model,
        "max_tokens": max_tokens,
    }

    if temperature is not None:
        config["temperature"] = temperature

    if tools:
        # Hash tool names only (stable across implementations)
        config["tools"] = sorted([t.get("function", {}).get("name", "") for t in tools])

    # JSON serialize with sorted keys for determinism
    config_json = json.dumps(config, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(config_json.encode("utf-8")).hexdigest()


def compute_prompt_hash(prompt: str) -> str:
    """Compute deterministic prompt hash.

    Parameters
    ----------
    prompt : str
        Prompt content

    Returns
    -------
    str
        SHA-256 hex hash (lowercase)
    """
    return hashlib.sha256(prompt.encode("utf-8")).hexdigest()


# ── Usage tracker ─────────────────────────────────────────────────

class UsageTracker:
    """Cumulative token and cost tracker.

    Create one per build invocation (or per test) to avoid
    module-global mutable state.
    """

    __slots__ = ("calls", "input_tokens", "output_tokens", "cost_usd",
                 "by_rule", "model")

    def __init__(self) -> None:
        self.calls: int = 0
        self.input_tokens: int = 0
        self.output_tokens: int = 0
        self.cost_usd: float = 0.0
        self.by_rule: dict[str, dict[str, Any]] = {}
        self.model: str | None = None

    def track(self, response: Any, rule: str | None = None) -> None:
        """Accumulate usage from a litellm response."""
        u = response.usage
        inp: int = u.prompt_tokens or 0
        out: int = u.completion_tokens or 0
        try:
            cost = _litellm().completion_cost(completion_response=response)
        except Exception:
            cost = 0.0

        self.calls += 1
        self.input_tokens += inp
        self.output_tokens += out
        self.cost_usd += cost
        if self.model is None:
            self.model = response.model

        if rule:
            s = self.by_rule.setdefault(rule, {
                "calls": 0, "input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0,
            })
            s["calls"] += 1
            s["input_tokens"] += inp
            s["output_tokens"] += out
            s["cost_usd"] += cost

    def snapshot(self) -> dict[str, Any]:
        """Return a copy of the current cumulative usage stats."""
        return {
            "calls": self.calls,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "cost_usd": round(self.cost_usd, 6),
            "by_rule": dict(self.by_rule),
            "model": self.model,
        }


# Module-level default tracker for backwards compatibility.
_usage = UsageTracker()


def get_usage() -> dict[str, Any]:
    """Return cumulative usage stats from the default tracker."""
    return _usage.snapshot()


def reset_usage() -> None:
    """Reset the default tracker to zero."""
    global _usage
    _usage = UsageTracker()


# ── Single-shot call ──────────────────────────────────────────────

def call(
    prompt: str,
    model: str = DEFAULT_MODEL,
    max_tokens: int = 1024,
    system: str | None = None,
    tools: list[dict] | None = None,
    temperature: float | None = None,
    tracker: UsageTracker | None = None,
) -> Any:
    """Single-shot LLM call.  Returns the litellm response object.

    Beta 100: Attaches config_hash and prompt_hash to response for provenance.
    """
    msgs: list[dict[str, Any]] = []
    if system:
        msgs.append({"role": "system", "content": system})
    msgs.append({"role": "user", "content": prompt})
    kwargs: dict[str, Any] = {"model": model, "max_tokens": max_tokens, "messages": msgs}
    if tools:
        kwargs["tools"] = tools
    if temperature is not None:
        kwargs["temperature"] = temperature
    r = _litellm().completion(**kwargs)
    (tracker or _usage).track(r)

    # Beta 100: Attach provenance hashes to response
    r._husks_config_hash = compute_config_hash(model, max_tokens, temperature, tools)
    r._husks_prompt_hash = compute_prompt_hash(prompt)

    return r


# ── Multi-turn call ───────────────────────────────────────────────

def call_messages(
    messages: list[dict[str, Any]],
    model: str = DEFAULT_MODEL,
    max_tokens: int = 4096,
    system: str | None = None,
    tools: list[dict] | None = None,
    temperature: float | None = None,
    rule: str | None = None,
    tracker: UsageTracker | None = None,
) -> Any:
    """Multi-turn LLM call with pre-built messages list.

    Beta 100: Attaches config_hash and prompt_hash to response for provenance.

    Parameters
    ----------
    messages : list of dicts
        OpenAI-format message list.
    model : str
        LiteLLM model identifier.
    max_tokens : int
        Maximum output tokens.
    system : str, optional
        System prompt (prepended as a system message).
    tools : list of dicts, optional
        OpenAI function-calling tool definitions.
    temperature : float, optional
        Sampling temperature.
    rule : str, optional
        Rule name for per-rule usage tracking.
    tracker : UsageTracker, optional
        Usage tracker instance.  Defaults to the module-level tracker.

    Returns
    -------
    litellm response object.
    """
    msgs = list(messages)
    if system:
        msgs.insert(0, {"role": "system", "content": system})
    kwargs: dict[str, Any] = {"model": model, "max_tokens": max_tokens, "messages": msgs}
    if tools:
        kwargs["tools"] = tools
    if temperature is not None:
        kwargs["temperature"] = temperature
    r = _litellm().completion(**kwargs)
    (tracker or _usage).track(r, rule=rule)

    # Beta 100: Attach provenance hashes
    r._husks_config_hash = compute_config_hash(model, max_tokens, temperature, tools)
    # For messages, hash the entire conversation
    prompt_content = json.dumps(msgs, sort_keys=True, separators=(",", ":"))
    r._husks_prompt_hash = hashlib.sha256(prompt_content.encode("utf-8")).hexdigest()

    return r


# ── Response metadata ─────────────────────────────────────────────

def meta(response: Any) -> dict[str, Any]:
    """Extract metadata from a litellm response (OpenAI shape).

    Beta 100: Includes config_hash and prompt_hash for provenance.

    Returns a dict with keys: model, input_tokens, output_tokens,
    finish_reason, cost_usd, text, config_hash, prompt_hash.
    """
    msg = response.choices[0].message
    u = response.usage
    inp: int = u.prompt_tokens or 0
    out: int = u.completion_tokens or 0
    try:
        cost = _litellm().completion_cost(completion_response=response)
    except Exception:
        cost = 0.0

    result = {
        "model": response.model,
        "input_tokens": inp,
        "output_tokens": out,
        "finish_reason": response.choices[0].finish_reason,
        "cost_usd": round(cost, 6),
        "text": msg.content or "",
    }

    # Beta 100: Include provenance hashes if available
    if hasattr(response, "_husks_config_hash"):
        result["config_hash"] = response._husks_config_hash
    if hasattr(response, "_husks_prompt_hash"):
        result["prompt_hash"] = response._husks_prompt_hash

    return result
