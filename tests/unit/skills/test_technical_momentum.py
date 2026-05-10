import numpy as np
import pandas as pd

from tradingagents.dataflows.universe import Universe, ETFEntry
from tradingagents.skills.technical.momentum_ranker import rank_momentum


def _synthetic_universe() -> Universe:
    return Universe(version="2026-05-10", etfs=[
        ETFEntry(ticker="A069500", name="KODEX 200", aum_krw=1e13,
                 underlying_index="KOSPI 200", bucket="위험", category="국내주식_지수"),
        ETFEntry(ticker="A360750", name="TIGER S&P500", aum_krw=1e13,
                 underlying_index="S&P 500", bucket="위험", category="해외주식_지수"),
    ])


def _synthetic_prices() -> pd.DataFrame:
    dates = pd.date_range("2024-05-01", periods=300, freq="B")
    rng = np.random.default_rng(42)
    rows = []
    for ticker, drift in [("A069500", 0.05), ("A360750", 0.10)]:
        close = 100 + np.cumsum(rng.normal(drift, 1.0, 300))
        for d, c in zip(dates, close):
            rows.append({"ticker": ticker, "date": d, "close": float(c),
                         "open": float(c), "high": float(c+1), "low": float(c-1), "volume": 1000})
    return pd.DataFrame(rows)


def test_rank_momentum_groups_by_category():
    prices = _synthetic_prices()
    universe = _synthetic_universe()
    rankings = rank_momentum(prices, universe, lookback_months=6)
    assert "국내주식_지수" in rankings
    assert "해외주식_지수" in rankings
    assert all(r.rank_in_category == 1 for cat in rankings.values() for r in cat[:1])
