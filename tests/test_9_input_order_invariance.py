"""
test_9_input_order_invariance.py -- Engine root must match reader root
regardless of declared input ordering.

CSE-v1 §8 says input bindings preserve the rule's declared order; no
additional sorting is applied.  The readers (Python and JS) honour this.
The engine must too.  This test exercises all permutations of a 3-input
rule to catch any engine-side sort that breaks the invariant.
"""

import itertools
import json
import os
import tempfile

from husks.core import recompute_root
from husks.designs import ir
from husks.utils import reset as reset_trace

import pytest


def _run_and_compare(input_order):
    """Build a design with the given input order, run it with the stub,
    then compare the engine-recorded root against the reader-recomputed root."""
    reset_trace()

    with tempfile.TemporaryDirectory() as tmp:
        site = os.path.join(tmp, "site")
        os.makedirs(site, exist_ok=True)

        # Create input files in tmpdir (next to design JSON for _source_path resolution)
        for name in ("a_in.txt", "b_in.txt", "c_in.txt"):
            with open(os.path.join(tmp, name), "w") as f:
                f.write(name.upper() + "\n")

        inputs = list(input_order)
        design = {
            "name": "ordtest",
            "fuel": 20,
            "target": "combine",
            "site_inputs": ["a_in.txt", "b_in.txt", "c_in.txt"],
            "rules": [
                {
                    "name": "combine",
                    "kind": "action",
                    "inputs": inputs,
                    "outputs": ["out.txt"],
                    "run": "cat " + " ".join(inputs) + " > out.txt",
                },
            ],
        }

        dpath = os.path.join(tmp, "d.json")
        with open(dpath, "w") as f:
            json.dump(design, f)

        d = ir.from_json(dpath)
        S = ir.run(d, site=site)

        assert S["status"] == "committed", f"build did not commit: {S['value']}"

        engine_root = S["build-root"]
        assert engine_root is not None, "no build-root recorded"

        husk_path = os.path.join(site, "ordtest.husk")
        assert os.path.exists(husk_path), "no .husk file written"

        husk_bytes = open(husk_path, "rb").read()
        reader_root = recompute_root(husk_bytes, site)

        assert engine_root == reader_root, (
            f"engine/reader root mismatch for input order {inputs}: "
            f"engine={engine_root[:16]}... reader={reader_root[:16]}..."
        )


@pytest.mark.alpha


def test_all_input_orderings_agree():
    """Engine root must equal reader root for every permutation of inputs."""
    for order in itertools.permutations(["a_in.txt", "b_in.txt", "c_in.txt"]):
        _run_and_compare(order)


@pytest.mark.alpha


def test_sorted_order_still_works():
    """Sanity check: the already-sorted case (which was always working) still works."""
    _run_and_compare(["a_in.txt", "b_in.txt", "c_in.txt"])


@pytest.mark.alpha


def test_reverse_sorted_order():
    """The reverse-sorted case is the minimal reproduction of the bug."""
    _run_and_compare(["c_in.txt", "b_in.txt", "a_in.txt"])
