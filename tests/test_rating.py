"""Tests for the shared rating heuristic.

The Portfolio Manager produces a typed PortfolioDecision via structured
output and renders it to markdown that always contains a ``**Rating**: X``
header.  The deterministic heuristic in ``tradingagents.agents.utils.rating``
extracts the rating from that markdown — no second LLM call is needed.

(Wave 2 of the dead-code sweep removed graph/signal_processing.py — the
thin SignalProcessor adapter over this heuristic — together with its
tests, which used to live in this file as tests/test_signal_processing.py.)
"""

import pytest

from tradingagents.agents.utils.rating import RATINGS_5_TIER, parse_rating


# ---------------------------------------------------------------------------
# Heuristic parser
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestParseRating:
    def test_explicit_label_buy(self):
        assert parse_rating("Rating: Buy\nReasoning here.") == "Buy"

    def test_explicit_label_overweight(self):
        assert parse_rating("Rating: Overweight\nDetails.") == "Overweight"

    def test_explicit_label_with_markdown_bold_value(self):
        # Regression: Rating: **Sell** — markdown around the value.
        assert parse_rating("Rating: **Sell**\nExit immediately.") == "Sell"

    def test_explicit_label_with_markdown_bold_label(self):
        assert parse_rating("**Rating**: Underweight\nTrim exposure.") == "Underweight"

    def test_rendered_pm_markdown_shape(self):
        # The exact shape produced by render_pm_decision must always parse.
        text = (
            "**Rating**: Buy\n\n"
            "**Executive Summary**: Enter at $189-192, 6% portfolio cap.\n\n"
            "**Investment Thesis**: AI capex cycle intact; institutional flows constructive."
        )
        assert parse_rating(text) == "Buy"

    def test_explicit_label_wins_over_prose_with_markdown(self):
        text = (
            "The buy thesis is weakened by guidance.\n"
            "Rating: **Sell**\n"
            "Exit before earnings."
        )
        assert parse_rating(text) == "Sell"

    def test_no_rating_returns_default(self):
        assert parse_rating("No clear directional signal at this time.") == "Hold"

    def test_no_rating_custom_default(self):
        assert parse_rating("Plain prose.", default="Underweight") == "Underweight"

    def test_all_five_tiers_recognised(self):
        for r in RATINGS_5_TIER:
            assert parse_rating(f"Rating: {r}") == r
