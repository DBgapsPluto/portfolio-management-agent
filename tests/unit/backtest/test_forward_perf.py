from datetime import date

import pandas as pd

import tradingagents.backtest.forward_perf as fp


def test_score_ok_basic(monkeypatch):
    idx = pd.date_range("2025-01-02", periods=60, freq="B")
    # A: alternating +0.2%/0% (mean>0, std>0), B: flat
    rm = pd.DataFrame({"A": [0.002, 0.0] * 30, "B": [0.0] * 60}, index=idx)
    monkeypatch.setattr(fp, "fetch_returns_matrix", lambda *a, **k: rm)
    out = fp.score_forward_performance({"A": 0.5, "B": 0.5}, date(2025, 1, 1), 63)
    assert out["status"] == "ok"
    assert out["n_obs"] == 60
    assert out["total_return"] > 0
    assert out["sharpe"] > 0
    assert out["max_drawdown"] <= 0


def test_score_insufficient_obs(monkeypatch):
    idx = pd.date_range("2025-01-02", periods=10, freq="B")
    rm = pd.DataFrame({"A": [0.001] * 10}, index=idx)
    monkeypatch.setattr(fp, "fetch_returns_matrix", lambda *a, **k: rm)
    out = fp.score_forward_performance({"A": 1.0}, date(2025, 1, 1), 63)
    assert out["status"] == "insufficient_data"
    assert out["n_obs"] == 10


def test_score_empty(monkeypatch):
    monkeypatch.setattr(fp, "fetch_returns_matrix", lambda *a, **k: pd.DataFrame())
    out = fp.score_forward_performance({"A": 1.0}, date(2025, 1, 1), 63)
    assert out["status"] == "insufficient_data"


def test_score_truncates_to_horizon(monkeypatch):
    idx = pd.date_range("2025-01-02", periods=200, freq="B")
    rm = pd.DataFrame({"A": [0.001] * 200}, index=idx)
    monkeypatch.setattr(fp, "fetch_returns_matrix", lambda *a, **k: rm)
    out = fp.score_forward_performance({"A": 1.0}, date(2025, 1, 1), 63)
    assert out["n_obs"] == 63   # 앞 63 거래일만
