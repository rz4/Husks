"""
litellm.py -- LiteLLM oracle 
Owns an OpenAI-shaped agent loop (kernel.py) and reaches providers
through litellm.  Enforces the tool allowlist and the fuel bound
*in-process*: the loop dispatches every tool itself, so "allowed" and
"out of fuel" are decided here (kernel._allowed, kernel.step), not
trusted to the model.  This is the strong case -- no out-of-band
interceptor is needed because the loop is the interceptor.

This module absorbs the build-facing logic that used to live in
kernel.live_oracle.  kernel.py keeps only the loop primitives
(parse_response, _build_messages, invoke_llm, step, agent) and the
process-default model getter/setter.

Config  (S["oracle-config"], every field optional)
--------------------------------------------------
  model     : str   -- litellm model id.  Default llm.DEFAULT_MODEL.
  params    : dict  -- opaque pass-through to litellm.completion.
                       temperature, top_p, api_base, api_key,
                       custom_llm_provider, num_retries, timeout,
                       fallbacks, response_format, reasoning_effort,
                       thinking, metadata, extra_headers, caching,
                       drop_params, ...  Any current or future litellm
                       kwarg.  messages / tools / model are owned by the
                       loop and cannot be set here.
  router    : litellm.Router | None
                    -- if set, calls route through it (load-balancing,
                       fallbacks, retries across a model_list) instead
                       of litellm.completion.
  per_rule  : dict[str, dict]
                    -- {model, params, router} overrides keyed by rule
                       name.  Provenance only; does not re-fire seals.

None of this enters the recipe digest.  Two designs with identical
(prompt, tools, fuel) seal identically no matter the model, provider,
sampling params, or router behind them.  Consequence to know: changing
params alone will NOT re-fire a sealed rule.  To force a re-run, change
the recipe (prompt / tools / fuel), not the route.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from husks.oracle import backend
from husks.oracle.backend import RealizedCost
from husks.oracle import kernel, llm, tools


def _resolve_config(config: dict[str, Any], rule_name: str) -> dict[str, Any]:
    """Merge the per-rule override (if any) over the base config."""
    override = config.get("per_rule", {}).get(rule_name, {})
    return {**config, **override}


def _raise_unless_stop(result: dict[str, Any]) -> None:
    """Parity with the old live_oracle: only a clean stop seals.

    Anything else raises so the build does not seal partial output.
    """
    t = result.get("type")
    if t == "stop":
        return
    if t == "error":
        raise RuntimeError(f"oracle agent error: {result.get('error', 'unknown')}")
    if t == "halt":
        raise RuntimeError("oracle agent ran out of fuel")
    if t == "kill":
        raise RuntimeError("oracle agent interrupted")
    if t == "say":
        text = result.get("text", "")
        raise RuntimeError(
            f"oracle agent produced text without stopping: {text[:100]}"
        )
    raise RuntimeError(f"oracle agent returned unexpected type: {t}")


class LiteLLMBackend:
    name = "litellm"

    def run(
        self,
        S: dict[str, Any],
        rule_name: str,
        recipe: dict[str, Any],
        outputs: list[str],
        config: dict[str, Any],
    ) -> RealizedCost:
        site = str(backend.site_of(S))
        prompt: str = recipe.get("prompt", "")
        tool_names: list[str] = recipe.get("tools", backend.DEFAULT_TOOLS)
        fuel: int = recipe.get("fuel", 8)

        rc = _resolve_config(config, rule_name)
        model = rc.get("model", llm.DEFAULT_MODEL)
        params = rc.get("params") or {}
        router = rc.get("router")

        # Site containment at the tool layer (same as before).
        readonly = S.get("readonly-dirs", [])
        tools.set_site_root(site, readonly=readonly or None)
        site_root = Path(site).resolve()
        readonly_roots = backend.readonly_roots_of(S)
        tracker = llm.UsageTracker()
        system = backend.build_system_prompt(site, outputs)

        try:
            result = kernel.agent(
                {
                    "prompt": prompt,
                    "tools": tool_names,
                    "system": system,
                    "model": model,
                    "params": params,      # threaded to llm.call_messages
                    "router": router,      # threaded to llm.call_messages
                    "rule": rule_name,
                    "tracker": tracker,
                    "site_root": site_root,
                    "readonly_roots": readonly_roots,
                },
                fuel=fuel,
            )
        finally:
            tools.set_site_root(None)

        _raise_unless_stop(result)

        snap = tracker.snapshot()
        return RealizedCost(
            tokens_in=snap["input_tokens"],
            tokens_out=snap["output_tokens"],
            cost_usd=snap["cost_usd"],
            fuel_steps=result.get("fuel_steps", 0),
        )
