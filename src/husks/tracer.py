"""L7 tracer -- Tool-stream observer that drafts candidate designs.

The tracer accumulates tool events from an exploration session (file reads,
file writes, bash commands) and drafts a candidate design dict suitable for
gamma.condense().  The tracer has zero authority: its output is validated
only by re-derivation through condense(), never asserted directly.

Dependencies: locke (L5) for check() validation + stdlib.
"""

from __future__ import annotations

from typing import Any


class Tracer:
    """Accumulates tool events and drafts a candidate design."""

    def __init__(self, name: str = "traced"):
        self._name = name
        self._events: list[dict] = []

    def record(self, event: dict) -> None:
        """Record a single tool event.

        Events have:
        - type: "read", "write", or "bash"
        - path: for read/write events
        - cmd: for bash events
        - reads/writes: optional explicit I/O lists for bash events
        """
        if "type" not in event:
            raise ValueError("event must have a 'type' field")
        etype = event["type"]
        if etype not in ("read", "write", "bash"):
            raise ValueError(f"unknown event type: {etype!r}")
        self._events.append(dict(event))

    def draft(self, accepted_outputs: list[str] | None = None) -> dict:
        """Draft a candidate design from recorded events.

        Returns a design dict ready for gamma.condense().
        The draft is never authoritative -- the caller must pass it
        through condense() for validation by re-derivation.
        """
        if not self._events:
            return {"name": self._name, "fuel": 1, "rules": [], "target": ""}

        produced: set[str] = set()       # files produced by prior rules
        site_inputs: dict[str, str] = {} # files read but never produced
        rules: list[dict[str, Any]] = []
        rule_counter = 0

        for ev in self._events:
            etype = ev["type"]

            if etype == "read":
                path = ev["path"]
                if path not in produced:
                    site_inputs[path] = path

            elif etype == "write":
                produced.add(ev["path"])

            elif etype == "bash":
                cmd = ev["cmd"]
                reads = list(ev.get("reads", []))
                writes = list(ev.get("writes", []))

                # Track reads as site_inputs if not already produced
                for r in reads:
                    if r not in produced:
                        site_inputs[r] = r

                if writes:
                    rule_counter += 1
                    rname = f"step{rule_counter}"
                    # Inputs = reads that exist before this command
                    inputs = []
                    for r in reads:
                        if r in produced or r in site_inputs:
                            inputs.append(r)
                    rules.append({
                        "name": rname,
                        "kind": "action",
                        "inputs": inputs,
                        "outputs": writes,
                        "run": cmd,
                    })
                    for w in writes:
                        produced.add(w)

        # Filter to only rules contributing to accepted_outputs
        if accepted_outputs is not None and rules:
            needed_files = set(accepted_outputs)
            needed_rules: list[dict] = []
            # Walk backwards to find contributing rules
            for rule in reversed(rules):
                if any(o in needed_files for o in rule["outputs"]):
                    needed_rules.append(rule)
                    needed_files.update(rule["inputs"])
            rules = list(reversed(needed_rules))

            # Prune site_inputs to only those needed
            all_rule_inputs = {i for r in rules for i in r["inputs"]}
            site_inputs = {k: v for k, v in site_inputs.items()
                           if k in all_rule_inputs}

        target = rules[-1]["name"] if rules else ""
        fuel = len(self._events) + len(rules) + 5  # conservative margin

        design: dict[str, Any] = {
            "name": self._name,
            "fuel": fuel,
            "target": target,
            "rules": rules,
        }
        if site_inputs:
            design["site_inputs"] = site_inputs

        # Validate with locke.check() -- return design regardless
        # (let condense handle errors via re-derivation)
        try:
            from husks.locke import check
            check(design)
        except Exception:
            pass

        return design
