"""
test_12_fuel_batch.py -- Mid-batch fuel exhaustion in kernel step().

When a parallel tool call batch has N calls and fuel = K < N, exactly
K calls should dispatch and the result should be a halt.
"""

from husks.oracle.kernel import step
from husks.oracle import tools

import pytest


@pytest.mark.alpha


def test_mid_batch_fuel_exhaustion():
    """Batch of 4 calls with fuel=2 must dispatch exactly 2, then halt."""
    dispatch_count = [0]

    def counting_fn(**kwargs):
        dispatch_count[0] += 1
        return "ok"

    # Register dummy tool
    orig = tools._REGISTRY.get("t")
    tools._REGISTRY["t"] = {"fn": counting_fn, "schema": {}}

    iteration = [0]

    def mock_M(C):
        iteration[0] += 1
        if iteration[0] == 1:
            return {
                "type": "acts",
                "calls": [
                    {"tool": "t", "args": {}, "tool_call_id": f"c{i}"}
                    for i in range(4)
                ],
            }
        return {"type": "stop", "value": "done"}

    try:
        result = step(mock_M, {"tools": ["t"]}, fuel=2)
        assert result["type"] == "halt", f"expected halt, got {result['type']}"
        assert dispatch_count[0] == 2, f"expected 2 dispatches, got {dispatch_count[0]}"
        assert result["fuel_steps"] == 2
    finally:
        if orig is None:
            tools._REGISTRY.pop("t", None)
        else:
            tools._REGISTRY["t"] = orig


@pytest.mark.alpha


def test_batch_exact_fuel():
    """Batch of 2 calls with fuel=2 dispatches all, then halts on next iteration."""
    dispatch_count = [0]

    def counting_fn(**kwargs):
        dispatch_count[0] += 1
        return "ok"

    orig = tools._REGISTRY.get("t")
    tools._REGISTRY["t"] = {"fn": counting_fn, "schema": {}}

    iteration = [0]

    def mock_M(C):
        iteration[0] += 1
        if iteration[0] == 1:
            return {
                "type": "acts",
                "calls": [
                    {"tool": "t", "args": {}, "tool_call_id": "a"},
                    {"tool": "t", "args": {}, "tool_call_id": "b"},
                ],
            }
        return {"type": "stop", "value": "done"}

    try:
        result = step(mock_M, {"tools": ["t"]}, fuel=2)
        # All 2 dispatched, fuel now 0, next loop iteration halts
        assert result["type"] == "halt"
        assert dispatch_count[0] == 2
        assert result["fuel_steps"] == 2
    finally:
        if orig is None:
            tools._REGISTRY.pop("t", None)
        else:
            tools._REGISTRY["t"] = orig


@pytest.mark.alpha


def test_fuel_never_negative():
    """Fuel must never go negative in batch processing."""
    dispatch_count = [0]

    def counting_fn(**kwargs):
        dispatch_count[0] += 1
        return "ok"

    orig = tools._REGISTRY.get("t")
    tools._REGISTRY["t"] = {"fn": counting_fn, "schema": {}}

    def mock_M(C):
        return {
            "type": "acts",
            "calls": [
                {"tool": "t", "args": {}, "tool_call_id": f"c{i}"}
                for i in range(10)
            ],
        }

    try:
        result = step(mock_M, {"tools": ["t"]}, fuel=3)
        assert result["type"] == "halt"
        assert dispatch_count[0] == 3, f"expected 3 dispatches, got {dispatch_count[0]}"
        assert result["fuel_steps"] == 3
    finally:
        if orig is None:
            tools._REGISTRY.pop("t", None)
        else:
            tools._REGISTRY["t"] = orig
