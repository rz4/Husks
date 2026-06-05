"""L4 oracle -- LLM backend, fuel-bounded kernel, tool sandbox.

Sits on stdlib only (+ litellm/claude_code_sdk as lazy optional imports).
Single module merging backend.py, tools.py, kernel.py, llm.py, litellm.py,
claude_code.py, and __init__.py.  No husks.utils.trace coupling: all events
stay in the kernel context trace list.  No module-level mutable state except
the backend and tool registries (populated at import time for tools, lazily
for backends).
"""

from __future__ import annotations

import hashlib
import inspect
import json
import os
import signal
from pathlib import Path
from typing import Any, Callable, Protocol, TypedDict, get_type_hints, runtime_checkable


# ── Types ────────────────────────────────────────────────────────

class RealizedCost(TypedDict):
    """What a backend reports after producing oracle outputs.  Provenance only."""
    tokens_in: int
    tokens_out: int
    cost_usd: float
    fuel_steps: int


@runtime_checkable
class OracleBackend(Protocol):
    """Produce an oracle rule's outputs, bounded by tools and fuel.

    Must: (1) confine effects to site + readonly roots, (2) permit only
    recipe tools, (3) stop at recipe fuel, (4) raise on non-clean exit,
    (5) return RealizedCost.  Must NOT read config from recipe.
    """
    name: str
    def run(self, S: dict[str, Any], rule_name: str, recipe: dict[str, Any],
            outputs: list[str], config: dict[str, Any]) -> RealizedCost: ...


# ── Backend registry ─────────────────────────────────────────────

_BACKENDS: dict[str, OracleBackend] = {}


def register(backend: OracleBackend) -> None:
    """Register a backend under its name.  Idempotent."""
    _BACKENDS[backend.name] = backend


def get_backend(name: str) -> OracleBackend:
    """Get backend by name, lazy-loading concrete backends on first use."""
    if name not in _BACKENDS:
        if name == "litellm":
            register(LiteLLMBackend())
        elif name == "claude-code":
            register(ClaudeCodeBackend())
    if name not in _BACKENDS:
        known = ", ".join(sorted(_BACKENDS)) or "(none)"
        raise KeyError(f"unknown oracle backend {name!r}; registered: {known}")
    return _BACKENDS[name]


# ── Shared scaffolding ───────────────────────────────────────────

DEFAULT_TOOLS: list[str] = ["read-file", "write-file", "list-dir", "tree"]


def build_system_prompt(site: str, outputs: list[str]) -> str:
    """The oracle's standing orders: where it is, what it must produce."""
    lines = "\n".join(f"  - {o}" for o in outputs)
    return (
        "You are an oracle inside a build system.\n"
        "All file paths are relative to the working directory.\n"
        f"You must produce these outputs:\n{lines}\n\n"
        "Use the available tools to read inputs and write outputs. "
        "When finished, stop."
    )


def site_of(S: dict[str, Any]) -> Path:
    """Resolve the build site (stage if staging, else site)."""
    return Path(S.get("stage", S["site"])).resolve()


def readonly_roots_of(S: dict[str, Any]) -> set[Path]:
    """Resolve declared readonly roots from the store."""
    return {Path(p).resolve() for p in S.get("readonly-dirs", [])}


# ── Tool sandbox ─────────────────────────────────────────────────

MAX_WRITE_SIZE = 10 * 1024 * 1024   # 10 MB
MAX_TOOL_TIMEOUT = 30                # seconds


def sandbox(path: str, *, write: bool = False,
            site_root: Path | None = None,
            readonly_roots: set[Path] | None = None) -> Path:
    """Resolve path within sandbox.  Raises ValueError on escape.

    write=True restricts to site_root only (never readonly_roots).
    """
    raw = Path(path)
    if site_root is not None and not raw.is_absolute():
        p = (site_root / raw).resolve()
    else:
        p = raw.resolve()
    if site_root is None:
        return p
    try:
        p.relative_to(site_root)
        return p
    except ValueError:
        pass
    if write:
        raise ValueError(
            f"path '{path}' resolves to '{p}' outside site root '{site_root}' (write denied)"
        ) from None
    for ro in (readonly_roots or set()):
        try:
            p.relative_to(ro)
            return p
        except ValueError:
            continue
    raise ValueError(
        f"path '{path}' resolves to '{p}' outside site root '{site_root}'"
    ) from None


# ── Tool registry ────────────────────────────────────────────────

_TOOLS: dict[str, dict[str, Any]] = {}
_INTERNAL_PARAMS = frozenset({"site_root", "readonly_roots"})


def tool(fn):
    """Register a function as a tool.  Name from fn.__name__ with _ -> -."""
    name = fn.__name__.replace("_", "-")
    hints = get_type_hints(fn)
    sig = inspect.signature(fn)
    props, required = {}, []
    for pname, param in sig.parameters.items():
        if pname in _INTERNAL_PARAMS or param.kind == inspect.Parameter.KEYWORD_ONLY:
            continue
        ptype = hints.get(pname, str)
        jtype = {str: "string", int: "integer", float: "number", bool: "boolean"}.get(ptype, "string")
        props[pname] = {"type": jtype, "description": pname}
        if param.default is inspect.Parameter.empty:
            required.append(pname)
    schema = {"type": "function", "function": {
        "name": name, "description": (fn.__doc__ or "").strip(),
        "parameters": {"type": "object", "properties": props, "required": required},
    }}
    _TOOLS[name] = {"fn": fn, "schema": schema}
    return fn


def schemas(names: list[str] | None = None) -> list[dict[str, Any]]:
    """Return OpenAI function-calling tool definitions."""
    if names is None:
        return [v["schema"] for v in _TOOLS.values()]
    return [_TOOLS[n]["schema"] for n in names if n in _TOOLS]


def _timeout_handler(signum, frame):
    raise TimeoutError("tool execution exceeded time limit")


def dispatch(name: str, args: dict[str, Any], *,
             context: dict[str, Any] | None = None,
             timeout: int | None = None) -> str:
    """Call a registered tool by name.  Returns string output or error string."""
    entry = _TOOLS.get(name)
    if entry is None:
        return f"Error: unknown tool '{name}'"
    effective_timeout = timeout if timeout is not None else MAX_TOOL_TIMEOUT
    old_handler = None
    try:
        if hasattr(signal, "SIGALRM"):
            old_handler = signal.signal(signal.SIGALRM, _timeout_handler)
            signal.alarm(effective_timeout)
        result = entry["fn"](**args, **context) if context else entry["fn"](**args)
        return result
    except Exception as e:
        return f"Error: {type(e).__name__} in '{name}': {e}"
    finally:
        if hasattr(signal, "SIGALRM"):
            signal.alarm(0)
            if old_handler:
                signal.signal(signal.SIGALRM, old_handler)


# ── Built-in tools ───────────────────────────────────────────────

@tool
def read_file(path: str, *, site_root=None, readonly_roots=None) -> str:
    """Return file contents as a string."""
    try:
        p = sandbox(path, site_root=site_root, readonly_roots=readonly_roots)
    except ValueError as e:
        return f"Error: {e}"
    if p.is_dir():
        return f"Error: '{path}' is a directory, not a file. Use list-dir instead."
    if not p.exists():
        return f"Error: '{path}' does not exist."
    try:
        return p.read_text()
    except UnicodeDecodeError:
        return f"Error: '{path}' is a binary file and cannot be read as text."


@tool
def write_file(path: str, content: str, *, site_root=None, readonly_roots=None) -> str:
    """Write content to a file, creating parent directories as needed."""
    content_bytes = content.encode("utf-8")
    if len(content_bytes) > MAX_WRITE_SIZE:
        return f"Error: content size ({len(content_bytes) / (1024*1024):.1f} MB) exceeds max ({MAX_WRITE_SIZE / (1024*1024):.1f} MB)"
    try:
        p = sandbox(path, write=True, site_root=site_root, readonly_roots=readonly_roots)
    except ValueError as e:
        return f"Error: {e}"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content)
    return "ok"


@tool
def list_dir(path: str, *, site_root=None, readonly_roots=None) -> str:
    """Return names in a directory (one level)."""
    try:
        p = sandbox(path, site_root=site_root, readonly_roots=readonly_roots)
    except ValueError as e:
        return f"Error: {e}"
    if not p.exists():
        return f"Error: '{path}' does not exist."
    if not p.is_dir():
        return f"Error: '{path}' is not a directory."
    return "\n".join(sorted(os.listdir(str(p))))


@tool
def tree(path: str, depth: int = 3, *, site_root=None, readonly_roots=None) -> str:
    """Recursive directory listing up to the given depth."""
    try:
        root = sandbox(path, site_root=site_root, readonly_roots=readonly_roots)
    except ValueError as e:
        return f"Error: {e}"
    if not root.exists():
        return f"Error: '{path}' does not exist."
    if not root.is_dir():
        return f"Error: '{path}' is not a directory."
    sr = Path(site_root) if site_root and not isinstance(site_root, Path) else site_root
    ro = ({Path(p) if not isinstance(p, Path) else p for p in readonly_roots}
          if readonly_roots else None)
    lines: list[str] = []
    _walk(root, root, depth, lines, sr, ro)
    return "\n".join(lines)


def _walk(base: Path, current: Path, depth: int, lines: list[str],
          site_root: Path | None, readonly_roots: set[Path] | None) -> None:
    """Recursive tree helper.  Skips hidden files, __pycache__, sandbox escapes."""
    if depth < 0:
        return
    rel = current.relative_to(base)
    indent = "  " * len(rel.parts)
    if current == base:
        lines.append(str(base))
    else:
        lines.append(f"{indent}{current.name}{'/' if current.is_dir() else ''}")
    if not current.is_dir():
        return
    for child in sorted(current.iterdir(), key=lambda p: (not p.is_dir(), p.name)):
        if child.name.startswith(".") or child.name == "__pycache__":
            continue
        if site_root is not None:
            try:
                resolved = child.resolve()
                try:
                    resolved.relative_to(site_root)
                except ValueError:
                    if not any(resolved.relative_to(ro) is not None or True
                               for ro in (readonly_roots or set())
                               if _is_under(resolved, ro)):
                        continue
            except (OSError, RuntimeError):
                continue
        _walk(base, child, depth - (1 if child.is_dir() else 0), lines,
              site_root, readonly_roots)


def _is_under(p: Path, root: Path) -> bool:
    """True if p is under root."""
    try:
        p.relative_to(root)
        return True
    except ValueError:
        return False


# ── Usage tracker ────────────────────────────────────────────────

class UsageTracker:
    """Cumulative token and cost tracker.  One per build, no global state."""
    __slots__ = ("calls", "input_tokens", "output_tokens", "cost_usd", "by_rule", "model")

    def __init__(self) -> None:
        self.calls = 0
        self.input_tokens = 0
        self.output_tokens = 0
        self.cost_usd = 0.0
        self.by_rule: dict[str, dict[str, Any]] = {}
        self.model: str | None = None

    def track(self, response: Any, rule: str | None = None) -> None:
        """Accumulate usage from a litellm response."""
        u = response.usage
        inp, out = u.prompt_tokens or 0, u.completion_tokens or 0
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
                "calls": 0, "input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0})
            s["calls"] += 1
            s["input_tokens"] += inp
            s["output_tokens"] += out
            s["cost_usd"] += cost

    def snapshot(self) -> dict[str, Any]:
        """Return copy of cumulative usage stats."""
        return {"calls": self.calls, "input_tokens": self.input_tokens,
                "output_tokens": self.output_tokens, "cost_usd": round(self.cost_usd, 6),
                "by_rule": dict(self.by_rule), "model": self.model}


# ── LLM wrapper (lazy litellm) ──────────────────────────────────

DEFAULT_MODEL: str = "anthropic/claude-haiku-4-5-20251001"


def _litellm():
    """Lazy import of litellm."""
    try:
        import litellm
        return litellm
    except ModuleNotFoundError:
        raise ModuleNotFoundError(
            "litellm is required for live oracle calls. "
            "Install it with: pip install litellm"
        ) from None


def compute_config_hash(model: str, max_tokens: int,
                        temperature: float | None = None,
                        tools: list[dict] | None = None) -> str:
    """Deterministic SHA-256 of oracle config for provenance."""
    config: dict[str, Any] = {"backend": "litellm", "model": model, "max_tokens": max_tokens}
    if temperature is not None:
        config["temperature"] = temperature
    if tools:
        config["tools"] = sorted(t.get("function", {}).get("name", "") for t in tools)
    return hashlib.sha256(json.dumps(config, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def compute_prompt_hash(prompt: str) -> str:
    """Deterministic SHA-256 of prompt content."""
    return hashlib.sha256(prompt.encode("utf-8")).hexdigest()


def llm_call(prompt: str, *, model: str = DEFAULT_MODEL, max_tokens: int = 1024,
             system: str | None = None, tools: list[dict] | None = None,
             temperature: float | None = None, tracker: UsageTracker | None = None,
             params: dict[str, Any] | None = None, router: Any | None = None) -> Any:
    """Single-shot LLM call.  Returns litellm response."""
    msgs: list[dict[str, Any]] = []
    if system:
        msgs.append({"role": "system", "content": system})
    msgs.append({"role": "user", "content": prompt})
    kwargs: dict[str, Any] = {**(params or {})}
    kwargs.update({"model": model, "max_tokens": max_tokens, "messages": msgs})
    if tools:
        kwargs["tools"] = tools
    if temperature is not None:
        kwargs["temperature"] = temperature
    r = router.completion(**kwargs) if router else _litellm().completion(**kwargs)
    if tracker:
        tracker.track(r)
    return r


def llm_call_messages(messages: list[dict[str, Any]], *, model: str = DEFAULT_MODEL,
                      max_tokens: int = 4096, system: str | None = None,
                      tools: list[dict] | None = None, temperature: float | None = None,
                      rule: str | None = None, tracker: UsageTracker | None = None,
                      params: dict[str, Any] | None = None, router: Any | None = None) -> Any:
    """Multi-turn LLM call with pre-built messages.  Returns litellm response."""
    msgs = list(messages)
    if system:
        msgs.insert(0, {"role": "system", "content": system})
    kwargs: dict[str, Any] = {**(params or {})}
    kwargs.update({"model": model, "max_tokens": max_tokens, "messages": msgs})
    if tools:
        kwargs["tools"] = tools
    if temperature is not None:
        kwargs["temperature"] = temperature
    r = router.completion(**kwargs) if router else _litellm().completion(**kwargs)
    if tracker:
        tracker.track(r, rule=rule)
    return r


def llm_meta(response: Any) -> dict[str, Any]:
    """Extract metadata from a litellm response."""
    msg = response.choices[0].message
    u = response.usage
    try:
        cost = _litellm().completion_cost(completion_response=response)
    except Exception:
        cost = 0.0
    return {"model": response.model, "input_tokens": u.prompt_tokens or 0,
            "output_tokens": u.completion_tokens or 0,
            "finish_reason": response.choices[0].finish_reason,
            "cost_usd": round(cost, 6), "text": msg.content or ""}


# ── Kernel: response parsing ────────────────────────────────────

MAX_TOOL_OUTPUT: int = 8000


def _truncate(s: str) -> str:
    return s[:MAX_TOOL_OUTPUT] + "\n\n[... truncated ...]" if len(s) > MAX_TOOL_OUTPUT else s


def parse_response(r: Any) -> dict[str, Any]:
    """Extract actionable blocks from litellm response.

    Returns dict with type: "act", "acts", "stop", or "say".
    """
    msg = r.choices[0].message
    tc = getattr(msg, "tool_calls", None)
    if tc and len(tc) > 1:
        calls = []
        for call in tc:
            fn = call.function
            name = fn.name.replace("_", "-")
            try:
                args = json.loads(fn.arguments or "{}")
            except Exception:
                args = {}
            calls.append({"tool": name, "args": args, "tool_call_id": call.id})
        return {"type": "acts", "calls": calls}
    if tc and len(tc) == 1:
        call = tc[0]
        fn = call.function
        name = fn.name.replace("_", "-")
        try:
            args = json.loads(fn.arguments or "{}")
        except Exception:
            args = {}
        return {"type": "act", "tool": name, "args": args, "tool_call_id": call.id}
    if r.choices[0].finish_reason == "stop":
        return {"type": "stop", "value": msg.content or ""}
    return {"type": "say", "text": msg.content or ""}


# ── Kernel: message building ────────────────────────────────────

def _build_messages(C: dict[str, Any]) -> list[dict[str, Any]]:
    """Build OpenAI messages from initial prompt + trace."""
    msgs: list[dict[str, Any]] = [
        {"role": "user", "content": C.get("prompt", "Run the task.")}
    ]
    for event in C.get("trace", []):
        form = event.get("form", {})
        kind = form.get("type", "")
        if kind == "act":
            tid = form.get("tool_call_id", "t0")
            fn_name = event.get("tool", "unknown").replace("-", "_")
            msgs.append({"role": "assistant", "content": None, "tool_calls": [{
                "id": tid, "type": "function",
                "function": {"name": fn_name, "arguments": json.dumps(form.get("args", {}))},
            }]})
            out = event.get("out", "")
            msgs.append({"role": "tool", "tool_call_id": tid,
                         "content": _truncate(out if isinstance(out, str) else json.dumps(out, default=str))})
        elif kind == "acts":
            calls_data, results = event.get("calls", []), event.get("results", [])
            tc_arr = [{"id": cd.get("tool_call_id", "t0"), "type": "function",
                       "function": {"name": cd["tool"].replace("-", "_"),
                                    "arguments": json.dumps(cd.get("args", {}))}}
                      for cd in calls_data]
            msgs.append({"role": "assistant", "content": None, "tool_calls": tc_arr})
            for cd, res in zip(calls_data, results):
                out = res if isinstance(res, str) else json.dumps(res, default=str)
                msgs.append({"role": "tool", "tool_call_id": cd.get("tool_call_id", "t0"),
                             "content": _truncate(out)})
    return msgs


# ── Kernel: context helpers ──────────────────────────────────────

def _rebind(C: dict[str, Any], event: dict[str, Any]) -> dict[str, Any]:
    """Return new context with event appended to trace."""
    return {**C, "trace": C.get("trace", []) + [event]}


def _allowed(C: dict[str, Any], tool_name: str) -> bool:
    """True if tool_name is in the context's tool allowlist."""
    return tool_name in C.get("tools", [])


def _dispatch_context(C: dict[str, Any]) -> dict[str, Any]:
    """Build kwargs for dispatch() from kernel context."""
    ctx: dict[str, Any] = {}
    sr, ro = C.get("site_root"), C.get("readonly_roots")
    if sr is not None or ro is not None:
        ctx["context"] = {}
        if sr is not None:
            ctx["context"]["site_root"] = sr
        if ro is not None:
            ctx["context"]["readonly_roots"] = ro
    return ctx


# ── Kernel: LLM invocation ──────────────────────────────────────

def invoke_llm(C: dict[str, Any]) -> dict[str, Any]:
    """Call the LLM with current context.  Returns parsed response."""
    msgs = _build_messages(C)
    tool_schemas = C.get("tool-defs", [])
    kwargs: dict[str, Any] = {
        "model": C.get("model", DEFAULT_MODEL),
        "max_tokens": C.get("max-tokens", 4096),
        "rule": C.get("rule"),
        "params": C.get("params"),
        "router": C.get("router"),
    }
    tracker = C.get("tracker")
    if tracker is not None:
        kwargs["tracker"] = tracker
    system = C.get("system")
    if system:
        kwargs["system"] = system
    if tool_schemas:
        kwargs["tools"] = tool_schemas
    r = llm_call_messages(msgs, **kwargs)
    return parse_response(r)


# ── Kernel: agentic loop ────────────────────────────────────────

def step(M: Callable[[dict], dict], C: dict[str, Any], fuel: int) -> dict[str, Any]:
    """Run agentic loop iteratively until stop or fuel exhaustion.

    M: LLM invocation function (context -> parsed response).
    Returns dict with type, C, fuel_steps, and type-specific fields.
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
            return {"type": "say", "text": form.get("text"), "C": C, "fuel_steps": fuel_used}
        if kind == "stop":
            return {"type": "stop", "value": form.get("value", C), "C": C, "fuel_steps": fuel_used}

        if kind == "act":
            name, args = form.get("tool"), form.get("args", {})
            if not _allowed(C, name):
                return {"type": "error", "error": f"{name} not in scope", "C": C, "fuel_steps": fuel_used}
            ctx = _dispatch_context(C)
            out = dispatch(name, args, **ctx)
            C = _rebind(C, {"form": form, "tool": name, "out": out})
            fuel -= 1
            fuel_used += 1
            continue

        if kind == "acts":
            calls = form.get("calls", [])
            results = []
            for i, cd in enumerate(calls):
                if fuel <= 0:
                    C = _rebind(C, {"form": form, "calls": calls[:i], "results": results})
                    return {"type": "halt", "C": C, "fuel_steps": fuel_used}
                name, args = cd["tool"], cd.get("args", {})
                if not _allowed(C, name):
                    return {"type": "error", "error": f"{name} not in scope", "C": C, "fuel_steps": fuel_used}
                ctx = _dispatch_context(C)
                out = dispatch(name, args, **ctx)
                results.append(out)
                fuel -= 1
                fuel_used += 1
            C = _rebind(C, {"form": form, "calls": calls, "results": results})
            continue

        return {"type": "error", "error": f"bad form: {form}", "C": C, "fuel_steps": fuel_used}


def agent(C: dict[str, Any], *, fuel: int = 8,
          M: Callable[[dict], dict] | None = None) -> dict[str, Any]:
    """Run the agentic kernel.  C must have prompt and tools."""
    if M is None:
        M = invoke_llm
    tool_names = C.get("tools", [])
    tool_defs = schemas(tool_names)
    C0 = {"trace": [], "tool-defs": tool_defs, **C}
    return step(M, C0, fuel)


# ── LiteLLMBackend ───────────────────────────────────────────────

def _resolve_config(config: dict[str, Any], rule_name: str) -> dict[str, Any]:
    """Merge per-rule override over base config.

    One-level deep merge: if both base and override have a dict value for the
    same key (e.g. ``params``), the dicts are merged instead of replaced.
    """
    override = config.get("per_rule", {}).get(rule_name, {})
    merged = {**config, **override}
    for key, val in override.items():
        if isinstance(val, dict) and isinstance(config.get(key), dict):
            merged[key] = {**config[key], **val}
    return merged


class LiteLLMBackend:
    """LiteLLM agent loop backend.  Owns the loop, enforces allowlist+fuel in-process."""
    name = "litellm"

    def run(self, S: dict[str, Any], rule_name: str, recipe: dict[str, Any],
            outputs: list[str], config: dict[str, Any]) -> RealizedCost:
        site = str(site_of(S))
        prompt = recipe.get("prompt", "")
        tool_names = recipe.get("tools", DEFAULT_TOOLS)
        fuel = recipe.get("fuel", 8)

        rc = _resolve_config(config, rule_name)
        model = rc.get("model", DEFAULT_MODEL)
        params = rc.get("params") or {}
        router = rc.get("router")

        site_root = Path(site).resolve()
        ro_roots = readonly_roots_of(S)
        tracker = UsageTracker()
        system = build_system_prompt(site, outputs)

        result = agent(
            {"prompt": prompt, "tools": tool_names, "system": system,
             "model": model, "params": params, "router": router,
             "rule": rule_name, "tracker": tracker,
             "site_root": site_root, "readonly_roots": ro_roots},
            fuel=fuel,
        )
        _raise_unless_stop(result)

        snap = tracker.snapshot()
        return RealizedCost(
            tokens_in=snap["input_tokens"], tokens_out=snap["output_tokens"],
            cost_usd=snap["cost_usd"], fuel_steps=result.get("fuel_steps", 0),
        )


def _raise_unless_stop(result: dict[str, Any]) -> None:
    """Raise on non-clean termination.  Only clean stop seals."""
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
        raise RuntimeError(f"oracle agent produced text without stopping: {result.get('text', '')[:100]}")
    raise RuntimeError(f"oracle agent returned unexpected type: {t}")


# ── ClaudeCodeBackend ────────────────────────────────────────────

CC_TOOL_MAP: dict[str, str] = {
    "read-file": "Read", "write-file": "Write", "list-dir": "Glob", "tree": "Glob",
}
_CC_PATH_KEYS = ("file_path", "path", "notebook_path")


class _Gate:
    """Per-invocation tool interceptor: allowlist + fuel + sandbox."""
    __slots__ = ("allowed", "fuel", "site_root", "readonly_roots", "steps", "exhausted")

    def __init__(self, allowed: set[str], fuel: int, site_root: Path, readonly_roots: set[Path]):
        self.allowed, self.fuel = allowed, fuel
        self.site_root, self.readonly_roots = site_root, readonly_roots
        self.steps, self.exhausted = 0, False

    def _in_bounds(self, raw: str) -> bool:
        if ".." in Path(raw).parts:
            return False
        p = (self.site_root / raw).resolve() if not Path(raw).is_absolute() else Path(raw).resolve()
        roots = {self.site_root, *self.readonly_roots}
        return any(p == r or r in p.parents for r in roots)

    def decide(self, tool_name: str, tool_input: dict[str, Any]) -> tuple[bool, str]:
        """Return (allow, reason)."""
        if tool_name not in self.allowed:
            return False, f"{tool_name} not in scope"
        for k in _CC_PATH_KEYS:
            v = tool_input.get(k)
            if isinstance(v, str) and v and not self._in_bounds(v):
                return False, f"path escapes site: {v}"
        if self.steps >= self.fuel:
            self.exhausted = True
            return False, "out of fuel"
        self.steps += 1
        return True, ""


class ClaudeCodeBackend:
    """Claude Code Agent SDK backend.  Delegates loop to SDK, enforces via can_use_tool."""
    name = "claude-code"

    def run(self, S: dict[str, Any], rule_name: str, recipe: dict[str, Any],
            outputs: list[str], config: dict[str, Any]) -> RealizedCost:
        import asyncio

        sr = site_of(S)
        ro = readonly_roots_of(S)
        prompt = recipe.get("prompt", "")
        husk_tools = recipe.get("tools", DEFAULT_TOOLS)
        fuel = recipe.get("fuel", 8)

        rc = _resolve_config(config, rule_name)
        tmap = {**CC_TOOL_MAP, **rc.get("tool_map", {})}
        allowed_cc = {tmap[t] for t in husk_tools if t in tmap}
        unmapped = [t for t in husk_tools if t not in tmap]
        if unmapped:
            raise RuntimeError(f"no Claude Code mapping for husk tools: {unmapped}")

        gate = _Gate(allowed_cc, fuel, sr, ro)
        system = build_system_prompt(str(sr), outputs)

        saved_cc = os.environ.pop("CLAUDECODE", None)
        try:
            cost = asyncio.run(self._run_async(prompt, system, allowed_cc, fuel, gate, rc, sr))
        finally:
            if saved_cc is not None:
                os.environ["CLAUDECODE"] = saved_cc

        if gate.exhausted:
            raise RuntimeError("oracle agent ran out of fuel")
        cost["fuel_steps"] = gate.steps
        return cost

    async def _run_async(self, prompt: str, system: str, allowed_cc: set[str],
                         fuel: int, gate: _Gate, rc: dict[str, Any],
                         site_root: Path) -> RealizedCost:
        from claude_code_sdk import (
            query, ClaudeCodeOptions, PermissionResultAllow,
            PermissionResultDeny, ResultMessage, ToolPermissionContext,
        )

        async def can_use_tool(tool_name, tool_input, ctx: ToolPermissionContext):
            allow, reason = gate.decide(tool_name, tool_input)
            return PermissionResultAllow() if allow else PermissionResultDeny(message=reason)

        async def _prompt_stream():
            yield {"type": "user", "message": {
                "role": "user", "content": [{"type": "text", "text": prompt}]}}

        options = ClaudeCodeOptions(
            system_prompt=system, allowed_tools=sorted(allowed_cc),
            max_turns=fuel, permission_mode=rc.get("permission", "default"),
            can_use_tool=can_use_tool, cwd=str(site_root), **rc.get("options", {}))
        if "model" in rc:
            options.model = rc["model"]

        tokens_in = tokens_out = 0
        cost_usd = 0.0
        async for message in query(prompt=_prompt_stream(), options=options):
            if isinstance(message, ResultMessage):
                cost_usd = float(getattr(message, "total_cost_usd", 0.0) or 0.0)
                usage = getattr(message, "usage", None)
                if usage is not None:
                    tokens_in = int(getattr(usage, "input_tokens", 0) or 0)
                    tokens_out = int(getattr(usage, "output_tokens", 0) or 0)
                subtype = getattr(message, "subtype", "")
                if subtype and subtype != "success" and not gate.exhausted:
                    raise RuntimeError(f"claude-code oracle terminated: {subtype}")

        return RealizedCost(tokens_in=tokens_in, tokens_out=tokens_out,
                            cost_usd=cost_usd, fuel_steps=gate.steps)


# ── Dispatcher ───────────────────────────────────────────────────

def run_oracle(S: dict[str, Any], rule_name: str,
               recipe: dict[str, Any], outputs: list[str]) -> RealizedCost:
    """Build-facing entry point.  Selects backend from S["oracle-backend-name"].

    Per-rule ``backend`` override: if the resolved config for a rule contains a
    ``backend`` key, that backend is used instead of the global one.
    """
    name = S.get("oracle-backend-name", "litellm")
    config = dict(S.get("oracle-config", {}))
    rc = _resolve_config(config, rule_name)
    name = rc.pop("backend", name)
    return get_backend(name).run(S, rule_name, recipe, outputs, config)
