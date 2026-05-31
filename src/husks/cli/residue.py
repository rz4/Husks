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
class CliOutput:
    """Represents a single output artifact from a rule."""

    path: str
    """Output file path"""

    sha256: Optional[str] = None
    """Content hash of the output (lowercase hex)"""


@dataclass
class CliTrace:
    """Oracle provenance and execution metadata."""

    backend: Optional[str] = None
    """Backend type: 'litellm', 'stub', or custom"""

    provider: Optional[str] = None
    """LLM provider (e.g., 'anthropic')"""

    model: Optional[str] = None
    """Model identifier (e.g., 'claude-haiku-4-5')"""

    config_hash: Optional[str] = None
    """Hash of oracle config (provider+model+params)"""

    prompt_hash: Optional[str] = None
    """Hash of prompt content"""

    input_tokens: int = 0
    """Input tokens consumed"""

    output_tokens: int = 0
    """Output tokens generated"""

    elapsed_s: Optional[float] = None
    """Execution time in seconds"""

    cost_usd: float = 0.0
    """Cost in USD"""

    stdout: Optional[str] = None
    """Captured stdout (for action rules)"""

    stderr: Optional[str] = None
    """Captured stderr (for action rules)"""

    cache_source: Optional[str] = None
    """Cache source identifier (e.g., 'local', 'imported')"""


@dataclass
class CliNode:
    """Represents a single node (rule) in CLI output.

    **State vocabulary (unified across check, run, status):**
    - unrealized: Node exists in design but hasn't run
    - sealed: Previously built, inputs unchanged, outputs fresh
    - cached: Reused from cache with explicit evidence
    - stale: Recipe/inputs changed, or outputs missing/tampered
    - failed: Execution failed with diagnosis
    - running: Currently executing (verbose run frames)

    **Kind vocabulary:**
    - oracle: LLM-powered generative rule
    - action: Deterministic shell command
    - trial: Non-committing exploration
    """

    name: str
    """Rule name"""

    kind: str
    """Rule kind: oracle, action, or trial"""

    state: str
    """Node state: unrealized, sealed, cached, stale, failed, running"""

    children: list[str] = field(default_factory=list)
    """Child node names (dependencies)"""

    fuel: Optional[int] = None
    """Fuel consumed by this node (None if not executed)"""

    fuel_budget: Optional[int] = None
    """Fuel budget for this node (oracle rules)"""

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

    duration: Optional[float] = None
    """Execution duration in seconds"""

    outputs: list[CliOutput] = field(default_factory=list)
    """Output artifacts produced by this node"""

    reason: Optional[str] = None
    """Reason for current state (e.g., halt reason, cache source)"""

    trace: Optional[CliTrace] = None
    """Oracle/action execution trace (provenance metadata)"""


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

    status: str
    """Build status: checked, hydrating, sealed, stale, failed"""

    design: Optional[str] = None
    """Design file path"""

    site: Optional[str] = None
    """Site directory path (None for check without --site)"""

    cse_path: Optional[str] = None
    """CSE husk artifact path (e.g., 'core-bootstrap.husk')"""

    root: Optional[str] = None
    """Build root hash (None if not committed)"""

    target: Optional[str] = None
    """Target rule name"""

    fuel_budget: int = 0
    """Total fuel budget from design"""

    fuel_used: int = 0
    """Fuel consumed by executed rules"""

    cost: float = 0.0
    """Total USD cost of oracle calls"""

    nodes: list[CliNode] = field(default_factory=list)
    """List of nodes (rules) in target-rooted order"""

    passes: list[str] = field(default_factory=list)
    """List of passing categories (e.g., ['checks', 'site', 'cache'])"""

    fails: list[str] = field(default_factory=list)
    """List of failing categories (e.g., ['site', 'run'])"""

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
    - (no event) → unrealized (not executed)
    """
    if failed:
        return "failed"
    if cached or trace_event == "reused":
        return "cached"
    if trace_event == "fired":
        return "sealed"
    return "unrealized"
