import logging
import time
from datetime import date, timedelta

import pandas as pd

from tradingagents.dataflows.etf_metrics import (
    DEFAULT_METRICS_WINDOW_DAYS, compute_premium_discount_median,
    compute_tracking_error_12m, compute_volume_per_aum_median,
    fetch_etf_metrics_window,
)
from tradingagents.dataflows.krx_openapi import KRXOpenAPIError
from tradingagents.dataflows.universe import Universe
from tradingagents.schemas.llm_overlay import Stage3CandidateBoostView
from tradingagents.schemas.portfolio import BucketTarget, CandidateSet
from tradingagents.schemas.technical import ETFRanking
from tradingagents.skills.portfolio.factor_scorer import (
    FactorPanel, compute_adaptive_n_max, compute_factor_panel, compute_impl_score,
    score_candidates, score_candidates_with_components, select_by_enb_greedy,
    select_diverse,
)
from tradingagents.skills.portfolio.sub_category import (
    _scenario_to_axes, bucket_for_etf, compose_boost, log_boost,
)
from tradingagents.skills.registry import register_skill

logger = logging.getLogger(__name__)

# Scenario boost를 factor score에 가산할 때 곱하는 스케일.
# 1.0 = 원본 log_boost 그대로 (max +0.69). rank_percentile에서 boost ratio가
# factor 대비 ~136%까지 올라가지만, anchor 재평가 결과 시스템이 corr-aware로
# substitute (예: KOSPI200 = 암묵적 반도체) 잘 선정함이 확인되어 원복.
# 필요 시 파라미터로 0.5 등 조정 가능.
DEFAULT_BOOST_SCALE: float = 1.0
DEFAULT_LLM_CANDIDATE_BOOST_CAP: float = 0.08


def apply_llm_candidate_boost(
    *,
    alpha_scores: dict[str, float],
    ticker_to_sub_category: dict[str, str | None],
    llm_candidate_view: Stage3CandidateBoostView | None,
    allowed_tickers: set[str],
    boost_cap: float = DEFAULT_LLM_CANDIDATE_BOOST_CAP,
) -> tuple[dict[str, float], dict[str, dict]]:
    """Apply bounded LLM narrative boost to candidate alpha scores.

    This is score-only. It cannot add unsupported tickers and cannot turn a
    non-positive quant alpha into a positive alpha eligible for selection.
    """
    if llm_candidate_view is None:
        return dict(alpha_scores), {}

    cap = max(0.0, float(boost_cap))
    confidence = max(0.0, min(1.0, float(llm_candidate_view.confidence)))
    allowed_boosts = llm_candidate_view.filtered_ticker_boosts(allowed_tickers)
    boosted = dict(alpha_scores)
    audit: dict[str, dict] = {}

    for ticker in allowed_tickers:
        if ticker not in boosted:
            continue
        ticker_dir = allowed_boosts.get(ticker, 0.0)
        sub_category = ticker_to_sub_category.get(ticker)
        sub_dir = (
            llm_candidate_view.subcategory_boosts.get(sub_category, 0.0)
            if sub_category else 0.0
        )
        if ticker_dir == 0.0 and sub_dir == 0.0:
            continue
        raw_direction = ticker_dir + sub_dir
        raw_boost = confidence * cap * raw_direction
        clipped_boost = float(max(-cap, min(cap, raw_boost)))
        original = boosted[ticker]
        candidate_score = original + clipped_boost
        crossed_positive = original <= 0.0 < candidate_score
        if crossed_positive:
            candidate_score = 0.0
        boosted[ticker] = candidate_score
        audit[ticker] = {
            "original_score": original,
            "ticker_direction": ticker_dir,
            "subcategory": sub_category,
            "subcategory_direction": sub_dir,
            "confidence": confidence,
            "raw_boost": raw_boost,
            "clipped_boost": clipped_boost,
            "final_score": candidate_score,
            "crossed_positive_alpha": crossed_positive,
        }

    return boosted, audit



def _eligible_for_bucket(universe: Universe, bucket_name: str):
    """ETFs that classify into `bucket_name` via bucket_for_etf().

    8-bucket eligibility (Stage 3 D2/D3 — used by both list_* and select_*).
    bucket_for_etf() handles sub_category disambiguation for split buckets
    (FX 및 원자재 → precious_metals vs cyclical_commodity_fx; 국내채권_종합/
    해외채권_종합 → kr_bond / credit / global_duration).
    """
    return [e for e in universe.etfs if bucket_for_etf(e) == bucket_name]


def list_eligible_tickers(
    universe: Universe,
    bucket_target: BucketTarget,
    as_of: date,
) -> dict[str, list[str]]:
    """Return tickers passing hard filters (tradable + category), pre-ranking.

    Caller uses this to know which tickers need price/return data fetched
    before invoking the full select_etf_candidates with multi-factor mode.
    """
    universe = universe.tradable_at(as_of)
    out: dict[str, list[str]] = {}
    for bucket_name, weight in bucket_target.items():
        if bucket_name == "bond_tips_share":
            continue
        if weight <= 0:
            out[bucket_name] = []
            continue
        out[bucket_name] = [e.ticker for e in _eligible_for_bucket(universe, bucket_name)]
    return out


def build_quant_longlists_for_llm(
    universe: Universe,
    bucket_target: BucketTarget,
    as_of: date,
    *,
    returns: pd.DataFrame,
    factor_panel: dict[str, FactorPanel],
    max_per_bucket: int = 8,
    regime_quadrant: str | None = None,
    regime_confidence: float = 0.5,
    dominant_scenario: str | None = None,
    factor_scores: dict[str, float] | None = None,
    risk_adjusted: dict | None = None,
    trend_quant: dict | None = None,
    extended: dict | None = None,
    etf_states: dict | None = None,
) -> dict[str, list[dict]]:
    """Quant-ranked longlists for Stage 3 LLM (no ENB selection — single-pass allocator)."""
    universe = universe.tradable_at(as_of)
    aum_lookup = {e.ticker: e.aum_krw for e in universe.etfs}
    out: dict[str, list[dict]] = {}
    for bucket_name, weight in bucket_target.items():
        if bucket_name == "bond_tips_share" or weight <= 0:
            continue
        eligible = _eligible_for_bucket(universe, bucket_name)
        if not eligible:
            continue
        alpha_scores, _panels = _compute_alpha_scores(
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
        )
        ranked = sorted(
            alpha_scores.keys(), key=lambda t: alpha_scores[t], reverse=True,
        )
        sub_lookup = {e.ticker: e.sub_category for e in eligible}
        rows = []
        for ticker in ranked[:max_per_bucket]:
            rows.append({
                "ticker": ticker,
                "sub_category": sub_lookup.get(ticker),
                "alpha_score": alpha_scores.get(ticker),
                "impl_score": None,
            })
        if rows:
            out[bucket_name] = rows
    return out


@register_skill(name="select_etf_candidates", category="portfolio")
def select_etf_candidates(
    universe: Universe,
    bucket_target: BucketTarget,
    as_of: date,
    *,
    returns: pd.DataFrame,
    factor_panel: dict[str, FactorPanel],
    sigma: pd.DataFrame,
    capital_krw: float,
    regime_quadrant: str | None = None,
    regime_confidence: float = 0.5,
    correlation_threshold: float = 0.85,
    longlist_multiplier: int = 3,
    dominant_scenario: str | None = None,
    attribution: dict | None = None,
    normalization: str = "rank_percentile",
    boost_scale: float = DEFAULT_BOOST_SCALE,
    risk_adjusted: dict | None = None,
    trend_quant: dict | None = None,
    extended: dict | None = None,
    etf_states: dict | None = None,
    clusters: list | None = None,
    factor_scores: dict[str, float] | None = None,
    llm_candidate_view: Stage3CandidateBoostView | None = None,
    llm_candidate_boost_cap: float = DEFAULT_LLM_CANDIDATE_BOOST_CAP,
    require_positive_alpha: bool = True,
    precomputed_alpha_scores_by_bucket: dict[str, dict[str, float]] | None = None,
) -> CandidateSet:
    """Filter universe by bucket target, then multi-factor rank + corr de-dup.

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
    # 2026-05-26 #1 fix — underlying_index 매핑 (cluster_aware 의 강제 merge 용).
    underlying_lookup = {
        e.ticker: (e.underlying_index or "") for e in universe.etfs
    }

    # Phase 2a — ETF metrics fetch (impl_score 4-요소 입력)
    metrics_window_start = as_of - timedelta(days=DEFAULT_METRICS_WINDOW_DAYS)
    fetch_start_time = time.monotonic()
    cache_path_obj = None  # 기본 None — caller 가 주입할 수 있도록 향후 확장
    etf_metrics = None
    fetch_succeeded = False
    fallback_reason: str | None = None
    try:
        etf_metrics = fetch_etf_metrics_window(
            list({e.ticker for e in universe.etfs}),
            metrics_window_start, as_of,
            cache_path=cache_path_obj,
        )
        fetch_succeeded = True
    except KRXOpenAPIError as e:
        logger.warning(
            "KRX OpenAPI fetch failed (%s) — impl_score falls back to log_aum only", e,
        )
        fallback_reason = str(e)
    except Exception as e:  # noqa: BLE001
        logger.warning(
            "etf_metrics fetch failed unexpectedly (%s) — impl_score falls back", e,
        )
        fallback_reason = str(e)
    fetch_duration = time.monotonic() - fetch_start_time

    tracking_error_by_ticker: dict[str, float | None] | None = None
    prem_disc_by_ticker: dict[str, float | None] | None = None
    vol_aum_by_ticker: dict[str, float | None] | None = None
    if etf_metrics is not None and not etf_metrics.empty:
        elig_tickers_all = [e.ticker for e in universe.etfs]
        tracking_error_by_ticker = {
            t: compute_tracking_error_12m(etf_metrics, t)
            for t in elig_tickers_all
        }
        prem_disc_by_ticker = {
            t: compute_premium_discount_median(etf_metrics, t, n_days=30)
            for t in elig_tickers_all
        }
        vol_aum_by_ticker = {
            t: compute_volume_per_aum_median(etf_metrics, t, n_days=30)
            for t in elig_tickers_all
        }

    if attribution is not None:
        attribution["etf_metrics_summary"] = {
            "fetch_attempted": True,
            "fetch_succeeded": fetch_succeeded,
            "fallback_reason": fallback_reason,
            "n_tickers_with_te": (
                sum(1 for v in (tracking_error_by_ticker or {}).values() if v is not None)
            ),
            "n_tickers_with_pd": (
                sum(1 for v in (prem_disc_by_ticker or {}).values() if v is not None)
            ),
            "n_tickers_with_vol_aum": (
                sum(1 for v in (vol_aum_by_ticker or {}).values() if v is not None)
            ),
            "fetch_duration_seconds": float(fetch_duration),
        }

    bucket_to_tickers: dict[str, list[str]] = {}

    if attribution is not None:
        attribution.setdefault("config", {})
        attribution["config"].update({
            "regime_quadrant":       regime_quadrant,
            "regime_confidence":     regime_confidence,
            "dominant_scenario":     dominant_scenario,
            "capital_krw":           capital_krw,
            "correlation_threshold": correlation_threshold,
            "longlist_multiplier":   longlist_multiplier,
        })
        if precomputed_alpha_scores_by_bucket is not None:
            attribution["config"]["alpha_source"] = "stage2_precomputed"
        attribution["buckets"] = {}

    # Iterate over all 8 buckets from the BucketTarget dict.
    # TIPS quota applies to global_duration (which holds inflation_linked ETFs).
    for bucket_name, weight in bucket_target.items():
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

        eligible = _eligible_for_bucket(universe, bucket_name)
        if bucket_attr is not None:
            bucket_attr["eligible_count"] = len(eligible)

        if not eligible:
            bucket_to_tickers[bucket_name] = []
            if bucket_attr is not None:
                bucket_attr["skipped"] = True
                bucket_attr["skip_reason"] = "no eligible tickers"
            continue

        if bucket_name == "global_duration" and bucket_target.bond_tips_share > 0.0:
            bond_eligible_tickers = [e.ticker for e in eligible]
            # Use eligible count as n_positive_alpha upper bound — bond TIPS path
            # uses select_diverse (not ENB greedy), so alpha sign filter is not applied.
            bond_n = compute_adaptive_n_max(
                n_positive_alpha=len(bond_eligible_tickers),
                bucket_weight=weight,
                capital_krw=capital_krw,
            )
            chosen = _select_bond_with_tips_quota(
                eligible, returns, aum_lookup,
                regime_quadrant, regime_confidence, factor_panel,
                dominant_scenario, bond_n,
                correlation_threshold, longlist_multiplier,
                tips_share=bucket_target.bond_tips_share,
                breakdown_out=bucket_attr,
                normalization=normalization,
                boost_scale=boost_scale,
            )
        else:
            rank_break: dict | None = {} if bucket_attr is not None else None
            if precomputed_alpha_scores_by_bucket is not None:
                bucket_pre = precomputed_alpha_scores_by_bucket.get(bucket_name) or {}
                eligible_tickers = [e.ticker for e in eligible]
                alpha_scores = {
                    t: float(bucket_pre.get(t, 0.0)) for t in eligible_tickers
                }
                panels_for_impl = _build_panels(
                    eligible, returns, aum_lookup, factor_panel,
                )
                if bucket_attr is not None:
                    bucket_attr["alpha_source"] = "stage2_precomputed"
            else:
                alpha_scores, panels_for_impl = _compute_alpha_scores(
                    eligible, returns, aum_lookup,
                    regime_quadrant, regime_confidence,
                    precomputed_panel=factor_panel,
                    dominant_scenario=dominant_scenario,
                    breakdown_out=rank_break,
                    normalization=normalization,
                    boost_scale=boost_scale,
                    risk_adjusted=risk_adjusted, trend_quant=trend_quant,
                    extended=extended, etf_states=etf_states,
                    factor_scores=factor_scores,
                    llm_candidate_view=llm_candidate_view,
                    llm_candidate_boost_cap=llm_candidate_boost_cap,
                )
            impl_scores = compute_impl_score(
                panels_for_impl,
                normalization=normalization,
                volume_per_aum=vol_aum_by_ticker,
                premium_discount=prem_disc_by_ticker,
                tracking_error=tracking_error_by_ticker,
            )
            ranked = sorted(
                alpha_scores.keys(), key=lambda t: alpha_scores[t], reverse=True,
            )
            # Phase 2b — adaptive n_max + ENB greedy
            bucket_eligible_tickers = [e.ticker for e in eligible]
            n_positive_alpha = sum(
                1 for t in bucket_eligible_tickers if alpha_scores.get(t, 0.0) > 0
            )
            n_max = compute_adaptive_n_max(
                n_positive_alpha=n_positive_alpha,
                bucket_weight=weight,
                capital_krw=capital_krw,
            )
            sigma_sub = sigma.reindex(
                index=bucket_eligible_tickers, columns=bucket_eligible_tickers,
            ).dropna(how="all").dropna(axis=1, how="all")
            valid_eligible = [t for t in bucket_eligible_tickers if t in sigma_sub.index]
            selection_trace: dict = {}
            chosen = select_by_enb_greedy(
                eligible=valid_eligible,
                alpha_scores=alpha_scores,
                impl_scores=impl_scores,
                sigma=sigma_sub,
                n_max=n_max,
                selection_trace=selection_trace,
            )
            n_max_components = {
                "n_positive_alpha": n_positive_alpha,
                "weight_cap": max(1, int(weight / 0.025)) if weight > 0 else 0,
                "capital_cap": max(1, int(weight * capital_krw / 50_000_000)) if weight > 0 else 0,
                "abs_max": 8,
                "n_max_chosen": n_max,
            }
            selection_trace["n_max_components"] = n_max_components
            if bucket_attr is not None:
                bucket_attr["bond_split"] = False
                bucket_attr["ranked_order"] = ranked
                bucket_attr["alpha_scores"] = alpha_scores
                bucket_attr["impl_scores"] = impl_scores
                bucket_attr["regime_weights"] = (rank_break or {}).get("regime_weights")
                bucket_attr["scenario_axes"] = (rank_break or {}).get("scenario_axes")
                bucket_attr["per_ticker"] = (rank_break or {}).get("per_ticker", {})
                bucket_attr["selection_trace"] = selection_trace
                bucket_attr["n_max_computed"] = n_max
                bucket_attr["chosen"] = chosen

        bucket_to_tickers[bucket_name] = chosen

    total = sum(len(v) for v in bucket_to_tickers.values())
    mode_label = (
        f"multi-factor (regime={regime_quadrant}, conf={regime_confidence:.2f})"
    )
    return CandidateSet(
        bucket_to_tickers=bucket_to_tickers,
        selection_criteria=(
            f"mode={mode_label}, capital={capital_krw/1e9:.1f}B KRW, strategy=enb_greedy"
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
        # NEW: bucket level merged alpha_scores — cash_spillover._collect_alpha_scores_per_bucket 가 사용
        merged_alpha: dict[str, float] = {}
        for label, sp in sub_pool_breakdowns.items():
            per_t = sp.get("per_ticker") or {}
            for t, info in per_t.items():
                score = info.get("final_score")
                if score is None:
                    score = info.get("base_score", 0.0)
                merged_alpha[t] = float(score)
        breakdown_out["alpha_scores"] = merged_alpha

    return tips_picks + nominal_picks


def _build_panels(
    eligible, returns: pd.DataFrame, aum_lookup: dict[str, float],
    precomputed_panel: dict[str, FactorPanel] | None,
) -> dict[str, FactorPanel]:
    """eligible ETF 의 FactorPanel dict — precomputed 우선, 누락 시 returns 로 fallback."""
    panels: dict[str, FactorPanel] = {}
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
    return panels


def _compute_alpha_scores(
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
    risk_adjusted: dict | None = None,
    trend_quant: dict | None = None,
    extended: dict | None = None,
    etf_states: dict | None = None,
    factor_scores: dict[str, float] | None = None,
    llm_candidate_view: Stage3CandidateBoostView | None = None,
    llm_candidate_boost_cap: float = DEFAULT_LLM_CANDIDATE_BOOST_CAP,
) -> tuple[dict[str, float], dict[str, FactorPanel]]:
    """alpha scores dict + panel dict 반환. scenario boost 가산 포함."""
    panels = _build_panels(eligible, returns, aum_lookup, precomputed_panel)

    scores, breakdown, regime_weights = score_candidates_with_components(
        panels, regime_quadrant, regime_confidence,
        normalization=normalization,
        risk_adjusted=risk_adjusted, trend_quant=trend_quant,
        extended=extended, etf_states=etf_states,
    )

    sub_cat_lookup = {e.ticker: e.sub_category for e in eligible}
    scenario_coords = _scenario_to_axes(dominant_scenario) if dominant_scenario else None
    composed_for_scenario = (
        compose_boost(*scenario_coords) if scenario_coords else {}
    )

    # 2026-05-26 fix-B — macro alignment boost.
    # F2_inflation z 가 + 면 fx_commodity 의 inflation_hedge group (gold/oil
    # /agricultural/broad_commodity) alpha 에 boost. 평가의 "엔선물 11% 인플레
    # 헤지 라벨 사기" 비판에 root-level 응답.
    # F5_credit_cycle z 가 - 면 (신용 약세) safe_haven group (usd_fx/jpy_fx) 도
    # 부분 boost — carry unwind / dollar smile 환경.
    from tradingagents.skills.portfolio.sub_category import fx_subcategory_group
    f2_z = (factor_scores or {}).get("F2_inflation", 0.0)
    f5_z = (factor_scores or {}).get("F5_credit_cycle", 0.0)
    # boost coefficient: f2_z=+1 → +0.15 log boost ≈ ×1.16 multiplier
    INFLATION_HEDGE_COEF = 0.15
    SAFE_HAVEN_COEF = 0.10

    for ticker in list(scores):
        sub_cat = sub_cat_lookup.get(ticker)
        boost_log = log_boost(dominant_scenario, sub_cat) if dominant_scenario else 0.0
        boost_applied = boost_scale * boost_log

        # fx_commodity 의미 group boost (F2 / F5 기반).
        fx_group = fx_subcategory_group(sub_cat)
        macro_align_boost = 0.0
        if fx_group == "inflation_hedge" and f2_z > 0:
            macro_align_boost = INFLATION_HEDGE_COEF * f2_z
        elif fx_group == "safe_haven" and f5_z < 0:
            # F5 음수 (신용 약세) → safe_haven boost. f5_z=-1 → +0.10 boost.
            macro_align_boost = SAFE_HAVEN_COEF * (-f5_z)

        scores[ticker] = scores[ticker] + boost_applied + macro_align_boost
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
                "log_boost":     boost_log,
                "boost_scale":   boost_scale,
                "boost_applied": boost_applied,
            }
            if macro_align_boost != 0.0:
                breakdown[ticker]["macro_align_boost"] = {
                    "fx_group": fx_group,
                    "f2_z": float(f2_z),
                    "f5_z": float(f5_z),
                    "boost": float(macro_align_boost),
                }
            breakdown[ticker]["final_score"] = scores[ticker]

    scores, llm_boost_audit = apply_llm_candidate_boost(
        alpha_scores=scores,
        ticker_to_sub_category=sub_cat_lookup,
        llm_candidate_view=llm_candidate_view,
        allowed_tickers=set(scores),
        boost_cap=llm_candidate_boost_cap,
    )
    if llm_boost_audit and breakdown_out is not None:
        breakdown_out["llm_candidate_boost"] = llm_boost_audit
        for ticker, audit in llm_boost_audit.items():
            if ticker in breakdown:
                breakdown[ticker]["llm_candidate_boost"] = audit
                breakdown[ticker]["final_score"] = scores[ticker]

    if breakdown_out is not None:
        breakdown_out["regime_weights"] = regime_weights
        breakdown_out["scenario_axes"] = (
            list(scenario_coords) if scenario_coords else None
        )
        breakdown_out["per_ticker"] = breakdown
    return scores, panels


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
    risk_adjusted: dict | None = None,
    trend_quant: dict | None = None,
    extended: dict | None = None,
    etf_states: dict | None = None,
) -> list[str]:
    """Compute composite factor scores for eligible tickers; return tickers sorted desc.

    bond bucket path 호환용 wrapper — Stage 3 cluster-aware 경로는 직접
    `_compute_alpha_scores` 를 호출해서 scores dict 를 받음.
    """
    scores, _panels = _compute_alpha_scores(
        eligible, returns, aum_lookup, regime_quadrant, regime_confidence,
        precomputed_panel=precomputed_panel,
        dominant_scenario=dominant_scenario,
        breakdown_out=breakdown_out,
        normalization=normalization, boost_scale=boost_scale,
        risk_adjusted=risk_adjusted, trend_quant=trend_quant,
        extended=extended, etf_states=etf_states,
    )

    return sorted(scores.keys(), key=lambda t: scores[t], reverse=True)


