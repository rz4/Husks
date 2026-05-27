"""
events.py -- Structured event stream for Husks build tracing.

This module is the observation backbone.  Every significant build event
(rule fired, oracle called, tool dispatched, trial scored) is captured
as a timestamped dict and appended to a JSONL backing store.  The event
stream is the single source of truth for post-build analysis, cost
reporting, and rendering.

Architecture
------------
The module maintains per-build state in a ``BuildTrace`` instance.
Callers emit events through the instance methods; the instance
accumulates structured records and per-category rollups.

The event stream is pure data -- no formatting, no ANSI, no I/O.
Rendering is the sole responsibility of the console module, which
subscribes to events via the listener protocol.

Listener protocol
-----------------
A listener is any object with a ``notify(event: dict)`` method.
After each event is recorded, all registered listeners are notified
with the event dict.  The console renderer is one such listener.

Event schema
------------
Every event dict has at minimum::

    {"event": str, "ts": float}

Additional keys depend on the event type:

  build_start    name, fuel, site
  build_end      status, fuel_left, elapsed
  rule_start     rule, stale_reason
  rule_done      rule, elapsed
  rule_sealed    rule, reused_by
  rule_halted    rule, reason, elapsed
  oracle_start   rule, oracle
  oracle_done    rule, oracle, tokens_in, tokens_out, cost_usd, elapsed
  tool_call      rule, tool, args
  tool_result    tool, result_preview
  trial_branch   rule, branch, score, tokens_in, tokens_out, cost_usd, elapsed
  trial_note     rule, message
  trial_verdict  rule, winner, scores
  sealed_manifest  artifacts

Interface with husks
-------------------------
Depends only on the standard library.

Consumed by:

  build.py         -- emits events during evaluation.
  oracle/kernel.py -- emits tool_call and tool_result events.
  utils/console.py -- listens to events for ANSI rendering.
  cli.py           -- calls to_jsonl() / to_dict() for export.
"""

from __future__ import annotations

import json
import time
from typing import Any, Protocol, runtime_checkable


# -- Listener protocol -------------------------------------------------------

@runtime_checkable
class TraceListener(Protocol):
    """Any object that can receive event notifications."""

    def notify(self, event: dict[str, Any]) -> None: ...


# -- BuildTrace --------------------------------------------------------------

class BuildTrace:
    """Accumulates structured events for a single build invocation.

    All event methods are safe to call at any time.  If no build has
    started, events are still recorded (with ts=0.0 for elapsed
    computations).

    Typical lifecycle::

        t = BuildTrace()
        t.add_listener(console_renderer)
        t.build_start("my-build", fuel=10, site="/tmp/site")
        ...
        t.build_end("committed", fuel_left=7, fuel_total=10)
        print(t.to_jsonl())
    """

    __slots__ = (
        "_events", "_listeners",
        "_build_name", "_build_fuel", "_build_t0",
        "_rule_timers", "_rule_stack",
        "_node_events", "_oracle_events", "_tool_events",
        "_artifacts",
    )

    def __init__(self) -> None:
        self._events: list[dict[str, Any]] = []
        self._listeners: list[TraceListener] = []

        self._build_name: str = ""
        self._build_fuel: int = 0
        self._build_t0: float = 0.0

        self._rule_timers: dict[str, float] = {}
        self._rule_stack: list[str] = []
        self._node_events: list[tuple[str, str, float]] = []
        self._oracle_events: list[tuple[str, str, int, int, float, float]] = []
        self._tool_events: list[tuple[str, str, str, str | None, dict]] = []
        self._artifacts: dict[str, dict[str, str]] = {}

    # -- Listener management --------------------------------------------------

    def add_listener(self, listener: TraceListener) -> None:
        """Register a listener to receive event notifications."""
        self._listeners.append(listener)

    def remove_listener(self, listener: TraceListener) -> None:
        """Remove a previously registered listener."""
        self._listeners = [l for l in self._listeners if l is not listener]

    def clear_listeners(self) -> None:
        """Remove all registered listeners."""
        self._listeners.clear()

    # -- State management -----------------------------------------------------

    def clear(self) -> None:
        """Reset internal state while preserving listener registrations.

        This mutates the existing instance in place so that aliases
        (``from husks.utils import trace as T``) stay valid after a reset.
        """
        self._events.clear()
        self._build_name = ""
        self._build_fuel = 0
        self._build_t0 = 0.0
        self._rule_timers.clear()
        self._rule_stack.clear()
        self._node_events.clear()
        self._oracle_events.clear()
        self._tool_events.clear()
        self._artifacts.clear()

    # -- Internal -------------------------------------------------------------

    def _emit(self, event: dict[str, Any]) -> None:
        """Timestamp, store, and broadcast an event."""
        event["ts"] = time.time()
        self._events.append(event)
        for listener in self._listeners:
            listener.notify(event)

    def _parent(self) -> str | None:
        return self._rule_stack[-1] if self._rule_stack else None

    # -- Build events ---------------------------------------------------------

    def build_start(
        self,
        name: str,
        fuel: int,
        site: str,
        oracle_model: str | None = None,
    ) -> None:
        """Record the start of a build."""
        self._build_name = name
        self._build_fuel = fuel
        self._build_t0 = time.time()
        self._emit({
            "event": "build_start",
            "name": name,
            "fuel": fuel,
            "site": site,
            "oracle_model": oracle_model,
        })

    def build_end(
        self,
        status: str,
        fuel_left: int,
        fuel_total: int,
    ) -> None:
        """Record the end of a build."""
        elapsed = time.time() - self._build_t0
        self._emit({
            "event": "build_end",
            "status": status,
            "fuel_left": fuel_left,
            "fuel_total": fuel_total,
            "elapsed": elapsed,
            # Embed summary data so listeners can render without
            # reaching back into the trace object.
            "node_events": list(self._node_events),
            "oracle_events": list(self._oracle_events),
            "tool_events_count": len(self._tool_events),
            "artifacts": dict(self._artifacts),
        })

    # -- Rule events ----------------------------------------------------------

    def push_rule(self, name: str) -> None:
        """Track parent rule for diamond annotations."""
        self._rule_stack.append(name)

    def pop_rule(self) -> None:
        """Pop the current rule from the parent stack."""
        if self._rule_stack:
            self._rule_stack.pop()

    def rule_start(self, name: str, stale_reason: str | None = None) -> None:
        """Record that a rule has started firing."""
        self._rule_timers[name] = time.time()
        self._emit({
            "event": "rule_start",
            "rule": name,
            "stale_reason": stale_reason,
        })

    def rule_done(
        self,
        name: str,
        outputs: list[str] | None = None,
        output_hashes: list[str] | None = None,
    ) -> None:
        """Record that a rule fired successfully."""
        el = time.time() - self._rule_timers.pop(name, time.time())
        self._node_events.append((name, "fired", el))
        if outputs and output_hashes:
            for o, h in zip(outputs, output_hashes):
                self._artifacts[o] = {
                    "hash": h, "rule": name, "status": "produced",
                }
        self._emit({"event": "rule_done", "rule": name, "elapsed": el})

    def rule_sealed(
        self,
        name: str,
        outputs: list[str] | None = None,
        output_hashes: list[str] | None = None,
    ) -> None:
        """Record that a rule was sealed (outputs reused)."""
        parent = self._parent()
        self._node_events.append((name, "reused", 0.0))
        if outputs and output_hashes:
            for o, h in zip(outputs, output_hashes):
                if o not in self._artifacts:
                    self._artifacts[o] = {
                        "hash": h, "rule": name, "status": "sealed",
                    }
        self._emit({
            "event": "rule_sealed",
            "rule": name,
            "reused_by": parent,
        })

    def rule_halted(self, name: str, reason: str) -> None:
        """Record that a rule was halted (failed)."""
        el = time.time() - self._rule_timers.pop(name, time.time())
        self._node_events.append((name, "failed", el))
        self._emit({
            "event": "rule_halted",
            "rule": name,
            "reason": reason,
            "elapsed": el,
        })

    # -- Oracle events --------------------------------------------------------

    def oracle_start(
        self,
        rule_name: str,
        oracle_name: str | None = None,
        prompt: str | None = None,
    ) -> None:
        """Record the start of an oracle invocation."""
        label = oracle_name or "oracle"
        self._emit({
            "event": "oracle_start",
            "rule": rule_name,
            "oracle": label,
            "prompt_preview": prompt[:50] if prompt else None,
        })

    def oracle_done(
        self,
        rule_name: str,
        oracle_name: str | None = None,
        tokens_in: int = 0,
        tokens_out: int = 0,
        cost_usd: float = 0.0,
        elapsed: float = 0.0,
    ) -> None:
        """Record the completion of an oracle invocation."""
        label = oracle_name or "oracle"
        self._oracle_events.append(
            (rule_name, label, tokens_in, tokens_out, cost_usd, elapsed)
        )
        self._emit({
            "event": "oracle_done",
            "rule": rule_name,
            "oracle": label,
            "tokens_in": tokens_in,
            "tokens_out": tokens_out,
            "cost_usd": cost_usd,
            "elapsed": elapsed,
        })

    # -- Tool events ----------------------------------------------------------

    def tool_call(
        self,
        rule_name: str,
        name: str,
        args: dict[str, Any],
    ) -> None:
        """Record a tool call dispatched by the kernel."""
        args_str = str(args)
        if len(args_str) > 80:
            args_str = args_str[:77] + "..."
        self._tool_events.append((rule_name, name, args_str, None, args))
        self._emit({
            "event": "tool_call",
            "rule": rule_name,
            "tool": name,
            "args": args,
        })

    def tool_result(self, name: str, result: Any) -> None:
        """Record a tool result."""
        out_str = str(result)
        if len(out_str) > 120:
            out_str = out_str[:117] + "..."
        # Update last matching tool event with result.
        for i in range(len(self._tool_events) - 1, -1, -1):
            if self._tool_events[i][1] == name and self._tool_events[i][3] is None:
                self._tool_events[i] = (
                    *self._tool_events[i][:3], out_str, self._tool_events[i][4],
                )
                break
        self._emit({
            "event": "tool_result",
            "tool": name,
            "result_preview": out_str,
        })

    # -- Trial events ---------------------------------------------------------

    def trial_branch(
        self,
        rule_name: str,
        branch_name: str,
        score: float | None = None,
        tokens_in: int = 0,
        tokens_out: int = 0,
        cost_usd: float = 0.0,
        elapsed: float = 0.0,
    ) -> None:
        """Record a trial branch result."""
        self._emit({
            "event": "trial_branch",
            "rule": rule_name,
            "branch": branch_name,
            "score": score,
            "tokens_in": tokens_in,
            "tokens_out": tokens_out,
            "cost_usd": cost_usd,
            "elapsed": elapsed,
        })

    def trial_note(self, rule_name: str, message: str) -> None:
        """Record a lightweight informational event for trial-level decisions."""
        self._emit({
            "event": "trial_note",
            "rule": rule_name,
            "message": message,
        })

    def trial_verdict(
        self,
        rule_name: str,
        winner_name: str,
        scores: dict[str, float] | None = None,
    ) -> None:
        """Record the verdict of a trial."""
        self._emit({
            "event": "trial_verdict",
            "rule": rule_name,
            "winner": winner_name,
            "scores": scores,
        })

    # -- Sealed manifest ------------------------------------------------------

    def sealed_manifest(self) -> None:
        """Emit the final sealed artifact manifest."""
        if not self._artifacts:
            return
        self._emit({
            "event": "sealed_manifest",
            "artifacts": {
                p: {"hash": a["hash"], "rule": a["rule"]}
                for p, a in self._artifacts.items()
            },
        })

    # -- Export ---------------------------------------------------------------

    def to_jsonl(self) -> str:
        """Return the full event stream as a JSONL string."""
        return (
            "\n".join(json.dumps(e, default=str) for e in self._events)
            + "\n"
        )

    def to_dict(self) -> dict[str, Any]:
        """Return a summary dict suitable for JSON serialization."""
        elapsed = time.time() - self._build_t0 if self._build_t0 else 0
        return {
            "build": self._build_name,
            "fuel_total": self._build_fuel,
            "elapsed_s": round(elapsed, 4),
            "events": list(self._events),
            "nodes": [
                {"name": n, "status": s, "elapsed_s": round(e, 4)}
                for n, s, e in self._node_events
            ],
            "artifacts": dict(self._artifacts),
            "totals": {
                "nodes_fired": sum(
                    1 for _, s, _ in self._node_events if s == "fired"
                ),
                "nodes_reused": sum(
                    1 for _, s, _ in self._node_events if s == "reused"
                ),
                "nodes_failed": sum(
                    1 for _, s, _ in self._node_events if s == "failed"
                ),
                "tool_calls": len(self._tool_events),
                "oracle_calls": len(self._oracle_events),
                "tokens_in": sum(e[2] for e in self._oracle_events),
                "tokens_out": sum(e[3] for e in self._oracle_events),
                "cost_usd": round(
                    sum(e[4] for e in self._oracle_events), 6
                ),
            },
        }
