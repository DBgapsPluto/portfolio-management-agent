from datetime import date

import pandas as pd

from tradingagents.dataflows.universe import Universe
from tradingagents.schemas.portfolio import BucketTarget, CandidateSet
from tradingagents.schemas.technical import ETFRanking
from tradingagents.skills.portfolio.factor_scorer import (
    FactorPanel, compute_factor_panel, score_candidates, select_diverse,
)
from tradingagents.skills.registry import register_skill


# Map BucketTarget fields to universe categories
BUCKET_TO_CATEGORIES = {
    "kr_equity": ["국내주식_지수", "국내주식_섹터"],
    "global_equity": ["해외주식_지수", "해외주식_섹터"],
    "fx_commodity": ["FX 및 원자재"],
    "bond": [
        "국내채권_종합", "국내채권_회사채",
        "해외채권_종합", "해외채권_회사채",
    ],
    "cash_mmf": ["금리연계형/초단기채권"],
}


def list_eligible_tickers(
    universe: Universe,
    bucket_target: BucketTarget,
    as_of: date,
    min_aum_krw: float = 1_000_000_000_000,
) -> dict[str, list[str]]:
    """Return tickers passing hard filters (tradable + category + AUM), pre-ranking.

    Caller uses this to know which tickers need price/return data fetched
    before invoking the full select_etf_candidates with multi-factor mode.
    """
    universe = universe.tradable_at(as_of)
    out: dict[str, list[str]] = {}
    for bucket_name, weight in [
        ("kr_equity", bucket_target.kr_equity),
        ("global_equity", bucket_target.global_equity),
        ("fx_commodity", bucket_target.fx_commodity),
        ("bond", bucket_target.bond),
        ("cash_mmf", bucket_target.cash_mmf),
    ]:
        if weight <= 0:
            out[bucket_name] = []
            continue
        cats = BUCKET_TO_CATEGORIES[bucket_name]
        out[bucket_name] = [
            e.ticker for e in universe.etfs
            if e.category in cats and e.aum_krw >= min_aum_krw
        ]
    return out


@register_skill(name="select_etf_candidates", category="portfolio")
def select_etf_candidates(
    universe: Universe,
    bucket_target: BucketTarget,
    as_of: date,
    *,
    returns: pd.DataFrame,
    factor_panel: dict[str, FactorPanel],
    min_aum_krw: float = 1_000_000_000_000,  # 1조원 floor
    per_bucket_n: int = 5,
    regime_quadrant: str | None = None,
    regime_confidence: float = 0.5,
    correlation_threshold: float = 0.85,
    longlist_multiplier: int = 2,
) -> CandidateSet:
    """Filter universe by bucket target + AUM, then multi-factor rank + corr de-dup.

    Stage 1 technical_analyst가 항상 returns + factor_panel을 채우므로
    multi-factor mode가 유일한 운영 경로. legacy momentum-only mode는 폐기.

    Per D13: tradable_at(as_of) is applied first to avoid look-ahead bias.

    Required:
        returns: 후보 universe의 일별 returns matrix (corr de-dup 입력)
        factor_panel: Stage 1 technical_analyst가 산출한 ticker → FactorPanel dict
    """
    if returns is None or returns.empty:
        raise ValueError("returns matrix must be non-empty (Stage 1 dependency)")
    if not factor_panel:
        raise ValueError("factor_panel must be non-empty (Stage 1 dependency)")

    universe = universe.tradable_at(as_of)
    aum_lookup = {e.ticker: e.aum_krw for e in universe.etfs}

    bucket_to_tickers: dict[str, list[str]] = {}

    for bucket_name, weight in [
        ("kr_equity", bucket_target.kr_equity),
        ("global_equity", bucket_target.global_equity),
        ("fx_commodity", bucket_target.fx_commodity),
        ("bond", bucket_target.bond),
        ("cash_mmf", bucket_target.cash_mmf),
    ]:
        if weight <= 0:
            bucket_to_tickers[bucket_name] = []
            continue

        cats = BUCKET_TO_CATEGORIES[bucket_name]
        eligible = [
            e for e in universe.etfs
            if e.category in cats and e.aum_krw >= min_aum_krw
        ]
        if not eligible:
            bucket_to_tickers[bucket_name] = []
            continue

        ranked = _rank_by_factors(
            eligible, returns, aum_lookup,
            regime_quadrant, regime_confidence,
            precomputed_panel=factor_panel,
        )
        longlist_n = max(per_bucket_n * longlist_multiplier, per_bucket_n)
        longlist = ranked[:longlist_n]
        chosen = select_diverse(
            longlist, returns, n=per_bucket_n,
            correlation_threshold=correlation_threshold,
        )

        bucket_to_tickers[bucket_name] = chosen[:per_bucket_n]

    total = sum(len(v) for v in bucket_to_tickers.values())
    mode_label = (
        f"multi-factor (regime={regime_quadrant}, conf={regime_confidence:.2f})"
    )
    return CandidateSet(
        bucket_to_tickers=bucket_to_tickers,
        selection_criteria=(
            f"AUM ≥ {min_aum_krw / 1e12:.1f}조, mode={mode_label}, "
            f"per_bucket_n={per_bucket_n}, corr_thresh={correlation_threshold}"
        )[:300],
        total_candidates=max(total, 1),
    )


def _rank_by_factors(
    eligible,
    returns: pd.DataFrame,
    aum_lookup: dict[str, float],
    regime_quadrant: str | None,
    regime_confidence: float,
    precomputed_panel: dict[str, FactorPanel] | None = None,
) -> list[str]:
    """Compute composite factor scores for eligible tickers; return tickers sorted desc.

    If `precomputed_panel` is provided (from Stage 1 Technical Analyst), reuse
    those values and skip recomputation. Missing tickers fall back to local
    computation from `returns`.
    """
    panels = {}
    for e in eligible:
        if precomputed_panel is not None and e.ticker in precomputed_panel:
            panels[e.ticker] = precomputed_panel[e.ticker]
            continue
        if e.ticker not in returns.columns:
            panels[e.ticker] = compute_factor_panel(
                pd.Series(dtype=float), aum_lookup.get(e.ticker, e.aum_krw),
            )
            continue
        panels[e.ticker] = compute_factor_panel(
            returns[e.ticker], aum_lookup.get(e.ticker, e.aum_krw),
        )
    scores = score_candidates(panels, regime_quadrant, regime_confidence)
    return sorted(scores.keys(), key=lambda t: scores[t], reverse=True)


