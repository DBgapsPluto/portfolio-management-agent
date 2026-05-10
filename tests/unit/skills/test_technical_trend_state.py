from datetime import date

from tradingagents.schemas.technical import IndicatorPanel, TrendState
from tradingagents.skills.technical.trend_state import detect_trend_state


def _panel(ma200=100.0, ma50=100.0, rsi=50.0):
    return IndicatorPanel(
        ticker="A069500",
        ma200=ma200, ma50=ma50, rsi=rsi,
        macd_signal=0.0, atr=1.0,
        source_date=date(2026, 5, 10),
    )


def test_strong_uptrend():
    panel = _panel(ma200=100, ma50=110, rsi=65)
    assert detect_trend_state(panel, current_price=120) == TrendState.STRONG_UPTREND


def test_uptrend():
    panel = _panel(ma200=100, ma50=105, rsi=55)
    assert detect_trend_state(panel, current_price=108) == TrendState.UPTREND


def test_breakdown():
    panel = _panel(ma200=100, ma50=95, rsi=30)
    assert detect_trend_state(panel, current_price=85) == TrendState.BREAKDOWN


def test_downtrend():
    panel = _panel(ma200=100, ma50=95, rsi=45)
    assert detect_trend_state(panel, current_price=92) == TrendState.DOWNTREND


def test_neutral():
    panel = _panel(ma200=100, ma50=105, rsi=50)
    assert detect_trend_state(panel, current_price=102) == TrendState.NEUTRAL
