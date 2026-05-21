#- llm.py — LLM wrapper (liteLLM)
#
# litellm.completion() replaces direct Anthropic client.
# litellm.completion_cost() replaces hardcoded PRICING.
# Model names use provider prefix: "anthropic/claude-haiku-4-5-20251001"

import litellm


# ── Cumulative cost tracker ──────────────────────────────────
_usage = {
    "calls": 0,
    "input_tokens": 0,
    "output_tokens": 0,
    "cost_usd": 0.0,
    "by_rule": {},   # rule_name -> {calls, input_tokens, output_tokens, cost_usd}
    "model": None,
}


def _track(response, rule=None):
    """Accumulate usage from a litellm response."""
    u = response.usage
    inp = u.prompt_tokens or 0
    out = u.completion_tokens or 0
    try:
        cost = litellm.completion_cost(completion_response=response)
    except Exception:
        cost = 0.0

    _usage["calls"] += 1
    _usage["input_tokens"] += inp
    _usage["output_tokens"] += out
    _usage["cost_usd"] += cost
    if _usage["model"] is None:
        _usage["model"] = response.model

    if rule:
        s = _usage["by_rule"].setdefault(rule, {
            "calls": 0, "input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0
        })
        s["calls"] += 1
        s["input_tokens"] += inp
        s["output_tokens"] += out
        s["cost_usd"] += cost


def get_usage():
    """Return cumulative usage stats."""
    return {k: (round(v, 6) if isinstance(v, float) else v)
            for k, v in _usage.items()}


# ── Single-shot call ─────────────────────────────────────────
def call(prompt, model="anthropic/claude-haiku-4-5-20251001", max_tokens=1024,
         system=None, tools=None, temperature=None):
    msgs = []
    if system:
        msgs.append({"role": "system", "content": system})
    msgs.append({"role": "user", "content": prompt})
    kwargs = dict(model=model, max_tokens=max_tokens, messages=msgs)
    if tools:
        kwargs["tools"] = tools
    if temperature is not None:
        kwargs["temperature"] = temperature
    r = litellm.completion(**kwargs)
    _track(r)
    return r


# ── Multi-turn call ──────────────────────────────────────────
def call_messages(messages, model="anthropic/claude-haiku-4-5-20251001",
                  max_tokens=4096, system=None, tools=None,
                  temperature=None, rule=None):
    """Like call() but accepts pre-built messages list."""
    msgs = list(messages)
    if system:
        msgs.insert(0, {"role": "system", "content": system})
    kwargs = dict(model=model, max_tokens=max_tokens, messages=msgs)
    if tools:
        kwargs["tools"] = tools
    if temperature is not None:
        kwargs["temperature"] = temperature
    r = litellm.completion(**kwargs)
    _track(r, rule=rule)
    return r


# ── Response metadata ────────────────────────────────────────
def meta(response):
    """Extract metadata from a litellm response (OpenAI shape)."""
    msg = response.choices[0].message
    u = response.usage
    inp = u.prompt_tokens or 0
    out = u.completion_tokens or 0
    try:
        cost = litellm.completion_cost(completion_response=response)
    except Exception:
        cost = 0.0
    return {
        "model": response.model,
        "input_tokens": inp,
        "output_tokens": out,
        "finish_reason": response.choices[0].finish_reason,
        "cost_usd": round(cost, 6),
        "text": msg.content or "",
    }


if __name__ == "__main__":
    r = call("Say hello in one sentence.")
    print(meta(r))
