"""
CLI Residue models - shared intermediate representation for all commands.

Beta Gate 95: Command → Residue → Surface architecture.

All CLI commands (check, run, status) collect facts into CliResidue,
which is then dispatched to the surface layer (JSON or visual output).
This provides:
- One shared state model
- One visual DAG renderer
- One JSON surface with shared vocabulary
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class CliNode:
    """Represents a single node (rule) in CLI output.

    **State vocabulary (unified across check, run, status):**
    - dry: Node exists in design but hasn't run (check mode without site)
    - sealed: Previously built, inputs unchanged, outputs fresh
    - cached: Reused from cache with explicit evidence (cached=True flag)
    - stale: Recipe/inputs changed, or outputs missing/tampered
    - failed: Execution failed with diagnosis

    **Kind vocabulary:**
    - oracle: LLM-powered generative rule
    - action: Deterministic shell command
    - trial: Non-committing exploration (not in beta 95 scope)
    """

    name: str
    """Rule name"""

    kind: str
    """Rule kind: oracle, action, or trial"""

    state: str
    """Node state: dry, sealed, cached, stale, or failed"""

    fuel: Optional[int] = None
    """Fuel consumed by this node (None if not executed)"""

    cost: Optional[float] = None
    """USD cost for this node (None if not executed or zero-cost)"""

    cache: bool = False
    """True if node output was reused from cache (explicit evidence)"""

    output_hash: Optional[str] = None
    """Content hash of outputs (for verification)"""

    diagnosis: Optional[str] = None
    """Error message or halt reason (only for failed state)"""

    stale_reason: Optional[str] = None
    """Reason for staleness (e.g., 'input_changed:file.txt')"""

    # Additional metadata for verbose rendering
    duration: Optional[float] = None
    """Execution duration in seconds (only for run command)"""


@dataclass
class CliResidue:
    """Intermediate representation of CLI command state.

    All commands (check, run, status) collect their results into
    CliResidue, which is then formatted by the surface layer.
    """

    command: str
    """Command that produced this residue: check, run, or status"""

    design_name: str
    """Design name from design.json"""

    site: Optional[str]
    """Site directory path (None for check without --site)"""

    status: str
    """Build status: dry, committed, or halted"""

    root: Optional[str] = None
    """Build root hash (None if not committed)"""

    fuel_budget: int = 0
    """Total fuel budget from design"""

    fuel_used: int = 0
    """Fuel consumed by executed rules"""

    cost: float = 0.0
    """Total USD cost of oracle calls"""

    nodes: list[CliNode] = field(default_factory=list)
    """List of nodes (rules) in execution order"""

    passes: int = 0
    """Count of nodes in sealed or cached state"""

    fails: int = 0
    """Count of nodes in failed or stale state"""

    # Additional metadata for verbose output
    trace_events: list = field(default_factory=list)
    """Full trace events (for verbose mode debugging)"""

    error_message: Optional[str] = None
    """Top-level error message (e.g., validation failure)"""


# ── State mapping helpers ──────────────────────────────────────────

def map_manifest_state(manifest_state: str) -> str:
    """Map manifest state to CLI state vocabulary.

    Manifest states (from conformance checking):
    - fresh → sealed
    - stale → stale
    - missing → stale (outputs don't exist)
    - tampered → stale (outputs modified)
    """
    if manifest_state == "fresh":
        return "sealed"
    # All other manifest states map to stale
    return "stale"


def map_trace_state(
    trace_event: str,
    cached: bool = False,
    failed: bool = False
) -> str:
    """Map trace event state to CLI state vocabulary.

    Trace events (from build execution):
    - fired + cached=True → cached
    - fired + cached=False → sealed
    - reused → cached (legacy)
    - failed → failed
    - (no event) → dry (not executed)
    """
    if failed:
        return "failed"
    if cached or trace_event == "reused":
        return "cached"
    if trace_event == "fired":
        return "sealed"
    return "dry"
