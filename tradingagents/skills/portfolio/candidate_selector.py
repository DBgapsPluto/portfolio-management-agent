from datetime import date

import pandas as pd

from tradingagents.dataflows.universe import Universe
from tradingagents.schemas.portfolio import BucketTarget, CandidateSet
from tradingagents.schemas.technical import ETFRanking
from tradingagents.skills.portfolio.factor_scorer import (
    FactorPanel, compute_factor_panel, score_candidates,
    score_candidates_with_components, select_diverse,
)
from tradingagents.skills.portfolio.sub_category import (
    _scenario_to_axes, compose_boost, log_boost,
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


# Sub_category별 minimum AUM 완화 — KR 시장에 large-AUM 옵션이 부족한
# sparse sub_category 한정. default min_aum_krw 대신 이 값 사용.
# 운영 capital 10억-100억 가정에서 안전 (포지션 < AUM의 5%).
_RELAXED_MIN_AUM_KRW: dict[str, float] = {
    "inflation_linked": 10_000_000_000,   # 100억 — KR TIPS 시장 매우 작음
}


# Scenario boost를 factor score에 가산할 때 곱하는 스케일.
# 1.0 = 원본 log_boost 그대로 (max +0.69). rank_percentile에서 boost ratio가
# factor 대비 ~136%까지 올라가지만, anchor 재평가 결과 시스템이 corr-aware로
# substitute (예: KOSPI200 = 암묵적 반도체) 잘 선정함이 확인되어 원복.
# 필요 시 파라미터로 0.5 등 조정 가능.
DEFAULT_BOOST_SCALE: float = 1.0


def _min_aum_for_etf(etf, default_threshold: float) -> float:
    """ETF의 sub_category에 따라 minimum AUM 결정.

    sub_category가 _RELAXED_MIN_AUM_KRW에 있으면 그 값과 default 중 작은 쪽 사용.
    그 외엔 default 그대로.
    """
    sc = etf.sub_category
    if sc and sc in _RELAXED_MIN_AUM_KRW:
        return min(default_threshold, _RELAXED_MIN_AUM_KRW[sc])
    return default_threshold


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
            if e.category in cats and e.aum_krw >= _min_aum_for_etf(e, min_aum_krw)
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
    longlist_multiplier: int = 3,
    dominant_scenario: str | None = None,
    attribution: dict | None = None,
    normalization: str = "rank_percentile",
    boost_scale: float = DEFAULT_BOOST_SCALE,
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

    if attribution is not None:
        attribution.setdefault("config", {})
        attribution["config"].update({
            "regime_quadrant":       regime_quadrant,
            "regime_confidence":     regime_confidence,
            "dominant_scenario":     dominant_scenario,
            "per_bucket_n":          per_bucket_n,
            "correlation_threshold": correlation_threshold,
            "longlist_multiplier":   longlist_multiplier,
            "min_aum_krw":           min_aum_krw,
        })
        attribution["buckets"] = {}

    for bucket_name, weight in [
        ("kr_equity", bucket_target.kr_equity),
        ("global_equity", bucket_target.global_equity),
        ("fx_commodity", bucket_target.fx_commodity),
        ("bond", bucket_target.bond),
        ("cash_mmf", bucket_target.cash_mmf),
    ]:
        bucket_attr: dict | None = None
        if attribution is not None:
            bucket_attr = {
                "bucket_weight":  weight,
                "skipped":        False,
                "eligible_count": 0,
            }
            attribution["buckets"][bucket_name] = bucket_attr

        if weight <= 0:
            bucket_to_tickers[bucket_name] = []
            if bucket_attr is not None:
                bucket_attr["skipped"] = True
                bucket_attr["skip_reason"] = "bucket_weight=0"
            continue

        cats = BUCKET_TO_CATEGORIES[bucket_name]
        eligible = [
            e for e in universe.etfs
            if e.category in cats and e.aum_krw >= _min_aum_for_etf(e, min_aum_krw)
        ]
        if bucket_attr is not None:
            bucket_attr["eligible_count"] = len(eligible)

        if not eligible:
            bucket_to_tickers[bucket_name] = []
            if bucket_attr is not None:
                bucket_attr["skipped"] = True
                bucket_attr["skip_reason"] = "no eligible tickers"
            continue

        if bucket_name == "bond" and bucket_target.bond_tips_share > 0.0:
            chosen = _select_bond_with_tips_quota(
                eligible, returns, aum_lookup,
                regime_quadrant, regime_confidence, factor_panel,
                dominant_scenario, per_bucket_n,
                correlation_threshold, longlist_multiplier,
                tips_share=bucket_target.bond_tips_share,
                breakdown_out=bucket_attr,
                normalization=normalization,
                boost_scale=boost_scale,
            )
        else:
            rank_break: dict | None = {} if bucket_attr is not None else None
            ranked = _rank_by_factors(
                eligible, returns, aum_lookup,
                regime_quadrant, regime_confidence,
                precomputed_panel=factor_panel,
                dominant_scenario=dominant_scenario,
                breakdown_out=rank_break,
                normalization=normalization,
                boost_scale=boost_scale,
            )
            longlist_n = max(per_bucket_n * longlist_multiplier, per_bucket_n)
            longlist = ranked[:longlist_n]
            sel_trace: dict | None = {} if bucket_attr is not None else None
            chosen = select_diverse(
                longlist, returns, n=per_bucket_n,
                correlation_threshold=correlation_threshold,
                selection_trace=sel_trace,
            )
            if bucket_attr is not None:
                bucket_attr["bond_split"] = False
                bucket_attr["ranked_order"] = ranked
                bucket_attr["longlist_n"] = longlist_n
                bucket_attr["regime_weights"] = (rank_break or {}).get("regime_weights")
                bucket_attr["scenario_axes"] = (rank_break or {}).get("scenario_axes")
                bucket_attr["per_ticker"] = (rank_break or {}).get("per_ticker", {})
                bucket_attr["selection_trace"] = sel_trace or {}
                bucket_attr["chosen"] = chosen[:per_bucket_n]

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


def _select_bond_with_tips_quota(
    eligible,
    returns: pd.DataFrame,
    aum_lookup: dict[str, float],
    regime_quadrant: str | None,
    regime_confidence: float,
    factor_panel: dict[str, FactorPanel],
    dominant_scenario: str | None,
    per_bucket_n: int,
    correlation_threshold: float,
    longlist_multiplier: int,
    tips_share: float,
    breakdown_out: dict | None = None,
    normalization: str = "rank_percentile",
    boost_scale: float = DEFAULT_BOOST_SCALE,
) -> list[str]:
    """bond bucket fill — inflation_linked sub_category에 quota 적용.

    eligible을 sub_category=inflation_linked vs 나머지로 split → 각각 rank +
    diverse select → tips_share 비율의 slot 채움. 한쪽이 부족하면 다른 쪽에서 보충.
    """
    tips_pool = [e for e in eligible if (e.sub_category or "") == "inflation_linked"]
    nominal_pool = [e for e in eligible if (e.sub_category or "") != "inflation_linked"]

    tips_quota = int(round(per_bucket_n * tips_share))
    nominal_quota = per_bucket_n - tips_quota

    sub_pool_breakdowns: dict[str, dict] = {}
    sub_pool_traces: dict[str, dict] = {}

    def _pick(pool, n: int, label: str) -> list[str]:
        if not pool or n <= 0:
            return []
        rank_break = {} if breakdown_out is not None else None
        ranked = _rank_by_factors(
            pool, returns, aum_lookup,
            regime_quadrant, regime_confidence,
            precomputed_panel=factor_panel,
            dominant_scenario=dominant_scenario,
            breakdown_out=rank_break,
            normalization=normalization,
            boost_scale=boost_scale,
        )
        longlist = ranked[:max(n * longlist_multiplier, n)]
        sel_trace = {} if breakdown_out is not None else None
        chosen = select_diverse(
            longlist, returns, n=n,
            correlation_threshold=correlation_threshold,
            selection_trace=sel_trace,
        )[:n]
        if breakdown_out is not None:
            sub_pool_breakdowns[label] = rank_break or {}
            sub_pool_traces[label] = sel_trace or {}
            sub_pool_breakdowns[label]["ranked_order"] = ranked
            sub_pool_breakdowns[label]["longlist_n"] = len(longlist)
            sub_pool_breakdowns[label]["chosen"] = chosen
        return chosen

    tips_picks = _pick(tips_pool, tips_quota, "tips")
    nominal_picks = _pick(nominal_pool, nominal_quota, "nominal")

    # Shortfall fallback — 한쪽 quota 못 채우면 다른 쪽에서 보충.
    tips_short = tips_quota - len(tips_picks)
    if tips_short > 0:
        extra = _pick(nominal_pool, len(nominal_picks) + tips_short, "nominal_fallback")
        seen = set(nominal_picks)
        for t in extra:
            if t not in seen:
                nominal_picks.append(t); seen.add(t)
                if len(nominal_picks) >= nominal_quota + tips_short:
                    break
    nominal_short = nominal_quota - len(nominal_picks)
    if nominal_short > 0:
        extra = _pick(tips_pool, len(tips_picks) + nominal_short, "tips_fallback")
        seen = set(tips_picks)
        for t in extra:
            if t not in seen:
                tips_picks.append(t); seen.add(t)
                if len(tips_picks) >= tips_quota + nominal_short:
                    break

    if breakdown_out is not None:
        breakdown_out["bond_split"] = True
        breakdown_out["tips_share"] = tips_share
        breakdown_out["tips_quota"] = tips_quota
        breakdown_out["nominal_quota"] = nominal_quota
        breakdown_out["sub_pools"] = sub_pool_breakdowns
        breakdown_out["selection_traces"] = sub_pool_traces
        breakdown_out["tips_picks"] = tips_picks
        breakdown_out["nominal_picks"] = nominal_picks

    return tips_picks + nominal_picks


def _rank_by_factors(
    eligible,
    returns: pd.DataFrame,
    aum_lookup: dict[str, float],
    regime_quadrant: str | None,
    regime_confidence: float,
    precomputed_panel: dict[str, FactorPanel] | None = None,
    dominant_scenario: str | None = None,
    breakdown_out: dict | None = None,
    normalization: str = "rank_percentile",
    boost_scale: float = DEFAULT_BOOST_SCALE,
) -> list[str]:
    """Compute composite factor scores for eligible tickers; return tickers sorted desc.

    If `precomputed_panel` is provided (from Stage 1 Technical Analyst), reuse
    those values and skip recomputation. Missing tickers fall back to local
    computation from `returns`.

    Phase C: dominant_scenario가 있고 ETF의 sub_category가 채워져 있으면
    log_boost를 score에 가산해서 시나리오 친화 sub_category에 가중치 부여.

    If `breakdown_out` dict is provided, mutates it in place to record per-ticker
    factor decomposition (raw values, z-scores, contributions, scenario boost,
    final_score) + regime weights + scenario coords.
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

    scores, breakdown, regime_weights = score_candidates_with_components(
        panels, regime_quadrant, regime_confidence,
        normalization=normalization,
    )

    # Scenario boost — ETF에 sub_category 있고 dominant_scenario가 boost 정의돼
    # 있는 경우만 가산.
    sub_cat_lookup = {e.ticker: e.sub_category for e in eligible}
    scenario_coords = _scenario_to_axes(dominant_scenario) if dominant_scenario else None
    composed_for_scenario = (
        compose_boost(*scenario_coords) if scenario_coords else {}
    )

    for ticker in list(scores):
        sub_cat = sub_cat_lookup.get(ticker)
        boost_log = log_boost(dominant_scenario, sub_cat) if dominant_scenario else 0.0
        boost_applied = boost_scale * boost_log
        scores[ticker] = scores[ticker] + boost_applied
        if breakdown_out is not None and ticker in breakdown:
            mult = (
                composed_for_scenario.get(sub_cat, 1.0)
                if (scenario_coords and sub_cat) else 1.0
            )
            breakdown[ticker]["sub_category"] = sub_cat
            breakdown[ticker]["scenario_boost"] = {
                "scenario":      dominant_scenario,
                "axes":          list(scenario_coords) if scenario_coords else None,
                "composed_mult": mult,
                "log_boost":     boost_log,        # raw, 스케일 적용 전
                "boost_scale":   boost_scale,
                "boost_applied": boost_applied,    # base에 실제 더해진 값
            }
            breakdown[ticker]["final_score"] = scores[ticker]

    if breakdown_out is not None:
        breakdown_out["regime_weights"] = regime_weights
        breakdown_out["scenario_axes"] = (
            list(scenario_coords) if scenario_coords else None
        )
        breakdown_out["per_ticker"] = breakdown

    return sorted(scores.keys(), key=lambda t: scores[t], reverse=True)


