"""test_convergence.py -- History I/O, trend analysis, convergence classification."""

from husks.report import (
    read_history, _trend, convergence_summary, declared_vs_traced,
)


# ── History I/O ─────────────────────────────────────────────────

class TestReadHistory:
    def test_no_file(self, tmp_site):
        assert read_history(str(tmp_site), "w") == []

    def test_read_entries(self, tmp_site, write_history):
        entries = [
            {"fuel_consumed": 3, "output_hashes": ["a"]},
            {"fuel_consumed": 2, "output_hashes": ["b"]},
        ]
        write_history(tmp_site, "w", entries)
        result = read_history(str(tmp_site), "w")
        assert len(result) == 2
        assert result[0]["fuel_consumed"] == 3

    def test_blank_lines_skipped(self, tmp_site):
        p = tmp_site / ".traces" / "w.history.jsonl"
        p.write_text('{"a":1}\n\n{"a":2}\n')
        assert len(read_history(str(tmp_site), "w")) == 2


# ── Trend analysis ──────────────────────────────────────────────

class TestTrend:
    def test_flat_single(self):
        assert _trend([5]) == "flat"

    def test_flat_equal(self):
        assert _trend([3, 3, 3]) == "flat"

    def test_falling(self):
        assert _trend([5, 3, 1]) == "falling"

    def test_rising(self):
        assert _trend([1, 3, 5]) == "rising"

    def test_mixed(self):
        assert _trend([1, 5, 3]) == "flat"

    def test_empty(self):
        assert _trend([]) == "flat"


# ── Convergence summary ────────────────────────────────────────

class TestConvergenceSummary:
    def test_no_data(self, tmp_site):
        cs = convergence_summary("w", str(tmp_site))
        assert cs["classification"] == "no-data"
        assert cs["fuel_trend"] is None

    def test_stable(self, tmp_site, write_history):
        entries = [
            {"fuel_consumed": 3, "output_hashes": ["h1"]},
            {"fuel_consumed": 3, "output_hashes": ["h1"]},
            {"fuel_consumed": 3, "output_hashes": ["h1"]},
        ]
        write_history(tmp_site, "w", entries)
        cs = convergence_summary("w", str(tmp_site))
        assert cs["classification"] == "stable"
        assert cs["output_stable"] is True

    def test_converging(self, tmp_site, write_history):
        entries = [
            {"fuel_consumed": 5, "output_hashes": ["h1"]},
            {"fuel_consumed": 3, "output_hashes": ["h2"]},
        ]
        write_history(tmp_site, "w", entries)
        cs = convergence_summary("w", str(tmp_site))
        assert cs["classification"] == "converging"
        assert cs["fuel_trend"] == "falling"

    def test_volatile(self, tmp_site, write_history):
        # Rising fuel (1,3,5) with rising prompt -> volatile
        entries = [
            {"fuel_consumed": 1, "prompt_length": 10, "output_hashes": ["h1"]},
            {"fuel_consumed": 3, "prompt_length": 15, "output_hashes": ["h2"]},
            {"fuel_consumed": 5, "prompt_length": 20, "output_hashes": ["h3"]},
        ]
        write_history(tmp_site, "w", entries)
        cs = convergence_summary("w", str(tmp_site))
        assert cs["classification"] == "volatile"

    def test_prompt_loading(self, tmp_site, write_history):
        entries = [
            {"fuel_consumed": 3, "prompt_length": 10, "output_hashes": ["h1"]},
            {"fuel_consumed": 3, "prompt_length": 20, "output_hashes": ["h2"]},
        ]
        write_history(tmp_site, "w", entries)
        cs = convergence_summary("w", str(tmp_site))
        assert cs["classification"] == "prompt-loading"
        assert cs["prompt_trend"] == "rising"

    def test_n_limit(self, tmp_site, write_history):
        entries = [{"fuel_consumed": i, "output_hashes": [f"h{i}"]}
                   for i in range(10)]
        write_history(tmp_site, "w", entries)
        cs = convergence_summary("w", str(tmp_site), n=3)
        assert len(cs["entries"]) == 3


# ── Declared vs. traced ────────────────────────────────────────

class TestDeclaredVsTraced:
    def test_no_undeclared(self, tmp_site, write_history):
        design = {"rules": [
            {"name": "w", "inputs": ["a.txt"]},
        ]}
        write_history(tmp_site, "w", [
            {"traced_reads": ["a.txt"]},
        ])
        assert declared_vs_traced(design, str(tmp_site)) == {}

    def test_undeclared(self, tmp_site, write_history):
        design = {"rules": [
            {"name": "w", "inputs": ["a.txt"]},
        ]}
        write_history(tmp_site, "w", [
            {"traced_reads": ["a.txt", "b.txt"]},
        ])
        result = declared_vs_traced(design, str(tmp_site))
        assert result == {"w": ["b.txt"]}

    def test_no_history(self, tmp_site):
        design = {"rules": [{"name": "w", "inputs": ["a.txt"]}]}
        assert declared_vs_traced(design, str(tmp_site)) == {}
