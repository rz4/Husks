"""
test_beta_three_machine.py -- Beta Gate E2: Three-machine smoke test.

Task 12: This test uses programmatic API for unit testing.
The CANONICAL beta seed is: examples/beta_seed/
CLI-based tests (test_compare_runs.py, test_three_machine_cli_acceptance.py)
use the canonical seed via `husks run` commands.

This is the development spine for Husks beta. The test simulates the
three-machine proof:

Machine 1: seed design + empty cache + oracle access
  -> builds valid artifact, reports cost C1

Machine 2: same seed + imported cache from Machine 1
  -> materializes equivalent artifact, zero oracle cost, reports cache reuse

Machine 3: same seed + empty cache + oracle access
  -> independently builds valid artifact, cost C3 comparable to C1

This test may start as skipped or expected-fail. Every beta task should
move this test closer to green.
"""

import tempfile
import shutil
import json
from pathlib import Path


def test_machine_1_and_3_independent_realization():
    """Machine 1 and Machine 3 independently realize same seed with comparable cost.

    Tests Beta Gate E2: Independent re-realization.

    Machine 1 and Machine 3 receive the same seed design and empty caches.
    Both should:
    - Build successfully
    - Produce valid artifacts
    - Pay comparable oracle costs
    - Have comparable oracle call counts
    """
    from husks.designs.ir import run
    from husks.build.cache import cache_list

    tmpdir = tempfile.mkdtemp(prefix="beta-three-machine-")
    try:
        # Prepare seed design (beta_seed example)
        seed_design = {
            "name": "beta-seed",
            "fuel": 20,
            "target": "validate",
            "site_inputs": ["prompt.txt"],
            "rules": [
                {
                    "name": "generate",
                    "kind": "oracle",
                    "inputs": ["prompt.txt"],
                    "outputs": ["response.txt"],
                    "prompt": "Read the prompt and provide a brief, factual answer.",
                    "tools": [],
                    "fuel": 8,
                },
                {
                    "name": "validate",
                    "kind": "action",
                    "inputs": ["response.txt"],
                    "outputs": ["validation.txt"],
                    "run": "python3 -c \"text = open('response.txt').read(); valid = len(text.strip()) > 0; open('validation.txt', 'w').write('PASS\\\\n' if valid else 'FAIL\\\\n')\"",
                },
            ],
        }

        # Stub oracle for deterministic testing
        def stub_oracle(S, rule_name, recipe, outputs):
            from husks.build.site import write_text, site_path
            write_text(
                site_path(S, outputs[0], write=True),
                "The capital of France is Paris.\n",
            )
            return {"tokens_in": 100, "tokens_out": 50, "cost_usd": 0.001, "fuel_steps": 1}

        # Machine 1: Independent realization
        machine1_site = Path(tmpdir) / "machine1"
        machine1_site.mkdir()
        (machine1_site / "prompt.txt").write_text("What is the capital of France?\n")

        design1 = {**seed_design, "site": str(machine1_site)}
        S1 = run(design1, oracle_backend=stub_oracle)

        # Assertions for Machine 1
        assert S1["status"] == "committed", "Machine 1 should commit successfully"
        assert (machine1_site / "validation.txt").read_text() == "PASS\n"

        # Check oracle was called
        m1_cost = S1["usage"]["total_cost_usd"]
        m1_calls = S1["usage"]["total_input_tokens"] // 100  # Approximation based on stub
        assert m1_cost > 0, "Machine 1 should have paid oracle cost"
        assert m1_calls > 0, "Machine 1 should have called oracle"

        # Machine 3: Independent re-realization (separate site, empty cache)
        machine3_site = Path(tmpdir) / "machine3"
        machine3_site.mkdir()
        (machine3_site / "prompt.txt").write_text("What is the capital of France?\n")

        design3 = {**seed_design, "site": str(machine3_site)}
        S3 = run(design3, oracle_backend=stub_oracle)

        # Assertions for Machine 3
        assert S3["status"] == "committed", "Machine 3 should commit successfully"
        assert (machine3_site / "validation.txt").read_text() == "PASS\n"

        # Check oracle was called
        m3_cost = S3["usage"]["total_cost_usd"]
        m3_calls = S3["usage"]["total_input_tokens"] // 100
        assert m3_cost > 0, "Machine 3 should have paid oracle cost"
        assert m3_calls > 0, "Machine 3 should have called oracle"

        # Cost comparability (should be equal for stub oracle)
        assert m1_cost == m3_cost, (
            f"Machine 1 and 3 costs should be comparable "
            f"(M1: ${m1_cost}, M3: ${m3_cost})"
        )
        assert m1_calls == m3_calls, (
            f"Machine 1 and 3 oracle calls should be comparable "
            f"(M1: {m1_calls}, M3: {m3_calls})"
        )

        # Artifact validity: both should have same output structure
        assert (machine1_site / "response.txt").exists()
        assert (machine3_site / "response.txt").exists()
        assert (machine1_site / "validation.txt").read_text() == "PASS\n"
        assert (machine3_site / "validation.txt").read_text() == "PASS\n"

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_three_machine_full_proof():
    """Full three-machine proof: M1 builds, M2 reuses, M3 re-realizes.

    Tests the complete beta acceptance criteria:
    - Machine 1: builds with oracle cost
    - Machine 2: reuses cache with zero cost
    - Machine 3: independently builds with comparable cost

    This test requires cache export/import (Beta Gate D) to be complete.
    """
    from husks.designs.ir import run
    from husks.build.cache import cache_export, cache_import

    tmpdir = tempfile.mkdtemp(prefix="beta-full-proof-")
    try:
        # Seed design
        seed_design = {
            "name": "beta-seed",
            "fuel": 20,
            "target": "validate",
            "site_inputs": ["prompt.txt"],
            "rules": [
                {
                    "name": "generate",
                    "kind": "oracle",
                    "inputs": ["prompt.txt"],
                    "outputs": ["response.txt"],
                    "prompt": "Answer the question briefly and factually.",
                    "tools": [],
                    "fuel": 8,
                },
                {
                    "name": "validate",
                    "kind": "action",
                    "inputs": ["response.txt"],
                    "outputs": ["validation.txt"],
                    "run": "python3 -c \"text = open('response.txt').read(); valid = len(text.strip()) > 0; open('validation.txt', 'w').write('PASS\\\\n' if valid else 'FAIL\\\\n')\"",
                },
            ],
        }

        def stub_oracle(S, rule_name, recipe, outputs):
            from husks.build.site import write_text, site_path
            write_text(
                site_path(S, outputs[0], write=True),
                "The capital of France is Paris.\n",
            )
            return {"tokens_in": 100, "tokens_out": 50, "cost_usd": 0.001, "fuel_steps": 1}

        # Machine 1: Original realization
        m1_site = Path(tmpdir) / "machine1"
        m1_site.mkdir()
        (m1_site / "prompt.txt").write_text("What is the capital of France?\n")

        design1 = {**seed_design, "site": str(m1_site)}
        S1 = run(design1, oracle_backend=stub_oracle)

        assert S1["status"] == "committed"
        assert S1["usage"]["total_cost_usd"] > 0, "M1 should pay oracle cost"
        m1_cost = S1["usage"]["total_cost_usd"]

        # Export cache from Machine 1
        cache_file = Path(tmpdir) / "cache.tar.gz"
        cache_export(S1, str(cache_file))
        assert cache_file.exists(), "Cache export should create file"

        # Machine 2: Cache reuse
        m2_site = Path(tmpdir) / "machine2"
        m2_site.mkdir()
        (m2_site / "prompt.txt").write_text("What is the capital of France?\n")

        # Import cache to M2 site
        from husks.build import fresh_store
        S2_import = fresh_store(str(m2_site), fuel=20)
        cache_import(S2_import, str(cache_file))

        # Build with cache-reuse-only mode
        # For now, skip reuse-only mode test and just verify cache is used
        design2 = {**seed_design, "site": str(m2_site)}
        S2 = run(design2, oracle_backend=stub_oracle)

        assert S2["status"] == "committed"
        # Machine 2 should have zero cost (cache hit)
        assert S2["usage"]["total_cost_usd"] == 0.0, "M2 should have zero oracle cost (cache hit)"
        assert (m2_site / "validation.txt").read_text() == "PASS\n"

        # Machine 3: Independent re-realization
        m3_site = Path(tmpdir) / "machine3"
        m3_site.mkdir()
        (m3_site / "prompt.txt").write_text("What is the capital of France?\n")

        design3 = {**seed_design, "site": str(m3_site)}
        S3 = run(design3, oracle_backend=stub_oracle)

        assert S3["status"] == "committed"
        assert S3["usage"]["total_cost_usd"] > 0, "M3 should pay oracle cost"
        m3_cost = S3["usage"]["total_cost_usd"]

        # Cost comparability
        assert m1_cost == m3_cost, (
            f"M1 and M3 costs should be comparable (M1: ${m1_cost}, M3: ${m3_cost})"
        )

        # All machines produce valid artifacts
        assert (m1_site / "validation.txt").read_text() == "PASS\n"
        assert (m2_site / "validation.txt").read_text() == "PASS\n"
        assert (m3_site / "validation.txt").read_text() == "PASS\n"

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)
