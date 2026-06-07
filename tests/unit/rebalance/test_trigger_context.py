from datetime import date
import pandas as pd
import tradingagents.rebalance.daily_triggers as dt


def _patch_common(monkeypatch):
    monkeypatch.setattr(dt, "fetch_volatility_index",
                        lambda k, d: type("S", (), {"current_value": 15.0})())
    monkeypatch.setattr(dt, "fetch_fred_series", lambda *a, **k: pd.Series([1.0, 1.0]))


def test_any_etf_weight_from_current_weights(monkeypatch):
    _patch_common(monkeypatch)
    monkeypatch.setattr(dt, "fetch_etf_snapshot_by_date", lambda d: pd.DataFrame())
    monkeypatch.setattr(dt, "fetch_market_index", lambda *a, **k: pd.Series([100.0, 102.0]))
    ctx = dt._build_context(date(2026, 6, 8),
                            current_weights={"A069500": 0.22, "A229200": 0.10})
    assert abs(ctx["any_etf_weight"] - 0.22) < 1e-9
    assert abs(ctx["kospi_return_1d"] - 0.02) < 1e-9


def test_falls_back_to_snapshot_when_no_current_weights(monkeypatch):
    _patch_common(monkeypatch)
    monkeypatch.setattr(dt, "fetch_etf_snapshot_by_date",
                        lambda d: pd.DataFrame({"close": [100.0, 300.0]}))
    monkeypatch.setattr(dt, "fetch_market_index", lambda *a, **k: pd.Series([100.0, 100.0]))
    ctx = dt._build_context(date(2026, 6, 8), current_weights=None)
    assert abs(ctx["any_etf_weight"] - 0.75) < 1e-9   # 300/400


def test_kospi_return_zero_on_short_series(monkeypatch):
    _patch_common(monkeypatch)
    monkeypatch.setattr(dt, "fetch_etf_snapshot_by_date", lambda d: pd.DataFrame())
    monkeypatch.setattr(dt, "fetch_market_index", lambda *a, **k: pd.Series([100.0]))
    ctx = dt._build_context(date(2026, 6, 8), current_weights={"A": 0.1})
    assert ctx["kospi_return_1d"] == 0.0
