"""
claude_code.py -- Claude Code Agent SDK oracle 
Does NOT use kernel.py.  Claude Code owns its own agent loop and tool
protocol; this backend hands one oracle rule to one SDK ``query()`` call
and never sees the inner loop.  Every constraint the kernel enforced
in-process is re-established at the tool boundary through a
``can_use_tool`` interceptor that this backend owns:

  - allowlist : deny any tool not in the per-rule mapped set.
  - fuel      : count each permitted tool call; deny + flag once the
                count reaches recipe["fuel"].  A step is one tool call,
                matching kernel.step exactly.  max_turns is set as a
                coarse backstop only -- it counts turns, not steps, and
                the subagent-frontmatter path is known-unenforced
                (claude-code issue #41143), so the counter is the source
                of truth.
  - sandbox   : deny any path argument that escapes the site (or a
                declared readonly root).  This replaces tools.set_site_root,
                which the SDK does not honor.

One oracle rule -> one query() -> one fresh context.  We rely on the
top-level query max_turns (the enforced one), NOT subagent-frontmatter
maxTurns.

Config  (S["oracle-config"], every field optional)
--------------------------------------------------
  model        : str   -- model id for the SDK session.
  permission   : str   -- SDK permission mode.  Default "default" so the
                          can_use_tool callback is consulted.  Do not use
                          a bypass mode; it would skip the gate.
  options      : dict  -- opaque pass-through to ClaudeAgentOptions for
                          power users (cwd, env, mcp servers, effort,
                          setting_sources, ...).  allowed_tools,
                          max_turns, can_use_tool, and the agents tool
                          map are owned by this backend and overwritten.
  tool_map     : dict  -- override the husk->CC tool name mapping.
  per_rule     : dict[str, dict] -- {model, permission, options} keyed
                          by rule name.  Provenance only.

CONFIG NOTE: none of this enters the recipe digest.  A husk built under
litellm and resumed under claude-code busts no seals -- the recipe
(prompt, tools, fuel) is identical and the executor is not in the form.

SDK-SURFACE NOTE: the exact Python symbols below (query, ClaudeAgentOptions,
can_use_tool signature, ResultMessage fields, PermissionResult shape) must
be verified against the installed claude-agent-sdk version.  The points
that depend on the SDK surface are marked  # SDK:  inline.
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import Any

from husks.oracle.backend import (
    RealizedCost,
    site_of,
    DEFAULT_TOOLS,
    readonly_roots_of,
    build_system_prompt,
)


# -- husk tool namespace -> Claude Code tool namespace --------------
# tree has no 1:1 CC tool; Glob with a recursive pattern covers the
# same read-only "what is here" need.  Bash is deliberately absent:
# it is unsandboxable by name and would blow the allowlist open.

TOOL_MAP: dict[str, str] = {
    "read-file": "Read",
    "write-file": "Write",
    "list-dir": "Glob",
    "tree": "Glob",
}

# Tool-input keys that name a filesystem path and must be confined.
_PATH_KEYS = ("file_path", "path", "notebook_path")


class _FuelExhausted(Exception):
    """Raised internally when the step counter reaches the fuel bound."""


class _Gate:
    """Per-invocation tool interceptor: allowlist + fuel + sandbox.

    One instance per oracle rule.  Holds the step counter so fuel
    accounting is local to the run, mirroring kernel.step.
    """

    def __init__(
        self,
        allowed_cc_tools: set[str],
        fuel: int,
        site_root: Path,
        readonly_roots: set[Path],
    ) -> None:
        self.allowed = allowed_cc_tools
        self.fuel = fuel
        self.site_root = site_root
        self.readonly_roots = readonly_roots
        self.steps = 0
        self.exhausted = False

    def _in_bounds(self, raw: str) -> bool:
        if ".." in Path(raw).parts:
            return False
        # Relative paths resolve under the site; absolute paths must
        # already live under the site or a readonly root.
        p = (self.site_root / raw).resolve() if not Path(raw).is_absolute() \
            else Path(raw).resolve()
        roots = {self.site_root, *self.readonly_roots}
        return any(p == r or r in p.parents for r in roots)

    def decide(self, tool_name: str, tool_input: dict[str, Any]) -> tuple[bool, str]:
        """Return (allow, reason).  Pure; the caller maps to the SDK
        permission result shape."""
        if tool_name not in self.allowed:
            return False, f"{tool_name} not in scope"
        for k in _PATH_KEYS:
            v = tool_input.get(k)
            if isinstance(v, str) and v and not self._in_bounds(v):
                return False, f"path escapes site: {v}"
        if self.steps >= self.fuel:
            self.exhausted = True
            return False, "out of fuel"
        self.steps += 1
        return True, ""


def _resolve_config(config: dict[str, Any], rule_name: str) -> dict[str, Any]:
    override = config.get("per_rule", {}).get(rule_name, {})
    return {**config, **override}


class ClaudeCodeBackend:
    name = "claude-code"

    def run(
        self,
        S: dict[str, Any],
        rule_name: str,
        recipe: dict[str, Any],
        outputs: list[str],
        config: dict[str, Any],
    ) -> RealizedCost:
        site_root = backend.site_of(S)
        readonly_roots = backend.readonly_roots_of(S)
        prompt: str = recipe.get("prompt", "")
        husk_tools: list[str] = recipe.get("tools", backend.DEFAULT_TOOLS)
        fuel: int = recipe.get("fuel", 8)

        rc = _resolve_config(config, rule_name)
        tool_map = {**TOOL_MAP, **rc.get("tool_map", {})}
        allowed_cc = {tool_map[t] for t in husk_tools if t in tool_map}
        unmapped = [t for t in husk_tools if t not in tool_map]
        if unmapped:
            raise RuntimeError(
                f"no Claude Code mapping for husk tools: {unmapped}"
            )

        gate = _Gate(allowed_cc, fuel, site_root, readonly_roots)
        system = backend.build_system_prompt(str(site_root), outputs)

        # The Claude Code CLI refuses to start inside another Claude Code
        # session (detected via the CLAUDECODE env var).  Temporarily remove
        # it so the SDK subprocess can launch cleanly.
        saved_cc = os.environ.pop("CLAUDECODE", None)
        try:
            cost = asyncio.run(
                self._run_async(prompt, system, allowed_cc, fuel, gate, rc, site_root)
            )
        finally:
            if saved_cc is not None:
                os.environ["CLAUDECODE"] = saved_cc

        if gate.exhausted:
            raise RuntimeError("oracle agent ran out of fuel")
        cost["fuel_steps"] = gate.steps
        return cost

    async def _run_async(
        self,
        prompt: str,
        system: str,
        allowed_cc: set[str],
        fuel: int,
        gate: _Gate,
        rc: dict[str, Any],
        site_root: Path,
    ) -> RealizedCost:
        from claude_code_sdk import (
            query, ClaudeCodeOptions, PermissionResultAllow,
            PermissionResultDeny, ResultMessage, ToolPermissionContext,
        )

        async def can_use_tool(tool_name, tool_input, ctx: ToolPermissionContext):
            allow, reason = gate.decide(tool_name, tool_input)
            if allow:
                return PermissionResultAllow()
            return PermissionResultDeny(message=reason)

        # The SDK requires an AsyncIterable prompt when can_use_tool is set
        # (streaming mode).  Wrap the string in a single-message async generator.
        async def _prompt_stream():
            yield {
                "type": "user",
                "message": {
                    "role": "user",
                    "content": [{"type": "text", "text": prompt}],
                },
            }

        options = ClaudeCodeOptions(
            system_prompt=system,
            allowed_tools=sorted(allowed_cc),
            max_turns=fuel,
            permission_mode=rc.get("permission", "default"),
            can_use_tool=can_use_tool,
            cwd=str(site_root),
            **rc.get("options", {}),
        )
        if "model" in rc:
            options.model = rc["model"]

        tokens_in = tokens_out = 0
        cost_usd = 0.0
        async for message in query(prompt=_prompt_stream(), options=options):
            if isinstance(message, ResultMessage):
                subtype = getattr(message, "subtype", "")
                cost_usd = float(getattr(message, "total_cost_usd", 0.0) or 0.0)
                usage = getattr(message, "usage", None)
                if usage is not None:
                    tokens_in = int(getattr(usage, "input_tokens", 0) or 0)
                    tokens_out = int(getattr(usage, "output_tokens", 0) or 0)
                if subtype and subtype != "success":
                    if not gate.exhausted:
                        raise RuntimeError(
                            f"claude-code oracle terminated: {subtype}"
                        )

        return RealizedCost(
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            cost_usd=cost_usd,
            fuel_steps=gate.steps,
        )
