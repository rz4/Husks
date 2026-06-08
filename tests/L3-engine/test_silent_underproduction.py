"""G.a — close silent under-production.

A shell action that exits zero but does not write its declared output
must fail the build.  Previously, the engine auto-created the output
from stdout; this is unsound.
"""

from pathlib import Path

from husks.engine import build, rule


class TestSilentUnderproduction:
    def test_missing_output_halts_build(self, tmp_path):
        """Action 'true' exits 0 but writes nothing — build must halt."""
        site = str(tmp_path / "site")
        n = rule(
            "noop",
            run="true",
            outputs=["out.txt"],
        )
        S = build("b", 5, n, site=site)
        assert S["status"] == "halted"
        assert "did not produce declared output" in S["value"]
        assert not Path(site, "out.txt").exists()
