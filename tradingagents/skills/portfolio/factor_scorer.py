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
# Stage 3 cluster-aware selection — timing overlay constants.
# 신호당 가감점 δ + 양방향 bound. backtest 튜닝 대상이라 named const로 노출.
TIMING_DELTA: float = 0.1
TIMING_CAP: float = 0.3


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
        # Jegadeesh-Titman skip-1m: cumulative return over `window` daily returns
        # ending at t-21. Matches `momentum_ranker.py` (Stage 1 technical) which
        # computes close[t-21]/close[t-21-window] - 1. Need window+21 returns.
        if n < window + 21:
            return None
        sub = r.iloc[-(window + 21):-21]
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
    """Z-score across tickers; tickers with None get 0 (neutral).

    Range is unbounded (extreme outliers can have z > +3). This causes
    "size dominance" in heterogeneous baskets where one factor's
    distribution is much wider than others. Use `_rank_normalize` for
    bounded, scale-invariant normalization.
    """
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


def _rank_normalize(values: dict[str, float | None]) -> dict[str, float]:
    """Rank-based percentile normalization → uniform [-0.5, +0.5].

    Worst value → -0.5, best value → +0.5. Ties get average rank.
    None / NaN tickers get 0 (median position — neutral).

    Compared to z-score:
      - Bounded range (∈ [-0.5, +0.5]) prevents extreme outliers from dominating
      - Scale-invariant: distributions with different spreads end up uniform
      - Loses information about magnitude (only relative order matters)

    Resolves the "size dominance" problem where one factor's z-range is
    much wider than others. With rank, all factors contribute equally
    per the weights — no implicit weighting via spread.
    """
    valid_items = [
        (k, float(v)) for k, v in values.items()
        if v is not None and not (isinstance(v, float) and math.isnan(v))
    ]
    if len(valid_items) < 2:
        return {k: 0.0 for k in values}

    # pandas rank with 'average' method handles ties gracefully
    s = pd.Series({k: v for k, v in valid_items})
    ranks = s.rank(method="average")
    n = len(ranks)
    # ranks ∈ [1, n] → normalize to [-0.5, +0.5]
    percentile = (ranks - 1) / (n - 1) - 0.5

    out: dict[str, float] = {k: 0.0 for k in values}
    for k in percentile.index:
        out[k] = float(percentile[k])
    return out


def score_candidates_with_components(
    panels: dict[str, FactorPanel],
    regime_quadrant: str | None,
    regime_confidence: float,
    normalization: str = "rank_percentile",
    *,
    risk_adjusted: dict | None = None,
    trend_quant: dict | None = None,
    extended: dict | None = None,
    etf_states: dict | None = None,
) -> tuple[dict[str, float], dict[str, dict], dict[str, float]]:
    """Same as score_candidates but also returns per-ticker breakdown + weights.

    Args:
        normalization: "rank_percentile" (default, bounded ∈ [-0.5, +0.5],
            scale-invariant — recommended) or "zscore" (legacy, unbounded).
        risk_adjusted, trend_quant, extended, etf_states: Stage 1 technical
            panels (optional). 미제공 시 현행 4-family score와 수학적으로 동일.
            제공 시 qual = mean(z(sharpe), z(sortino), z(calmar), z(-maxdd));
            mom = mean(z(skip1m), z(trend_strength), z(accel)); + timing overlay.

    Returns:
        scores:     ticker → composite base_score (+ timing overlay if extended/states)
        breakdown:  ticker → dict with raw values, normalized values, contributions, timing
        weights:    factor → blended regime weight (4 keys: mom/lowvol/qual/size)
    """
    if not panels:
        return {}, {}, blend_regime_weights(regime_quadrant, regime_confidence)

    # momentum core: mean of skip1m windows (현행).
    mom_values: dict[str, float | None] = {}
    for t, p in panels.items():
        windows = [p.skip1m_mom_3m, p.skip1m_mom_6m, p.skip1m_mom_12m]
        valid = [w for w in windows if w is not None]
        mom_values[t] = float(np.mean(valid)) if valid else None

    vol_values = {t: p.realized_vol_60d for t, p in panels.items()}
    sharpe_values = {t: p.sharpe_60d for t, p in panels.items()}
    size_values: dict[str, float | None] = {t: p.log_aum for t, p in panels.items()}

    if normalization == "rank_percentile":
        normalize = _rank_normalize
    elif normalization == "zscore":
        normalize = _zscore
    else:
        raise ValueError(
            f"unknown normalization {normalization!r} (expected 'rank_percentile' or 'zscore')"
        )

    n_mom_core = normalize(mom_values)
    n_vol = normalize(vol_values)
    n_qual_core = normalize(sharpe_values)
    n_size = normalize(size_values)

    # Stage 3: family enrichment — sub-composite = mean(normalized sub-signals).
    # 신호 누락(None) 시 해당 sub-signal 만 제외 후 mean.
    extra_qual: dict[str, list[float]] = {t: [] for t in panels}
    extra_mom: dict[str, list[float]] = {t: [] for t in panels}
    if risk_adjusted:
        n_sortino = normalize({
            t: getattr(risk_adjusted.get(t), "sortino_60d", None) for t in panels
        })
        n_calmar = normalize({
            t: getattr(risk_adjusted.get(t), "calmar_12m", None) for t in panels
        })
        n_neg_maxdd = normalize({
            t: (-getattr(risk_adjusted.get(t), "max_drawdown_12m", None)
                if risk_adjusted.get(t) is not None else None)
            for t in panels
        })
        for t in panels:
            extra_qual[t].extend([n_sortino[t], n_calmar[t], n_neg_maxdd[t]])
    if trend_quant:
        n_trend_strength = normalize({
            t: getattr(trend_quant.get(t), "trend_strength_score", None) for t in panels
        })
        n_accel = normalize({
            t: getattr(trend_quant.get(t), "momentum_acceleration", None) for t in panels
        })
        for t in panels:
            extra_mom[t].extend([n_trend_strength[t], n_accel[t]])

    n_mom: dict[str, float] = {
        t: float(np.mean([n_mom_core[t], *extra_mom[t]])) for t in panels
    }
    n_qual: dict[str, float] = {
        t: float(np.mean([n_qual_core[t], *extra_qual[t]])) for t in panels
    }

    weights = blend_regime_weights(regime_quadrant, regime_confidence)

    scores: dict[str, float] = {}
    breakdown: dict[str, dict] = {}
    for t in panels:
        contribs = {
            "mom":    weights["mom"]    * n_mom[t],
            "lowvol": weights["lowvol"] * (-n_vol[t]),
            "qual":   weights["qual"]   * n_qual[t],
            "size":   weights["size"]   * n_size[t],
        }
        base = sum(contribs.values())

        ext_t = extended.get(t) if extended else None
        timing = _timing_overlay(t, ext_t, etf_states, risk_adjusted)
        final_base = base + timing

        scores[t] = final_base
        breakdown[t] = {
            "raw": {
                "mom_value":    mom_values[t],
                "vol_value":    vol_values[t],
                "sharpe_value": sharpe_values[t],
                "size_value":   size_values[t],
            },
            "normalization": normalization,
            "normalized": {
                "mom":  n_mom[t],
                "vol":  n_vol[t],
                "qual": n_qual[t],
                "size": n_size[t],
                "mom_core": n_mom_core[t],
                "qual_core": n_qual_core[t],
                "mom_extras": extra_mom[t],
                "qual_extras": extra_qual[t],
            },
            "contributions": contribs,
            "timing": timing,
            "base_score":    base,
        }
    return scores, breakdown, weights


def score_candidates(
    panels: dict[str, FactorPanel],
    regime_quadrant: str | None,
    regime_confidence: float,
    normalization: str = "rank_percentile",
    *,
    risk_adjusted: dict | None = None,
    trend_quant: dict | None = None,
    extended: dict | None = None,
    etf_states: dict | None = None,
) -> dict[str, float]:
    """Compute composite score per ticker. Higher = better.

    Normalized values are computed across the input ticker set (typically one
    bucket's eligible pool), so scores are *relative* within the bucket.

    Optional Stage 1 technical panels enrich qual/mom families + apply timing
    overlay (Stage 3 cluster-aware selection). 미제공 시 현행과 동일.
    """
    scores, _, _ = score_candidates_with_components(
        panels, regime_quadrant, regime_confidence, normalization=normalization,
        risk_adjusted=risk_adjusted, trend_quant=trend_quant,
        extended=extended, etf_states=etf_states,
    )
    return scores


def _timing_overlay(
    ticker: str,
    extended,
    etf_states,
    risk_adjusted,
) -> float:
    """Bounded soft 가감점 (Stage 3 cluster-aware selection).

    누락 데이터는 0 기여. 반환 ∈ [-TIMING_CAP, +TIMING_CAP].
    - rsi/macd divergence: bearish 페널티 / bullish 보너스
    - bb_percent_b>1.0 OR mfi>80 OR stoch_k>80 → overbought 페널티
    - trend state ∈ {breakdown, downtrend} 페널티
    - is_mean_reversion_candidate 보너스
    """
    d = TIMING_DELTA
    score = 0.0
    if extended is not None:
        if extended.rsi_divergence == "bearish":
            score -= d
        elif extended.rsi_divergence == "bullish":
            score += d
        if extended.macd_divergence == "bearish":
            score -= d
        elif extended.macd_divergence == "bullish":
            score += d
        if (
            extended.bb_percent_b > 1.0
            or extended.mfi > 80.0
            or extended.stoch_k > 80.0
        ):
            score -= d
    if etf_states is not None:
        st = etf_states.get(ticker)
        st_val = getattr(st, "value", st)
        if st_val in ("breakdown", "downtrend"):
            score -= d
    if risk_adjusted is not None:
        ra = risk_adjusted.get(ticker)
        if ra is not None and getattr(ra, "is_mean_reversion_candidate", False):
            score += d
    return max(-TIMING_CAP, min(TIMING_CAP, score))


def select_diverse(
    ranked_tickers: list[str],
    returns: pd.DataFrame,
    n: int,
    correlation_threshold: float = 0.85,
    selection_trace: dict | None = None,
) -> list[str]:
    """Greedy correlation-aware selection.

    Walk down `ranked_tickers` (best first); accept a ticker only if its
    correlation with every already-accepted ticker is below threshold.
    Pad with remaining ranked tickers if fewer than n pass the filter.

    If `selection_trace` dict is provided, mutates it in place to record
    {ticker: {selected, reason, corr_max, corr_with}} for every walked ticker.
    """
    if n <= 0:
        return []
    selected: list[str] = []
    rejected_by_corr: set[str] = set()

    def _record(ticker, *, selected_flag, reason, corr_max=None, corr_with=None):
        if selection_trace is None:
            return
        selection_trace[ticker] = {
            "selected":  selected_flag,
            "reason":    reason,
            "corr_max":  corr_max,
            "corr_with": corr_with or [],
        }

    for ticker in ranked_tickers:
        if len(selected) >= n:
            break
        if not selected:
            selected.append(ticker)
            _record(ticker, selected_flag=True, reason="first pick")
            continue
        if ticker not in returns.columns:
            selected.append(ticker)
            _record(ticker, selected_flag=True,
                    reason="no return data — treated as orthogonal")
            continue
        max_corr = 0.0
        too_correlated_with: str | None = None
        corr_with: list[tuple[str, float]] = []
        for s in selected:
            if s not in returns.columns:
                continue
            c = returns[ticker].corr(returns[s])
            if pd.isna(c):
                continue
            ac = abs(float(c))
            corr_with.append((s, ac))
            if ac >= correlation_threshold:
                too_correlated_with = s
                max_corr = ac
                break
            max_corr = max(max_corr, ac)
        if too_correlated_with is None:
            selected.append(ticker)
            _record(ticker, selected_flag=True,
                    reason=f"passed corr filter (max={max_corr:.3f})",
                    corr_max=max_corr, corr_with=corr_with)
        else:
            rejected_by_corr.add(ticker)
            _record(ticker, selected_flag=False,
                    reason=f"corr {max_corr:.3f} ≥ {correlation_threshold:.3f} with {too_correlated_with}",
                    corr_max=max_corr, corr_with=corr_with)

    if len(selected) < n:
        for ticker in ranked_tickers:
            if ticker not in selected:
                selected.append(ticker)
                if selection_trace is not None and ticker in selection_trace:
                    prev = selection_trace[ticker]
                    prev["selected"] = True
                    prev["reason"] = f"padding fallback (was: {prev['reason']})"
                else:
                    _record(ticker, selected_flag=True,
                            reason="padding fallback (mandate-priority)")
                if len(selected) >= n:
                    break

    return selected
