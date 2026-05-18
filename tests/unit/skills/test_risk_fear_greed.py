from datetime import date
from unittest.mock import patch

from tradingagents.skills.risk.fear_greed import fetch_fear_greed_index


def test_fear_greed_returns_none_on_scrape_fail():
    # use_cache=False로 실제 home cache의 stale fallback 회피
    with patch("tradingagents.skills.risk.fear_greed._scrape_cnn_fg", return_value=None):
        result = fetch_fear_greed_index(date(2026, 5, 10), use_cache=False)
    assert result is None


def test_fear_greed_parses_response():
    fake_data = {"score": 30, "previous_close": 25}
    with patch("tradingagents.skills.risk.fear_greed._scrape_cnn_fg", return_value=fake_data):
        result = fetch_fear_greed_index(date(2026, 5, 10), use_cache=False)
    assert result is not None
    assert result.current_value == 30
    assert result.label == "fear"
    assert result.trend_7d == "rising"
