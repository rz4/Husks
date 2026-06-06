"""test_helpers.py -- Constants, helpers, banner rendering."""

from husks.cli import (
    EXIT_OK, EXIT_BUILD_FAIL, EXIT_USAGE, EXIT_MISSING_DEP,
    EXIT_DIRTY_STALE, EXIT_INTERNAL,
    _visible_len, _rpad, _format_tokens, _truncate_right,
    render_banner, STATE_GLYPHS, STATE_COLORS, R,
    _DIAMOND, _DIAMOND_VIS,
)


# ── §1 Constants ──────────────────────────────────────────────

class TestExitCodes:
    def test_values(self):
        assert EXIT_OK == 0
        assert EXIT_BUILD_FAIL == 1
        assert EXIT_USAGE == 2
        assert EXIT_MISSING_DEP == 3
        assert EXIT_DIRTY_STALE == 4
        assert EXIT_INTERNAL == 5

    def test_all_distinct(self):
        codes = [EXIT_OK, EXIT_BUILD_FAIL, EXIT_USAGE, EXIT_MISSING_DEP,
                 EXIT_DIRTY_STALE, EXIT_INTERNAL]
        assert len(set(codes)) == len(codes)


class TestStateGlyphs:
    def test_all_states_present(self):
        for s in ("unrealized", "sealed", "cached", "stale", "failed", "running"):
            assert s in STATE_GLYPHS
            assert s in STATE_COLORS

    def test_glyphs_are_single_char(self):
        for g in STATE_GLYPHS.values():
            assert len(g) == 1


class TestDiamondArt:
    def test_all_stages_present(self):
        for s in ("dry", "hydrating", "sealed", "failed", "white"):
            assert s in _DIAMOND
            assert len(_DIAMOND[s]) == 5

    def test_vis_lengths(self):
        assert len(_DIAMOND_VIS) == 5
        assert all(isinstance(v, int) for v in _DIAMOND_VIS)

    def test_right_bound(self):
        assert R == 81


# ── §2 Helpers ────────────────────────────────────────────────

class TestVisibleLen:
    def test_plain(self):
        assert _visible_len("hello") == 5

    def test_ansi_stripped(self):
        assert _visible_len("\033[31mred\033[0m") == 3

    def test_empty(self):
        assert _visible_len("") == 0

    def test_wide_char(self):
        # CJK ideograph is double-width
        assert _visible_len("\u4e16") == 2


class TestRpad:
    def test_basic(self):
        result = _rpad("left", "right", 20)
        assert "left" in result
        assert "right" in result
        assert len(result) == 20

    def test_empty_right(self):
        assert _rpad("left", "", 20) == "left"

    def test_narrow_width(self):
        result = _rpad("left", "right", 5)
        # Should still have at least 1 space gap
        assert " " in result


class TestFormatTokens:
    def test_small(self):
        assert _format_tokens(500) == "500"

    def test_exact_thousand(self):
        assert _format_tokens(1000) == "1.0k"

    def test_large(self):
        assert _format_tokens(2500) == "2.5k"

    def test_zero(self):
        assert _format_tokens(0) == "0"


class TestTruncateRight:
    def test_short_stays(self):
        assert _truncate_right("hi", 10) == "hi"

    def test_long_truncated(self):
        result = _truncate_right("a" * 20, 10)
        assert len(result) <= 10
        assert result.endswith("\u2026")

    def test_tab_replaced(self):
        result = _truncate_right("\there", 50)
        assert "\t" not in result


class TestRenderBanner:
    def test_basic_stages(self):
        for stage in ("dry", "hydrating", "sealed", "failed", "white"):
            text = render_banner(stage)
            assert isinstance(text, str)
            assert len(text.splitlines()) == 5

    def test_with_right_lines(self):
        text = render_banner("sealed", ["Line1", "Line2"])
        assert "Line1" in text
        assert "Line2" in text

    def test_unknown_stage_fallback(self):
        text = render_banner("unknown_stage")
        # Falls back to hydrating
        assert isinstance(text, str)
        assert len(text.splitlines()) == 5
