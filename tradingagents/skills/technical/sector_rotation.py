"""Tier-4 — Sector rotation + correlation regime change.

카테고리 집계 모멘텀 + universe-level dispersion + 60d/252d correlation 차이.
"""
import numpy as np
import pandas as pd

from tradingagents.dataflows.universe import Universe
from tradingagents.schemas.technical import (
    CategoryMomentum, SectorRotationSnapshot,
)
from tradingagents.skills.registry import register_skill


def _mom_window(close: pd.Series, days: int) -> float | None:
    s = close.dropna()
    if len(s) < days + 1:
        return None
    return float(s.iloc[-1] / s.iloc[-days - 1] - 1.0)


def _decile_spread(values: list[float], pct: float = 0.1) -> float:
    """Top decile mean - bot decile mean."""
    arr = np.array([v for v in values if v is not None and not np.isnan(v)], dtype=float)
    if arr.size < 10:
        return 0.0
    arr.sort()
    k = max(1, int(round(arr.size * pct)))
    return float(arr[-k:].mean() - arr[:k].mean())


@register_skill(name="compute_sector_rotation", category="technical")
def compute_sector_rotation(
    prices: pd.DataFrame, universe: Universe,
) -> SectorRotationSnapshot:
    """카테고리 leadership + universe spread + correlation regime change."""
    pivot = prices.pivot(index="date", columns="ticker", values="close").sort_index()
    if pivot.empty:
        raise ValueError("empty price matrix")

    cat_lookup = {e.ticker: e.category for e in universe.etfs}

    per_ticker_3m: dict[str, float | None] = {}
    per_ticker_12m: dict[str, float | None] = {}
    for ticker in pivot.columns:
        s = pivot[ticker]
        per_ticker_3m[ticker] = _mom_window(s, 63)
        per_ticker_12m[ticker] = _mom_window(s, 252)

    cat_to_3m: dict[str, list[float]] = {}
    cat_to_12m: dict[str, list[float]] = {}
    for ticker, cat in cat_lookup.items():
        m3 = per_ticker_3m.get(ticker)
        m12 = per_ticker_12m.get(ticker)
        if m3 is not None:
            cat_to_3m.setdefault(cat, []).append(m3)
        if m12 is not None:
            cat_to_12m.setdefault(cat, []).append(m12)

    cat_entries: list[CategoryMomentum] = []
    for cat in sorted(set(cat_to_3m.keys()) | set(cat_to_12m.keys())):
        m3s = cat_to_3m.get(cat, [])
        m12s = cat_to_12m.get(cat, [])
        if not m3s and not m12s:
            continue
        cat_entries.append(CategoryMomentum(
            category=cat,
            n_etfs=max(len(m3s), len(m12s)),
            mean_mom_3m=float(np.mean(m3s)) if m3s else 0.0,
            mean_mom_12m=float(np.mean(m12s)) if m12s else 0.0,
            rank=1,
        ))
    cat_entries.sort(key=lambda c: -c.mean_mom_3m)
    for i, entry in enumerate(cat_entries, start=1):
        entry.rank = i

    leader = cat_entries[0].category if cat_entries else ""
    laggard = cat_entries[-1].category if cat_entries else ""

    spread = _decile_spread([v for v in per_ticker_3m.values() if v is not None])

    returns = pivot.pct_change()
    last_60 = returns.tail(60).dropna(axis=1, how="any")
    last_252 = returns.tail(252).dropna(axis=1, how="any")

    common_cols = [c for c in last_60.columns if c in last_252.columns]
    if len(common_cols) >= 5:
        corr_60 = last_60[common_cols].corr().fillna(0.0)
        corr_252 = last_252[common_cols].corr().fillna(0.0)
        iu = np.triu_indices_from(corr_60.values, k=1)
        med_60 = float(np.median(corr_60.values[iu]))
        med_252 = float(np.median(corr_252.values[iu]))
        if np.isnan(med_60):
            med_60 = 0.0
        if np.isnan(med_252):
            med_252 = 0.0
        med_60 = float(np.clip(med_60, -1.0, 1.0))
        med_252 = float(np.clip(med_252, -1.0, 1.0))
    else:
        med_60 = med_252 = 0.0

    corr_change = med_60 - med_252
    if corr_change > 0.1:
        corr_regime: str = "expansion"
    elif corr_change < -0.1:
        corr_regime = "compression"
    else:
        corr_regime = "stable"

    last_date = pivot.index[-1]
    source_date = (
        last_date.date() if hasattr(last_date, "date")
        else pd.Timestamp(last_date).date()
    )

    return SectorRotationSnapshot(
        categories=cat_entries,
        leader_category=leader,
        laggard_category=laggard,
        momentum_spread_3m=spread,
        correlation_median_60d=med_60,
        correlation_median_252d=med_252,
        correlation_change=corr_change,
        correlation_regime=corr_regime,  # type: ignore[arg-type]
        source_date=source_date,
    )
