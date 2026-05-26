"""
kernel.py -- Agentic loop for Husks oracle execution.

This module implements the agentic kernel: a fuel-bounded loop that
mediates between the LLM and the tool registry.  The kernel receives
a context (prompt, tool allowlist, model, fuel budget), invokes the
LLM, parses the response into actions, dispatches tool calls through
the sandboxed tool registry, and recurses until the LLM stops or
fuel is exhausted.

Execution flow
--------------
  1. agent() builds the initial context: prompt, tool schemas, fuel.
  2. step() calls the LLM (via invoke_llm), parses the response.
  3. If the response is a tool call: validate the tool is allowed,
     dispatch it, append the result to the conversation trace, and
     loop (iteratively, not recursively -- avoids Python stack limits
     at high fuel values).
  4. If the response is "stop": return the result.
  5. If fuel is exhausted: return a halt result.

Context dict
------------
The kernel threads a context dict ``C`` through the loop:

  prompt      str         -- the initial user prompt
  tools       list[str]   -- allowed tool names
  tool-defs   list[dict]  -- OpenAI function-calling schemas
  system      str|None    -- system prompt
  model       str         -- litellm model identifier
  max-tokens  int         -- max output tokens per LLM call
  rule        str|None    -- rule name (for usage tracking)
  trace       list[dict]  -- conversation trace (tool calls + results)

The trace is the conversation memory: each tool call appends an
entry with the form, tool name, and output.  The trace is rebuilt
into OpenAI messages format before each LLM call.

live_oracle()
-------------
Adapts the agentic kernel to the build's oracle backend signature::

    def live_oracle(S, rule_name, recipe, outputs) -> dict

This is what build.py calls when an oracle recipe fires.  It:
  1. Sets the site root for tool sandboxing.
  2. Constructs the system prompt (site location, required outputs).
  3. Snapshots usage before/after to compute token deltas.
  4. Runs agent() and returns usage dict.

Interface with husks
-------------------------
Imports from:

  oracle/llm.py    -- call_messages(), get_usage() for LLM invocation
                      and usage delta computation.
  oracle/tools.py  -- schemas(), dispatch(), set_site_root() for
                      tool management and sandboxing.

Consumed by:

  build.py         -- via the oracle_backend parameter passed to
                      build().  cli.py sets oracle_backend=live_oracle
                      for live runs.

  oracle/__init__  -- re-exports live_oracle and set_oracle_model.
"""

from __future__ import annotations

import json
from typing import Any, Callable

from husks.utils import trace as T

from husks.oracle import llm
from husks.oracle import tools


# ── Context helpers ───────────────────────────────────────────────

def _rebind(C: dict[str, Any], event: dict[str, Any]) -> dict[str, Any]:
    """Return a new context with *event* appended to the trace."""
    return {**C, "trace": C.get("trace", []) + [event]}


def _allowed(C: dict[str, Any], tool_name: str) -> bool:
    """True if *tool_name* is in the context's tool allowlist."""
    return tool_name in C.get("tools", [])


# ── Response parsing ──────────────────────────────────────────────

def parse_response(r: Any) -> dict[str, Any]:
    """Extract the first actionable block from a litellm response.

    Returns a dict with ``type`` key:
      - ``"act"``  : tool call with name, args, tool_call_id
      - ``"stop"`` : the model finished (finish_reason == "stop")
      - ``"say"``  : text output that is neither a tool call nor a stop
    """
    msg = r.choices[0].message
    tc = getattr(msg, "tool_calls", None)

    # Tool call present
    if tc and len(tc) > 0:
        call = tc[0]
        fn_obj = call.function
        name = fn_obj.name.replace("_", "-")
        try:
            args = json.loads(fn_obj.arguments or "{}")
        except Exception:
            args = {}
        return {
            "type": "act",
            "tool": name,
            "args": args,
            "tool_call_id": call.id,
        }

    # Finished
    if r.choices[0].finish_reason == "stop":
        return {"type": "stop", "value": msg.content or ""}

    # Otherwise treat as say
    return {"type": "say", "text": msg.content or ""}


# ── Message building ──────────────────────────────────────────────

def _build_messages(C: dict[str, Any]) -> list[dict[str, Any]]:
    """Build OpenAI messages list from the initial prompt + trace."""
    msgs: list[dict[str, Any]] = [
        {"role": "user", "content": C.get("prompt", "Run the task.")}
    ]
    for event in C.get("trace", []):
        form = event.get("form", {})
        kind = form.get("type", "")
        if kind == "act":
            tid = form.get("tool_call_id", "t0")
            tool_name = event.get("tool", "unknown")
            tool_args = form.get("args", {})
            out = event.get("out", "")
            out_str = out if isinstance(out, str) else json.dumps(out, default=str)
            fn_name = tool_name.replace("-", "_")
            # Assistant message with tool_calls array
            msgs.append({
                "role": "assistant",
                "content": None,
                "tool_calls": [{
                    "id": tid,
                    "type": "function",
                    "function": {
                        "name": fn_name,
                        "arguments": json.dumps(tool_args),
                    },
                }],
            })
            # Tool result message
            msgs.append({
                "role": "tool",
                "tool_call_id": tid,
                "content": out_str[:8000],
            })
    return msgs


# ── LLM invocation ────────────────────────────────────────────────

def invoke_llm(C: dict[str, Any]) -> dict[str, Any]:
    """Call the LLM with the current context and return a parsed response."""
    msgs = _build_messages(C)
    tool_schemas = C.get("tool-defs", [])
    kwargs: dict[str, Any] = {
        "model": C.get("model", llm.DEFAULT_MODEL),
        "max_tokens": C.get("max-tokens", 4096),
        "rule": C.get("rule"),
    }
    system = C.get("system")
    if system:
        kwargs["system"] = system
    if tool_schemas:
        kwargs["tools"] = tool_schemas
    r = llm.call_messages(msgs, **kwargs)
    return parse_response(r)


# ── Agentic step (iterative) ─────────────────────────────────────

def step(
    M: Callable[[dict], dict],
    C: dict[str, Any],
    fuel: int,
) -> dict[str, Any]:
    """Run the agentic loop iteratively until stop or fuel exhaustion.

    Unlike the original Hy implementation which used recursion, this
    version uses a while loop.  This avoids hitting Python's default
    recursion limit (~1000) at high fuel values.

    Parameters
    ----------
    M : callable
        The LLM invocation function (context -> parsed response).
    C : dict
        The current context.
    fuel : int
        Remaining fuel (agentic steps).

    Returns
    -------
    dict
        Result with keys: type, C, fuel_steps, and type-specific
        fields (value, text, error).
    """
    fuel_used = 0

    while True:
        try:
            form = M(C)
        except KeyboardInterrupt:
            return {"type": "kill", "C": C, "fuel_steps": fuel_used}

        kind = form.get("type")

        if fuel <= 0:
            return {"type": "halt", "C": C, "fuel_steps": fuel_used}

        if kind == "say":
            return {
                "type": "say",
                "text": form.get("text"),
                "C": C,
                "fuel_steps": fuel_used,
            }

        if kind == "stop":
            return {
                "type": "stop",
                "value": form.get("value", C),
                "C": C,
                "fuel_steps": fuel_used,
            }

        if kind == "act":
            name = form.get("tool")
            args = form.get("args", {})

            if not _allowed(C, name):
                return {
                    "type": "error",
                    "error": f"{name} not in scope",
                    "C": C,
                    "fuel_steps": fuel_used,
                }

            T.tool_call(C.get("rule", "agent"), name, args)
            out = tools.dispatch(name, args)
            C = _rebind(C, {"form": form, "tool": name, "out": out})
            T.tool_result(name, out)

            fuel -= 1
            fuel_used += 1
            continue

        # Unknown form
        return {
            "type": "error",
            "error": f"bad form: {form}",
            "C": C,
            "fuel_steps": fuel_used,
        }


def agent(
    C: dict[str, Any],
    *,
    fuel: int = 8,
    M: Callable[[dict], dict] | None = None,
) -> dict[str, Any]:
    """Run the agentic kernel with the given context.

    Parameters
    ----------
    C : dict
        Context with at minimum ``prompt`` and ``tools``.
    fuel : int
        Maximum agentic steps (tool calls).
    M : callable, optional
        LLM invocation function.  Defaults to invoke_llm.

    Returns
    -------
    dict
        Result from step().
    """
    if M is None:
        M = invoke_llm
    tool_names = C.get("tools", [])
    tool_defs = tools.schemas(tool_names)
    C0 = {"trace": [], "tool-defs": tool_defs, **C}
    return step(M, C0, fuel)


# ── Oracle model ──────────────────────────────────────────────────

_oracle_model: str = llm.DEFAULT_MODEL


def set_oracle_model(model: str) -> None:
    """Set the default model for live oracle execution."""
    global _oracle_model
    _oracle_model = model


def get_oracle_model() -> str:
    """Return the current oracle model."""
    return _oracle_model


# ── Live oracle backend ──────────────────────────────────────────

def live_oracle(
    S: dict[str, Any],
    rule_name: str,
    recipe: dict[str, Any],
    outputs: list[str],
) -> dict[str, Any]:
    """Run the kernel as a build oracle backend.

    This function matches the OracleBackend signature expected by
    build.py.  It:
      1. Activates site-root sandboxing.
      2. Constructs a system prompt with the site location and
         required output files.
      3. Snapshots usage before/after to compute token deltas.
      4. Runs agent() and returns the usage dict.

    Parameters
    ----------
    S : Store
        The build store (must contain "site").
    rule_name : str
        The name of the rule being evaluated.
    recipe : dict
        The oracle recipe (prompt, tools, fuel).
    outputs : list of str
        Declared output filenames that the oracle must produce.

    Returns
    -------
    dict
        Usage dict with keys: tokens_in, tokens_out, cost_usd,
        fuel_steps.
    """
    site: str = S["site"]
    prompt: str = recipe.get("prompt", "")
    tool_names: list[str] = recipe.get(
        "tools", ["read-file", "write-file", "list-dir", "tree"]
    )
    fuel: int = recipe.get("fuel", 8)

    # Enforce site containment at the tool layer
    readonly: list[str] = S.get("readonly-dirs", [])
    tools.set_site_root(site, readonly=readonly or None)

    # System prompt: tell the oracle where it is and what it must produce
    output_lines = "\n".join(f"  - {site}/{o}" for o in outputs)
    system = (
        "You are an oracle inside a build system.\n"
        f"Site directory: {site}\n"
        "All file paths must be absolute, rooted at the site.\n"
        "You must produce these outputs:\n"
        f"{output_lines}\n\n"
        "Use the available tools to read inputs and write outputs. "
        "When finished, stop."
    )

    # Snapshot usage before
    before = llm.get_usage()
    ti0 = before["input_tokens"]
    to0 = before["output_tokens"]
    c0 = before["cost_usd"]

    try:
        result = agent(
            {
                "prompt": prompt,
                "tools": tool_names,
                "system": system,
                "model": _oracle_model,
                "rule": rule_name,
            },
            fuel=fuel,
        )
    finally:
        tools.set_site_root(None)

    # Compute delta
    after = llm.get_usage()
    return {
        "tokens_in": after["input_tokens"] - ti0,
        "tokens_out": after["output_tokens"] - to0,
        "cost_usd": after["cost_usd"] - c0,
        "fuel_steps": result.get("fuel_steps", 0),
    }
