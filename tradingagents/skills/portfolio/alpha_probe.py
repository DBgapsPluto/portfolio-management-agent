"""Shared alpha scoring for Stage 2 contract and Stage 3 selection (P1-1 B)."""
from __future__ import annotations

from datetime import date, timedelta

import pandas as pd

from tradingagents.dataflows.universe import Universe
from tradingagents.schemas.portfolio import BucketTarget
from tradingagents.skills.portfolio.candidate_selector import (
    _compute_alpha_scores,
    list_eligible_tickers,
)
from tradingagents.skills.portfolio.bucket_sync import compute_bucket_selectability
from tradingagents.skills.portfolio.returns_matrix import fetch_returns_matrix
from tradingagents.skills.research.factor_to_bucket import BUCKETS

PRICE_LOOKBACK_DAYS: int = 365 * 3


def compute_alpha_scores_for_eligible(
    universe: Universe,
    bucket_target: BucketTarget,
    as_of: date,
    *,
    returns: pd.DataFrame | None = None,
    factor_panel: dict | None = None,
    cache_path: str | None = None,
    regime_quadrant: str | None = None,
    regime_confidence: float = 0.5,
    dominant_scenario: str | None = None,
    factor_scores: dict[str, float] | None = None,
    risk_adjusted: dict | None = None,
    trend_quant: dict | None = None,
    extended: dict | None = None,
    etf_states: dict | None = None,
    boost_scale: float = 0.0,
) -> tuple[dict[str, list[str]], dict[str, dict[str, float]]]:
    """Returns (eligible_by_bucket, alpha_scores_by_bucket)."""
    eligible_by_bucket = list_eligible_tickers(universe, bucket_target, as_of=as_of)
    if returns is None:
        tickers = list({t for ts in eligible_by_bucket.values() for t in ts})
        start = as_of - timedelta(days=PRICE_LOOKBACK_DAYS)
        returns = fetch_returns_matrix(tickers, start, as_of, cache_path=cache_path)
    if returns is None or returns.empty:
        return eligible_by_bucket, {b: {} for b in BUCKETS}

    universe_at = universe.tradable_at(as_of)
    aum_lookup = {e.ticker: e.aum_krw for e in universe_at.etfs}
    alpha_by_bucket: dict[str, dict[str, float]] = {}

    for bucket in BUCKETS:
        tickers = eligible_by_bucket.get(bucket, [])
        if not tickers:
            alpha_by_bucket[bucket] = {}
            continue
        eligible = [e for e in universe_at.etfs if e.ticker in tickers]
        scores, _panels = _compute_alpha_scores(
            eligible,
            returns,
            aum_lookup,
            regime_quadrant,
            regime_confidence,
            precomputed_panel=factor_panel,
            dominant_scenario=dominant_scenario,
            factor_scores=factor_scores,
            risk_adjusted=risk_adjusted,
            trend_quant=trend_quant,
            extended=extended,
            etf_states=etf_states,
            boost_scale=boost_scale,
        )
        alpha_by_bucket[bucket] = dict(scores)

    return eligible_by_bucket, alpha_by_bucket


def n_selectable_from_alpha(
    eligible_by_bucket: dict[str, list[str]],
    alpha_scores_by_bucket: dict[str, dict[str, float]],
) -> dict[str, int]:
    return compute_bucket_selectability(
        eligible_by_bucket=eligible_by_bucket,
        alpha_scores_by_bucket=alpha_scores_by_bucket,
    )
