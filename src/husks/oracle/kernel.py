"""
kernel.py -- Fuel-bounded agentic loop for Husks oracle execution.

Mediates between the LLM and the sandboxed tool registry.  Loops
iteratively until the LLM stops or fuel is exhausted.  live_oracle()
adapts the kernel to the build's oracle backend signature.

See docs/architecture.md for context dict schema, execution flow,
and the live_oracle adapter.
"""

from __future__ import annotations

import json
from typing import Any, Callable

from husks.utils import trace as T

from husks.oracle import llm
from husks.oracle import tools

# Maximum characters kept from a tool output before truncation.
MAX_TOOL_OUTPUT: int = 8000


# ── Truncation helper ─────────────────────────────────────────────

def _truncate(s: str) -> str:
    """Truncate tool output with a marker if it exceeds MAX_TOOL_OUTPUT."""
    if len(s) > MAX_TOOL_OUTPUT:
        return s[:MAX_TOOL_OUTPUT] + "\n\n[... truncated ...]"
    return s


# ── Context helpers ───────────────────────────────────────────────

def _rebind(C: dict[str, Any], event: dict[str, Any]) -> dict[str, Any]:
    """Return a new context with *event* appended to the trace."""
    return {**C, "trace": C.get("trace", []) + [event]}


def _allowed(C: dict[str, Any], tool_name: str) -> bool:
    """True if *tool_name* is in the context's tool allowlist."""
    return tool_name in C.get("tools", [])


def _dispatch_context(C: dict[str, Any]) -> dict[str, Any]:
    """Build keyword arguments for tools.dispatch from the kernel context."""
    ctx: dict[str, Any] = {}
    sr = C.get("site_root")
    ro = C.get("readonly_roots")
    if sr is not None or ro is not None:
        ctx["context"] = {}
        if sr is not None:
            ctx["context"]["site_root"] = sr
        if ro is not None:
            ctx["context"]["readonly_roots"] = ro
    return ctx


# ── Response parsing ──────────────────────────────────────────────

def parse_response(r: Any) -> dict[str, Any]:
    """Extract actionable blocks from a litellm response.

    Returns a dict with ``type`` key:
      - ``"act"``  : single tool call with name, args, tool_call_id
      - ``"acts"`` : multiple parallel tool calls (list of call dicts)
      - ``"stop"`` : the model finished (finish_reason == "stop")
      - ``"say"``  : text output that is neither a tool call nor a stop
    """
    msg = r.choices[0].message
    tc = getattr(msg, "tool_calls", None)

    # Multiple parallel tool calls
    if tc and len(tc) > 1:
        calls = []
        for call in tc:
            fn_obj = call.function
            name = fn_obj.name.replace("_", "-")
            try:
                args = json.loads(fn_obj.arguments or "{}")
            except Exception:
                args = {}
            calls.append({
                "tool": name, "args": args, "tool_call_id": call.id,
            })
        return {"type": "acts", "calls": calls}

    # Single tool call
    if tc and len(tc) == 1:
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
                "content": _truncate(out_str),
            })
        elif kind == "acts":
            # Parallel tool calls: one assistant message with all calls,
            # then one tool result message per call.
            calls_data = event.get("calls", [])
            results = event.get("results", [])
            tool_calls_arr = []
            for cd in calls_data:
                fn_name = cd["tool"].replace("-", "_")
                tool_calls_arr.append({
                    "id": cd.get("tool_call_id", "t0"),
                    "type": "function",
                    "function": {
                        "name": fn_name,
                        "arguments": json.dumps(cd.get("args", {})),
                    },
                })
            msgs.append({
                "role": "assistant",
                "content": None,
                "tool_calls": tool_calls_arr,
            })
            for cd, res in zip(calls_data, results):
                out = res if isinstance(res, str) else json.dumps(res, default=str)
                msgs.append({
                    "role": "tool",
                    "tool_call_id": cd.get("tool_call_id", "t0"),
                    "content": _truncate(out),
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
    tracker = C.get("tracker")
    if tracker is not None:
        kwargs["tracker"] = tracker
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
        if fuel <= 0:
            return {"type": "halt", "C": C, "fuel_steps": fuel_used}

        try:
            form = M(C)
        except KeyboardInterrupt:
            return {"type": "kill", "C": C, "fuel_steps": fuel_used}

        kind = form.get("type")

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
            ctx = _dispatch_context(C)
            out = tools.dispatch(name, args, **ctx)
            C = _rebind(C, {"form": form, "tool": name, "out": out})
            T.tool_result(name, out)

            fuel -= 1
            fuel_used += 1
            continue

        if kind == "acts":
            calls = form.get("calls", [])
            results = []
            for i, cd in enumerate(calls):
                if fuel <= 0:
                    # Partial batch: record what ran so far
                    C = _rebind(C, {
                        "form": form,
                        "calls": calls[:i],
                        "results": results,
                    })
                    return {"type": "halt", "C": C, "fuel_steps": fuel_used}

                name = cd["tool"]
                args = cd.get("args", {})

                if not _allowed(C, name):
                    return {
                        "type": "error",
                        "error": f"{name} not in scope",
                        "C": C,
                        "fuel_steps": fuel_used,
                    }

                T.tool_call(C.get("rule", "agent"), name, args)
                ctx = _dispatch_context(C)
                out = tools.dispatch(name, args, **ctx)
                T.tool_result(name, out)
                results.append(out)

                fuel -= 1
                fuel_used += 1

            C = _rebind(C, {
                "form": form,
                "calls": calls,
                "results": results,
            })
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
    from pathlib import Path as _Path

    site: str = S.get("stage", S["site"])
    prompt: str = recipe.get("prompt", "")
    tool_names: list[str] = recipe.get(
        "tools", ["read-file", "write-file", "list-dir", "tree"]
    )
    fuel: int = recipe.get("fuel", 8)

    # Enforce site containment at the tool layer (global, for backward compat)
    readonly: list[str] = S.get("readonly-dirs", [])
    tools.set_site_root(site, readonly=readonly or None)

    # Context-threaded site root and readonly roots (per-invocation)
    site_root = _Path(site).resolve()
    readonly_roots = {_Path(p).resolve() for p in (readonly or [])}

    # Per-invocation usage tracker
    tracker = llm.UsageTracker()

    # System prompt: tell the oracle where it is and what it must produce
    output_lines = "\n".join(f"  - {o}" for o in outputs)
    system = (
        "You are an oracle inside a build system.\n"
        f"Site directory: {site}\n"
        "File paths are relative to the site directory.\n"
        "You must produce these outputs:\n"
        f"{output_lines}\n\n"
        "Use the available tools to read inputs and write outputs. "
        "When finished, stop."
    )

    try:
        result = agent(
            {
                "prompt": prompt,
                "tools": tool_names,
                "system": system,
                "model": _oracle_model,
                "rule": rule_name,
                "tracker": tracker,
                "site_root": site_root,
                "readonly_roots": readonly_roots,
            },
            fuel=fuel,
        )
    finally:
        tools.set_site_root(None)

    # Check agent result status - only "stop" is successful
    result_type = result.get("type")
    if result_type != "stop":
        # Agent failed - raise to prevent sealing partial outputs
        if result_type == "error":
            error_msg = result.get("error", "unknown error")
            raise RuntimeError(f"oracle agent error: {error_msg}")
        elif result_type == "halt":
            raise RuntimeError("oracle agent ran out of fuel")
        elif result_type == "kill":
            raise RuntimeError("oracle agent interrupted")
        elif result_type == "say":
            text = result.get("text", "")
            raise RuntimeError(f"oracle agent produced text without stopping: {text[:100]}")
        else:
            raise RuntimeError(f"oracle agent returned unexpected type: {result_type}")

    # Compute deltas from the local tracker
    snap = tracker.snapshot()
    return {
        "tokens_in": snap["input_tokens"],
        "tokens_out": snap["output_tokens"],
        "cost_usd": snap["cost_usd"],
        "fuel_steps": result.get("fuel_steps", 0),
    }
