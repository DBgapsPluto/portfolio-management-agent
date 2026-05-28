import numpy as np
import pandas as pd
import pytest

from tradingagents.dataflows.universe import Universe, ETFEntry
from tradingagents.skills.portfolio.factor_scorer import compute_factor_panel
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
    rankings = rank_momentum(prices, universe)
    assert "국내주식_지수" in rankings
    assert "해외주식_지수" in rankings
    assert all(r.rank_in_category == 1 for cat in rankings.values() for r in cat[:1])


@pytest.mark.parametrize("window_label,window", [
    ("3m", 63), ("6m", 126), ("12m", 252),
])
def test_skip1m_definition_matches_across_stages(window_label, window):
    """Regression: Stage 1 momentum_ranker and Stage 3 factor_scorer must
    produce the same skip-1m momentum for the same series + window.

    Stage 1 uses close-ratio: close[t-21] / close[t-21-window] - 1
    Stage 3 uses return-product over the matching slice of daily returns.
    With no missing data, these are mathematically equivalent.
    """
    rng = np.random.default_rng(7)
    n = 320  # > 252 + 21 buffer
    daily_returns = rng.normal(0.0005, 0.01, n)
    close = 100.0 * np.cumprod(1.0 + daily_returns)
    dates = pd.date_range("2023-01-02", periods=n, freq="B")
    close_series = pd.Series(close, index=dates)
    return_series = close_series.pct_change().dropna()

    # Stage 1 convention (anchor-based price ratio)
    anchor = float(close_series.iloc[-22])
    base = float(close_series.iloc[-22 - window])
    ranker_mom = anchor / base - 1.0

    # Stage 3 convention (return-product over same slice)
    panel = compute_factor_panel(return_series, aum_krw=1e12)
    scorer_mom = {
        63: panel.skip1m_mom_3m,
        126: panel.skip1m_mom_6m,
        252: panel.skip1m_mom_12m,
    }[window]

    assert scorer_mom is not None, f"{window_label} returned None"
    assert ranker_mom == pytest.approx(scorer_mom, abs=1e-9), (
        f"{window_label} mismatch: ranker={ranker_mom:.10f} "
        f"scorer={scorer_mom:.10f} (diff={ranker_mom - scorer_mom:.2e})"
    )
