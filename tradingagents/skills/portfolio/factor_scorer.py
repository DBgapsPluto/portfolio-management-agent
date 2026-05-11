"""Multi-factor scoring for candidate selection (조합 1).

Replaces pure momentum ranking with a regime-conditional composite of:
- momentum: 3m/6m/12m skip-1m (Jegadeesh-Titman style, avoids short-term reversal)
- low-vol:  realized 60d vol (penalized — high vol gets negative z-score)
- quality:  Sharpe-like (mean / vol)
- size:     log(AUM)

Factor weights are blended between regime-specific and equal-weight using
regime confidence — when confident, use regime weights; when not, fall back
to equal weights.

This module is stateless and pure: takes data in, returns scores out.
The candidate_selector wires it into the pipeline.
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd
from pydantic import BaseModel


# Factor weights per macro regime quadrant.
# Rationale:
# - growth_disinflation (Goldilocks): trend persists → heavy momentum
# - growth_inflation (overheating): valuation matters → balance momentum + quality
# - recession_inflation (stagflation): defensive → heavy low-vol + quality
# - recession_disinflation (deflationary recession): defensive → heaviest low-vol
# - unknown / low confidence: equal weight (no view)
REGIME_FACTOR_WEIGHTS: dict[str, dict[str, float]] = {
    "growth_disinflation":    {"mom": 0.50, "lowvol": 0.10, "qual": 0.25, "size": 0.15},
    "growth_inflation":       {"mom": 0.30, "lowvol": 0.15, "qual": 0.30, "size": 0.25},
    "recession_inflation":    {"mom": 0.10, "lowvol": 0.40, "qual": 0.30, "size": 0.20},
    "recession_disinflation": {"mom": 0.15, "lowvol": 0.45, "qual": 0.25, "size": 0.15},
    "unknown":                {"mom": 0.25, "lowvol": 0.25, "qual": 0.25, "size": 0.25},
}


class FactorPanel(BaseModel):
    """Raw per-ticker factor values, pre z-score.

    Computed by Stage 1 Technical Analyst (or by the selector as fallback).
    Z-scoring + regime weighting happens later in Stage 3 candidate selection.
    """
    skip1m_mom_3m: float | None = None
    skip1m_mom_6m: float | None = None
    skip1m_mom_12m: float | None = None
    realized_vol_60d: float | None = None
    sharpe_60d: float | None = None
    log_aum: float


def blend_regime_weights(
    quadrant: str | None, confidence: float,
) -> dict[str, float]:
    """Blend regime-specific weights with equal weights by confidence.

    confidence=1.0 → pure regime weights; confidence=0.0 → equal weights.
    Falls back to "unknown" (equal) if quadrant is None or not in table.
    """
    confidence = max(0.0, min(1.0, confidence))
    base = REGIME_FACTOR_WEIGHTS.get(quadrant or "unknown", REGIME_FACTOR_WEIGHTS["unknown"])
    equal = REGIME_FACTOR_WEIGHTS["unknown"]
    blended = {k: confidence * base[k] + (1.0 - confidence) * equal[k] for k in base}
    total = sum(blended.values())
    return {k: v / total for k, v in blended.items()}


def compute_factor_panel(
    ticker_returns: pd.Series, aum_krw: float,
) -> FactorPanel:
    """Compute raw factor values for one ticker.

    ticker_returns: daily simple returns (most recent last).
    Returns None for windows lacking enough data — caller handles via z-score nan-skip.
    """
    r = ticker_returns.dropna()
    n = len(r)

    def _skip1m_mom(window: int) -> float | None:
        # cumulative return from t-window to t-21 (skip last 21 trading days)
        if n < window + 1:
            return None
        sub = r.iloc[-window:-21] if window > 21 else r.iloc[-window:]
        if sub.empty:
            return None
        return float((1.0 + sub).prod() - 1.0)

    # realized vol and Sharpe over last 60 trading days
    if n >= 60:
        last60 = r.iloc[-60:]
        vol_daily = float(last60.std())
        vol_annual = vol_daily * math.sqrt(252) if vol_daily > 0 else None
        mean_daily = float(last60.mean())
        sharpe = (mean_daily * 252) / vol_annual if vol_annual else None
    else:
        vol_annual = None
        sharpe = None

    log_aum = math.log(max(aum_krw, 1.0))

    return FactorPanel(
        skip1m_mom_3m=_skip1m_mom(63),
        skip1m_mom_6m=_skip1m_mom(126),
        skip1m_mom_12m=_skip1m_mom(252),
        realized_vol_60d=vol_annual,
        sharpe_60d=sharpe,
        log_aum=log_aum,
    )


def _zscore(values: dict[str, float | None]) -> dict[str, float]:
    """Z-score across tickers; tickers with None get 0 (neutral)."""
    arr = np.array(
        [v for v in values.values() if v is not None and not math.isnan(v)],
        dtype=float,
    )
    if arr.size < 2:
        return {k: 0.0 for k in values}
    mu = float(arr.mean())
    sd = float(arr.std(ddof=0))
    if sd == 0.0:
        return {k: 0.0 for k in values}
    out: dict[str, float] = {}
    for k, v in values.items():
        if v is None or (isinstance(v, float) and math.isnan(v)):
            out[k] = 0.0
        else:
            out[k] = (v - mu) / sd
    return out


def score_candidates(
    panels: dict[str, FactorPanel],
    regime_quadrant: str | None,
    regime_confidence: float,
) -> dict[str, float]:
    """Compute composite score per ticker. Higher = better.

    Z-scores are computed across the input ticker set (typically one bucket's
    eligible pool), so scores are *relative* within the bucket.
    """
    if not panels:
        return {}

    # Composite momentum = mean of three skip-1m windows (where available)
    mom_values: dict[str, float | None] = {}
    for t, p in panels.items():
        windows = [p.skip1m_mom_3m, p.skip1m_mom_6m, p.skip1m_mom_12m]
        valid = [w for w in windows if w is not None]
        mom_values[t] = float(np.mean(valid)) if valid else None

    vol_values = {t: p.realized_vol_60d for t, p in panels.items()}
    sharpe_values = {t: p.sharpe_60d for t, p in panels.items()}
    size_values: dict[str, float | None] = {t: p.log_aum for t, p in panels.items()}

    z_mom = _zscore(mom_values)
    z_vol = _zscore(vol_values)  # higher vol = higher z; we'll negate below
    z_qual = _zscore(sharpe_values)
    z_size = _zscore(size_values)

    weights = blend_regime_weights(regime_quadrant, regime_confidence)

    scores: dict[str, float] = {}
    for t in panels:
        scores[t] = (
            weights["mom"]    * z_mom[t]
            + weights["lowvol"] * (-z_vol[t])     # low vol = high score
            + weights["qual"]   * z_qual[t]
            + weights["size"]   * z_size[t]
        )
    return scores


def select_diverse(
    ranked_tickers: list[str],
    returns: pd.DataFrame,
    n: int,
    correlation_threshold: float = 0.85,
) -> list[str]:
    """Greedy correlation-aware selection.

    Walk down `ranked_tickers` (best first); accept a ticker only if its
    correlation with every already-accepted ticker is below threshold.
    Pad with remaining ranked tickers if fewer than n pass the filter.
    """
    if n <= 0:
        return []
    selected: list[str] = []
    for ticker in ranked_tickers:
        if len(selected) >= n:
            break
        if not selected:
            selected.append(ticker)
            continue
        if ticker not in returns.columns:
            # No correlation data — accept (treated as orthogonal).
            selected.append(ticker)
            continue
        max_corr = 0.0
        too_correlated = False
        for s in selected:
            if s not in returns.columns:
                continue
            c = returns[ticker].corr(returns[s])
            if pd.isna(c):
                continue
            ac = abs(float(c))
            if ac >= correlation_threshold:
                too_correlated = True
                break
            max_corr = max(max_corr, ac)
        if not too_correlated:
            selected.append(ticker)

    if len(selected) < n:
        for ticker in ranked_tickers:
            if ticker not in selected:
                selected.append(ticker)
                if len(selected) >= n:
                    break

    return selected
