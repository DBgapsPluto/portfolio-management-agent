import numpy as np
import pandas as pd
import pytest

from tradingagents.dataflows.universe import Universe, ETFEntry
from tradingagents.skills.technical.sector_rotation import (
    _decile_spread, compute_sector_rotation,
)


def _build_universe(specs: list[tuple[str, str, float]]) -> Universe:
    """specs: [(ticker, category, drift)]"""
    etfs = [
        ETFEntry(
            ticker=t, name=t, aum_krw=1e10,
            underlying_index="x", bucket="위험", category=cat,
        )
        for (t, cat, _drift) in specs
    ]
    return Universe(version="t", etfs=etfs)


def _prices_for(specs, n_days: int = 300, seed: int = 0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    dates = pd.date_range("2024-01-01", periods=n_days, freq="B")
    rows = []
    for ticker, _cat, drift in specs:
        close = 100 + np.cumsum(rng.normal(drift, 0.8, n_days))
        close = np.maximum(close, 1.0)
        rows.append(pd.DataFrame({
            "ticker": [ticker] * n_days, "date": dates, "close": close,
        }))
    return pd.concat(rows, ignore_index=True)


def test_basic_shape_and_ranking():
    specs = [
        ("A000001", "국내주식_지수", 0.3),
        ("A000002", "국내주식_지수", 0.4),
        ("A000003", "해외주식_지수", 0.05),
        ("A000004", "해외주식_지수", 0.0),
        ("A000005", "국내채권_종합", -0.1),
        ("A000006", "국내채권_종합", -0.15),
    ]
    universe = _build_universe(specs)
    prices = _prices_for(specs, n_days=300, seed=3)
    snap = compute_sector_rotation(prices, universe)

    assert len(snap.categories) == 3
    # Best drift category should lead
    assert snap.leader_category == "국내주식_지수"
    assert snap.laggard_category == "국내채권_종합"
    # Ranks consecutive 1..N
    assert [c.rank for c in snap.categories] == [1, 2, 3]


def test_correlation_regime_stable_or_classified():
    specs = [(f"A{str(i+1).zfill(6)}", "국내주식_지수", 0.1) for i in range(8)]
    universe = _build_universe(specs)
    prices = _prices_for(specs, n_days=300, seed=11)
    snap = compute_sector_rotation(prices, universe)
    assert snap.correlation_regime in ("expansion", "stable", "compression")
    assert -1.0 <= snap.correlation_median_60d <= 1.0
    assert -1.0 <= snap.correlation_median_252d <= 1.0


def test_momentum_spread_positive_with_dispersion():
    # Half strongly up, half strongly down → spread should be large positive
    specs = (
        [(f"A{str(i+1).zfill(6)}", "X", 0.6) for i in range(15)]
        + [(f"A{str(i+16).zfill(6)}", "Y", -0.6) for i in range(15)]
    )
    universe = _build_universe(specs)
    prices = _prices_for(specs, n_days=300, seed=17)
    snap = compute_sector_rotation(prices, universe)
    assert snap.momentum_spread_3m > 0


def test_decile_spread_helper_handles_short_input():
    assert _decile_spread([0.1, 0.2, 0.3]) == 0.0  # < 10 → 0


def test_empty_prices_raises():
    universe = _build_universe([("A000001", "X", 0)])
    with pytest.raises(ValueError, match="empty"):
        compute_sector_rotation(
            pd.DataFrame(columns=["date", "ticker", "close"]), universe,
        )
