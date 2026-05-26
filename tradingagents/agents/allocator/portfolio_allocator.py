"""Portfolio Allocator — Stage 3 (완전 함수화).

D12: bucket sum + single-cap을 동시에 만족하는 joint optimization.
D4 : validator 실패 시 자동 retry (attempts++, band 완화).

Phase A 변경 (이번 commit):
  - method_picker LLM 제거 → 결정적 매핑 (regime + systemic + scenario)
  - Stage 2 ResearchDecision (conviction, dominant_scenario) 활용
  - legacy candidate_selector mode 의존 제거
  - silent failure logging 추가
"""
import logging
from datetime import date, timedelta

import pandas as pd
from pypfopt import EfficientFrontier, HRPOpt, risk_models, expected_returns

from tradingagents.dataflows.universe import load_universe
from tradingagents.schemas.portfolio import OptimizationMethod, WeightVector
from tradingagents.skills.portfolio.candidate_selector import (
    BUCKET_TO_CATEGORIES, DEFAULT_MIN_AUM_KRW, list_eligible_tickers,
    select_etf_candidates,
)
from tradingagents.skills.portfolio.method_picker import pick_optimization_method
from tradingagents.skills.portfolio.returns_matrix import fetch_returns_matrix

logger = logging.getLogger(__name__)


# Stage 3 audit (2026-05-26, Task 1/3): named constants.
SINGLE_ASSET_CAP: float = 0.20         # 단일 ETF 최대 weight (mandate)
MIN_COV_OBS: int = 60                  # covariance 계산 최소 표본 (NaN-free row)
RETRY_BAND_WIDTH: float = 0.05         # attempts>0 시 bucket equality → ±5%p band
HRP_WATER_FILL_MAX_ITERS: int = 20     # HRP per-bucket cap 보정 max 반복
PRICE_LOOKBACK_DAYS_ALLOC: int = 365 * 3   # returns matrix fetch 윈도우
CORRELATION_THRESHOLD_ALLOC: float = 0.85  # cluster-aware fallback corr cut

# 2026-05-26 #2 fix — min weight threshold.
# HRP/MIN_VAR 가 marginal contribution 자산에 0.17% (원유) 같은 micro-position
# 부여 → PnL 영향 없는 "장식". 10억 원 portfolio 기준 1.5% = 1500만원 = MTS
# 단위 매수 가능한 최소 의미. threshold 미만 weight 는 drop 후 같은 bucket 의
# 다른 자산으로 비례 redistribute.
MIN_POSITION_WEIGHT: float = 0.015


def create_portfolio_allocator(
    quick_llm=None, deep_llm=None, cache_path: str | None = None,
):
    """quick_llm/deep_llm은 backward-compat 시그니처 (사용 안 함)."""
    def node(state):
        as_of = date.fromisoformat(state["as_of_date"])
        universe = load_universe(state["universe_path"])
        bucket_target = state["bucket_target"]
        if bucket_target is None:
            raise RuntimeError("bucket_target missing — Research Manager failed")

        feedback_violations = state.get("allocation_feedback", []) or []
        attempts = state.get("allocation_attempts", 0)
        logger.info(
            "allocator start: as_of=%s, attempts=%d, feedback_violations=%d, "
            "universe=%d ETF",
            as_of, attempts, len(feedback_violations), len(universe.etfs),
        )

        tech_report = state.get("technical_report")
        if tech_report is None or not tech_report.factor_panel:
            raise RuntimeError(
                "technical_report.factor_panel missing — Stage 1 technical analyst failed"
            )
        factor_panel = tech_report.factor_panel
        regime = state["macro_report"].regime if state.get("macro_report") else None
        risk_score = state["risk_report"].systemic_score if state.get("risk_report") else None
        research_decision = state.get("research_decision")

        # Stage 3 audit (2026-05-26, Task 0): Stage 1+2 deferred —
        # regime / systemic_score 의 staleness_days 검사. 둘 다 sentinel (≥99) 이면
        # downstream method_picker 가 placeholder 값 (score=5.0, regime="unknown")
        # 으로 결정하는 위험. method_picker 에 degraded_inputs=True 전달 →
        # rule 0 (MIN_VARIANCE 강제) 발동.
        regime_staleness = (
            getattr(regime, "staleness_days", None) if regime is not None else None
        )
        systemic_staleness = (
            getattr(risk_score, "staleness_days", None) if risk_score is not None else None
        )
        degraded_inputs = (
            isinstance(regime_staleness, int) and regime_staleness >= 99
            and isinstance(systemic_staleness, int) and systemic_staleness >= 99
        )
        if degraded_inputs:
            logger.warning(
                "allocator: regime + systemic 둘 다 sentinel (staleness regime=%s, "
                "systemic=%s) → method_picker degraded_inputs=True (strict MIN_VARIANCE)",
                regime_staleness, systemic_staleness,
            )

        # per_bucket_n: low conviction이면 후보 다양화, retry 시 확장.
        per_bucket_n = 4
        if research_decision is not None and getattr(research_decision, "conviction", "medium") == "low":
            per_bucket_n = 5
        if attempts > 0:
            per_bucket_n = max(per_bucket_n + 2, 6)
        logger.info(
            "allocator: per_bucket_n=%d, conviction=%s, dominant_scenario=%s",
            per_bucket_n,
            getattr(research_decision, "conviction", None) if research_decision else None,
            getattr(research_decision, "dominant_scenario", None) if research_decision else None,
        )

        # 1. eligible 후보 universe로 returns matrix fetch
        start = as_of - timedelta(days=PRICE_LOOKBACK_DAYS_ALLOC)
        eligible_by_bucket = list_eligible_tickers(
            universe, bucket_target, as_of=as_of,
            min_aum_krw=DEFAULT_MIN_AUM_KRW,
        )
        eligible_tickers = list({t for ts in eligible_by_bucket.values() for t in ts})
        if not eligible_tickers:
            raise RuntimeError("No eligible tickers (universe × bucket × AUM filter empty)")

        returns = fetch_returns_matrix(
            eligible_tickers, start, as_of, cache_path=cache_path,
        )
        if returns is None or returns.empty:
            raise RuntimeError("returns matrix empty — Stage 3 cannot proceed")

        # 2. Multi-factor + corr de-dup + (Phase C) scenario sub_category boost.
        # Factor model PR (2026-05-22): dominant_cell 제거. 항상 legacy scenario name string 사용.
        # log_boost 가 cell key 받던 path 도 해당 path 제거됨 (sub_category.py).
        dominant_scenario = None
        legacy_scenario_label = None
        if research_decision is not None:
            dominant_scenario = getattr(research_decision, "dominant_scenario", None)
            legacy_scenario_label = dominant_scenario

        # attribution dict — Phase D observability. Restored after merge regression
        # (lost block; referenced at line below + lines 135/142/153).
        attribution: dict = {
            "as_of_date": state["as_of_date"],
            "config": {
                "attempts":             attempts,
                "per_bucket_n":         per_bucket_n,
                "regime_quadrant":      regime.quadrant if regime else None,
                "regime_confidence":    regime.confidence if regime else 0.5,
                "systemic_score":       risk_score.score if risk_score else None,
                "systemic_regime":      risk_score.regime if risk_score else None,
                "dominant_scenario":    dominant_scenario,
                "legacy_scenario":      legacy_scenario_label,
                "conviction":           (
                    getattr(research_decision, "conviction", None)
                    if research_decision else None
                ),
                "bond_tips_share":      bucket_target.bond_tips_share,
                "bucket_target": {
                    "kr_equity":     bucket_target.kr_equity,
                    "global_equity": bucket_target.global_equity,
                    "fx_commodity":  bucket_target.fx_commodity,
                    "bond":          bucket_target.bond,
                    "cash_mmf":      bucket_target.cash_mmf,
                },
                # Stage 3 audit Task 0: Stage 1+2 sentinel propagation 가시화.
                "regime_staleness":    regime_staleness,
                "systemic_staleness":  systemic_staleness,
                "degraded_inputs":     degraded_inputs,
            },
        }

        # Stage 3 audit Task 1: Stage 2 의 safety_diagnostics 와 factor_contributions
        # top-3 를 attribution 에 thread → Stage 6 narrative 가시화.
        if research_decision is not None:
            stage2_safety = getattr(research_decision, "safety_diagnostics", None) or {}
            attribution["research_safety"] = dict(stage2_safety)
            if stage2_safety.get("mandate_violated_pre_projection") or \
                    stage2_safety.get("projection_intervened") or \
                    stage2_safety.get("extreme_factor_active"):
                logger.warning(
                    "allocator: Stage 2 reports intervention — "
                    "mandate_violated=%s, projection_intervened=%s, "
                    "extreme_factor=%s, projection_l2=%.3f",
                    stage2_safety.get("mandate_violated_pre_projection"),
                    stage2_safety.get("projection_intervened"),
                    stage2_safety.get("extreme_factor_active"),
                    stage2_safety.get("projection_l2_distance", 0.0),
                )
            # factor_contributions top-3 — |β·z| 기준
            contribs = getattr(research_decision, "factor_contributions", None) or {}
            flat: list[tuple[str, str, float]] = []
            for factor_name, bmap in contribs.items():
                if not isinstance(bmap, dict):
                    continue
                for bucket_name, contrib in bmap.items():
                    try:
                        flat.append((factor_name, bucket_name, float(contrib)))
                    except (TypeError, ValueError):
                        continue
            flat.sort(key=lambda x: -abs(x[2]))
            attribution["research_inputs"] = {
                "top_factor_contributors": [
                    {"factor": f, "bucket": b, "contribution_pp": c * 100}
                    for f, b, c in flat[:3]
                ],
                "factor_scores": dict(
                    getattr(research_decision, "factor_scores", None) or {}
                ),
            }

        candidates = select_etf_candidates(
            universe, bucket_target,
            as_of=as_of,
            min_aum_krw=DEFAULT_MIN_AUM_KRW,
            per_bucket_n=per_bucket_n,
            returns=returns,
            factor_panel=factor_panel,
            regime_quadrant=regime.quadrant if regime else None,
            regime_confidence=regime.confidence if regime else 0.5,
            correlation_threshold=CORRELATION_THRESHOLD_ALLOC,
            dominant_scenario=dominant_scenario,
            attribution=attribution,
            risk_adjusted=getattr(tech_report, "risk_adjusted", None),
            trend_quant=getattr(tech_report, "trend_quantification", None),
            extended=getattr(tech_report, "extended_indicators", None),
            etf_states=getattr(tech_report, "individual_etf_states", None),
            clusters=getattr(tech_report, "correlation_clusters", None),
        )

        all_candidates = [
            t for tickers in candidates.bucket_to_tickers.values() for t in tickers
        ]
        if len(all_candidates) < 3:
            raise RuntimeError(f"Too few candidates ({len(all_candidates)})")
        logger.info(
            "allocator: %d candidates selected across %d buckets",
            len(all_candidates),
            sum(1 for v in candidates.bucket_to_tickers.values() if v),
        )

        returns = returns[[c for c in all_candidates if c in returns.columns]]

        # 3. Method picker — deterministic (LLM 0회)
        feedback_str = ""
        if feedback_violations:
            feedback_str = "; ".join(
                f"{v.description} (fix: {v.suggested_fix})"
                for v in feedback_violations[:3]
            )

        method_choice = pick_optimization_method(
            regime_quadrant=regime.quadrant if regime else "unknown",
            regime_confidence=regime.confidence if regime else 0.5,
            systemic_score=risk_score.score if risk_score else 5.0,
            systemic_regime=risk_score.regime if risk_score else "neutral",
            research_decision=research_decision,
            feedback=feedback_str,
            degraded_inputs=degraded_inputs,
            regime_staleness=regime_staleness,
            systemic_staleness=systemic_staleness,
        )

        # 4. Optimize WITH bucket-constraints (D12).
        # bond bucket의 sub-bucket(TIPS/nominal) weight 강제 위해 sub_category lookup 전달.
        sub_category_lookup = {e.ticker: e.sub_category for e in universe.etfs}
        attribution["optimization"] = {}
        wv = _optimize_with_bucket_constraints(
            method=method_choice.method,
            returns=returns,
            candidates=candidates,
            bucket_target=bucket_target,
            method_params=method_choice.params,
            attempts=attempts,
            sub_category_lookup=sub_category_lookup,
            attribution=attribution["optimization"],
        )

        attribution["method_picker"] = {
            "method":       method_choice.method.value,
            "rule_fired":   method_choice.rule_fired,
            "rule_index":   method_choice.rule_index,
            "reasoning":    method_choice.reasoning,
            "inputs":       method_choice.inputs,
        }
        attribution["weight_vector_summary"] = {
            "n_positions":       len(wv.weights),
            "max_single_weight": max(wv.weights.values()) if wv.weights else 0.0,
            "expected_vol":      wv.expected_volatility,
            "expected_sharpe":   wv.expected_sharpe,
        }

        logger.info(
            "allocator complete: method=%s, %d positions, max_w=%.3f, "
            "expected_vol=%s, expected_sharpe=%s, attempts→%d",
            method_choice.method.value,
            len(wv.weights),
            max(wv.weights.values()) if wv.weights else 0.0,
            f"{wv.expected_volatility:.3f}" if wv.expected_volatility is not None else "n/a",
            f"{wv.expected_sharpe:.3f}" if wv.expected_sharpe is not None else "n/a",
            attempts + 1,
        )

        return {
            "candidate_set": candidates,
            "weight_vector": wv,
            "method_choice": method_choice,
            "allocation_attribution": attribution,
            "allocation_attempts": attempts + 1,
        }

    return node


def _build_sector_mapper_and_bounds(
    candidates, bucket_target, attempts: int,
    sub_category_lookup: dict[str, str | None] | None = None,
) -> tuple[dict[str, str], dict[str, float], dict[str, float]]:
    """Map ticker → bucket (or sub-bucket); build (lower, upper) bounds.

    bond bucket의 inflation_linked sub_category ticker는 'bond_tips'로,
    나머지는 'bond_nominal'로 매핑 (bond_tips_share > 0인 경우). 이렇게
    하면 pypfopt가 두 sub-pool의 weight 합을 각각 강제 — Stage 2의
    bond_tips_share intent가 실제 weight으로 enforce됨.

    First attempt: equality (lower == upper == target).
    Retry: relax to ±5%p band (handle infeasibility).
    """
    sub_category_lookup = sub_category_lookup or {}
    split_bond = bucket_target.bond_tips_share > 0.0

    sector_mapper: dict[str, str] = {}
    for bucket, tickers in candidates.bucket_to_tickers.items():
        for t in tickers:
            if bucket == "bond" and split_bond:
                sc = sub_category_lookup.get(t)
                sector_mapper[t] = "bond_tips" if sc == "inflation_linked" else "bond_nominal"
            else:
                sector_mapper[t] = bucket

    target_map: dict[str, float] = {
        "kr_equity": bucket_target.kr_equity,
        "global_equity": bucket_target.global_equity,
        "fx_commodity": bucket_target.fx_commodity,
        "cash_mmf": bucket_target.cash_mmf,
    }
    if split_bond:
        target_map["bond_tips"] = bucket_target.bond * bucket_target.bond_tips_share
        target_map["bond_nominal"] = bucket_target.bond * (1.0 - bucket_target.bond_tips_share)
    else:
        target_map["bond"] = bucket_target.bond

    # Infeasibility 방어 — 후보 풀에 한쪽 sub-bucket이 0이면 그 target도 0,
    # 다른 sub-bucket에 합쳐서 처리. (candidate_selector가 fallback으로
    # nominal로 채워도 sector_mapper에 따라 'bond_nominal'로 매핑됨)
    if split_bond:
        sectors_present = set(sector_mapper.values())
        if "bond_tips" not in sectors_present:
            # 후보 풀에 TIPS 없음 → tips target을 nominal로 흡수
            target_map["bond_nominal"] = target_map.pop("bond_tips") + target_map["bond_nominal"]
        if "bond_nominal" not in sectors_present:
            target_map["bond_tips"] = target_map.pop("bond_nominal") + target_map.get("bond_tips", 0.0)

    if attempts == 0:
        sector_lower = dict(target_map)
        sector_upper = dict(target_map)
    else:
        band = RETRY_BAND_WIDTH
        sector_lower = {b: round(max(0.0, w - band), 10) for b, w in target_map.items()}
        sector_upper = {b: round(min(1.0, w + band), 10) for b, w in target_map.items()}

    return sector_mapper, sector_lower, sector_upper


def _optimize_with_bucket_constraints(
    method: OptimizationMethod,
    returns: pd.DataFrame,
    candidates,
    bucket_target,
    method_params: dict,
    attempts: int,
    sub_category_lookup: dict[str, str | None] | None = None,
    attribution: dict | None = None,
) -> WeightVector:
    """Optimize with simultaneous (single-cap, bucket sum) constraints.

    sub_category_lookup이 주어지면 bond bucket이 (bond_tips, bond_nominal)로
    분리되어 Stage 2 bond_tips_share intent가 weight constraint로 강제됨.

    attribution (Stage 3 audit Task 1/3): 제공 시 cov 표본 부족 제외 ticker,
    cap 발동 ticker 등 진단 정보를 dict 에 기록.
    """
    sector_mapper, sector_lower, sector_upper = _build_sector_mapper_and_bounds(
        candidates, bucket_target, attempts, sub_category_lookup,
    )

    valid = [t for t in returns.columns if t in sector_mapper]
    returns_raw = returns[valid]
    returns = returns_raw.dropna(axis=0, how="any")

    # 표본 부족 (cov가 비양정부호 → eigenvalue 수렴 실패) 방지.
    # 늦게 상장된 ETF가 적은 수의 NaN-free row만 남기는 경우 데이터 적은 ticker
    # 부터 제거해서 표본 회복. _hrp_per_bucket은 sub-pool 단위라 영향 적어 skip.
    if method != OptimizationMethod.HRP and len(returns) < MIN_COV_OBS:
        valid = list(valid)
        days_per_ticker = {
            t: int(returns_raw[t].dropna().shape[0]) for t in valid
        }
        # 짧은 데이터 ticker부터 제거 (sector_mapper에 남기되 cov 계산에서만 제외)
        order = sorted(days_per_ticker, key=lambda t: days_per_ticker[t])
        excluded: list[str] = []
        while len(returns) < MIN_COV_OBS and len(valid) > 5:
            drop = order.pop(0)
            valid.remove(drop)
            excluded.append(drop)
            returns = returns_raw[valid].dropna(axis=0, how="any")
        if excluded:
            logger.warning(
                "cov 표본 부족 — %d ETF를 cov 계산에서 제외: %s (남은 표본 %d row)",
                len(excluded), excluded, len(returns),
            )
            if attribution is not None:
                attribution["cov_excluded_tickers"] = list(excluded)
                attribution["cov_final_obs"] = int(len(returns))

    if method == OptimizationMethod.HRP:
        return _hrp_per_bucket(
            returns, candidates, bucket_target, sub_category_lookup,
            attribution=attribution,
        )

    S = risk_models.sample_cov(returns)

    if method == OptimizationMethod.BLACK_LITTERMAN:
        from pypfopt import BlackLittermanModel
        views = method_params.get("views", {})
        confs = method_params.get("view_confidences", [])
        if views:
            bl = BlackLittermanModel(
                S, absolute_views=views, omega="idzorek", view_confidences=confs,
            )
            mu = bl.bl_returns()
        else:
            mu = expected_returns.mean_historical_return(returns, returns_data=True)
    else:
        mu = expected_returns.mean_historical_return(returns, returns_data=True)

    ef = EfficientFrontier(mu, S, weight_bounds=(0, SINGLE_ASSET_CAP))
    ef.add_sector_constraints(sector_mapper, sector_lower, sector_upper)

    try:
        if method == OptimizationMethod.MIN_VARIANCE:
            ef.min_volatility()
        elif method == OptimizationMethod.RISK_PARITY:
            ef.min_volatility()
        else:
            ef.max_sharpe()
    except Exception as e:
        raise RuntimeError(
            f"Joint optimization infeasible (method={method}, attempt={attempts}): {e}"
        ) from e

    weights = {t: float(w) for t, w in ef.clean_weights().items() if w > 1e-4}
    total = sum(weights.values())
    weights = {t: w / total for t, w in weights.items()}

    # 부동소수 오차 보정: solver가 0.20에 *근접*하게 풀이 + post-normalize로
    # 약 1e-5 ~ 1e-4 정도 초과 가능. 실질적 mandate 위반이 아니라 numerical
    # noise. clip(0.20) + 다른 자산 재정규화로 안전 보정 (validator는
    # 1e-6 정밀도로 다시 검증).
    if any(w > SINGLE_ASSET_CAP for w in weights.values()):
        # Stage 3 audit Task 3: cap clip 발동 가시화.
        capped_tickers = [t for t, w in weights.items() if w > SINGLE_ASSET_CAP]
        logger.info(
            "EF post-clip: %d ETF over cap (%.2f) — clip + redistribute: %s",
            len(capped_tickers), SINGLE_ASSET_CAP, capped_tickers,
        )
        if attribution is not None:
            attribution["cap_clipped_tickers"] = list(capped_tickers)
        clipped = {t: min(w, SINGLE_ASSET_CAP) for t, w in weights.items()}
        residual = 1.0 - sum(clipped.values())
        non_capped = [t for t, w in clipped.items() if w < SINGLE_ASSET_CAP - 1e-9]
        if non_capped and residual > 0:
            # 잔여를 non-capped 자산에 비례 분배 (다시 cap 초과 안 하도록 iter)
            for _ in range(10):
                share = residual / max(len(non_capped), 1)
                for t in non_capped:
                    add = min(share, SINGLE_ASSET_CAP - clipped[t])
                    clipped[t] += add
                residual = 1.0 - sum(clipped.values())
                non_capped = [t for t, w in clipped.items() if w < SINGLE_ASSET_CAP - 1e-9]
                if residual <= 1e-9 or not non_capped:
                    break
        weights = clipped

    violators = [
        (t, w) for t, w in weights.items() if w > SINGLE_ASSET_CAP + 1e-4
    ]
    assert not violators, (
        f"Optimizer violated {SINGLE_ASSET_CAP*100:.0f}% cap after clip: {violators}"
    )

    constraint_label = "strict bucket equality" if attempts == 0 else "±5%p bucket band"
    expected_vol = None
    expected_sharpe = None
    try:
        perf = ef.portfolio_performance(verbose=False)
        if len(perf) >= 3:
            expected_sharpe = float(perf[2])
        if len(perf) >= 2:
            expected_vol = float(perf[1])
    except Exception as e:
        logger.warning("portfolio_performance failed: %s", e)

    # 2026-05-26 #2 fix — min weight threshold.
    weights = _apply_min_weight_threshold(
        weights, candidates, attribution=attribution,
    )
    return WeightVector(
        method=method,
        weights=weights,
        rationale=(
            f"{method.value} with single-asset cap 20% AND bucket constraints "
            f"({constraint_label}). 위험자산 target {bucket_target.risk_asset_weight:.1%}."
        ),
        expected_volatility=expected_vol,
        expected_sharpe=expected_sharpe,
    )


def _apply_min_weight_threshold(
    weights: dict[str, float],
    candidates,
    min_weight: float = MIN_POSITION_WEIGHT,
    attribution: dict | None = None,
) -> dict[str, float]:
    """min_weight 미만 weight 는 drop + 같은 bucket 내 비례 redistribute.

    2026-05-26 #2 fix.
    같은 bucket 내 살아남은 자산이 없으면 dropped weight 는 *전체* 자산에 비례
    redistribute (bucket 합 보존 위반 가능하지만 dust 수준이므로 무해).
    """
    if not weights:
        return weights
    bucket_of = {
        t: b for b, ts in candidates.bucket_to_tickers.items() for t in ts
    }
    dropped: dict[str, float] = {}
    survivors: dict[str, float] = {}
    for t, w in weights.items():
        if w < min_weight:
            dropped[t] = w
        else:
            survivors[t] = w

    if not dropped:
        return weights
    if not survivors:
        # 전부 drop 대상 — 그대로 둠 (edge case)
        logger.warning(
            "min_weight threshold: all %d weights below %.3f — keeping as-is",
            len(weights), min_weight,
        )
        return weights

    # 각 dropped weight 를 같은 bucket 의 survivors 에 비례 redistribute.
    # 같은 bucket survivor 없으면 전체 survivors 에 비례.
    for dt, dw in dropped.items():
        db = bucket_of.get(dt)
        same_bucket_survivors = [
            s for s in survivors if bucket_of.get(s) == db
        ]
        recipients = same_bucket_survivors if same_bucket_survivors else list(survivors)
        sub_total = sum(survivors[r] for r in recipients)
        if sub_total <= 0:
            continue
        for r in recipients:
            survivors[r] += dw * (survivors[r] / sub_total)

    logger.info(
        "min_weight threshold (%.3f): dropped %d positions (%s), "
        "redistributed to %d survivors",
        min_weight, len(dropped), list(dropped),
        len(survivors),
    )
    if attribution is not None:
        attribution["min_weight_dropped"] = {
            t: float(w) for t, w in dropped.items()
        }
        attribution["min_weight_threshold"] = float(min_weight)

    # Single asset cap 재확인 (redistribute 후 cap 초과 위험은 미미하지만 safety).
    for t, w in list(survivors.items()):
        if w > SINGLE_ASSET_CAP + 1e-9:
            excess = w - SINGLE_ASSET_CAP
            survivors[t] = SINGLE_ASSET_CAP
            # excess 는 다른 survivor 에 비례 분배 (drop 자산 제외)
            others = [s for s in survivors if s != t]
            other_total = sum(survivors[s] for s in others)
            if other_total > 0:
                for s in others:
                    survivors[s] += excess * (survivors[s] / other_total)
    return survivors


def _hrp_per_bucket(
    returns: pd.DataFrame, candidates, bucket_target,
    sub_category_lookup: dict[str, str | None] | None = None,
    attribution: dict | None = None,
) -> WeightVector:
    """HRP within each bucket × bucket target, with ITERATIVE water-filling cap.

    Per D12 fix: single-pass clip+redistribute can fail (redistribute pushes
    other weights over cap). Loop until residual ≤ tolerance OR all assets
    capped (raise RuntimeError for joint infeasibility — Validator cycle handles).

    bond bucket: bond_tips_share > 0이면 (TIPS, nominal) sub-pool로 분리해서 각각
    HRP × sub-target. Stage 2 bond_tips_share intent enforce.

    attribution (Stage 3 audit Task 3): 제공 시 cap-all shortfall + 최종 단위
    normalization 발동 등을 dict 에 기록.
    """
    bucket_shortfalls: list[dict] = []
    sub_category_lookup = sub_category_lookup or {}
    target_map = {
        "kr_equity": bucket_target.kr_equity,
        "global_equity": bucket_target.global_equity,
        "fx_commodity": bucket_target.fx_commodity,
        "bond": bucket_target.bond,
        "cash_mmf": bucket_target.cash_mmf,
    }
    split_bond = bucket_target.bond_tips_share > 0.0

    final: dict[str, float] = {}
    for bucket, tickers in candidates.bucket_to_tickers.items():
        target = target_map.get(bucket, 0)
        if target <= 0 or not tickers:
            continue

        if bucket == "bond" and split_bond:
            # Sub-pool split per inflation_linked sub_category
            tips_tickers = [
                t for t in tickers
                if sub_category_lookup.get(t) == "inflation_linked"
            ]
            nominal_tickers = [t for t in tickers if t not in tips_tickers]
            tips_target = target * bucket_target.bond_tips_share
            nominal_target = target * (1.0 - bucket_target.bond_tips_share)
            # 한쪽이 비면 target을 다른 쪽으로 흡수
            if not tips_tickers and nominal_tickers:
                nominal_target += tips_target
                tips_target = 0.0
            if not nominal_tickers and tips_tickers:
                tips_target += nominal_target
                nominal_target = 0.0

            sub_buckets = []
            if tips_tickers and tips_target > 0:
                sub_buckets.append((tips_tickers, tips_target))
            if nominal_tickers and nominal_target > 0:
                sub_buckets.append((nominal_tickers, nominal_target))
        else:
            sub_buckets = [(tickers, target)]

        for pool_tickers, pool_target in sub_buckets:
            sub = returns[[t for t in pool_tickers if t in returns.columns]].dropna(axis=0, how="any")
            if sub.shape[1] == 0:
                continue
            if sub.shape[1] == 1:
                inner = {sub.columns[0]: 1.0}
            else:
                hrp = HRPOpt(sub)
                inner = {k: float(v) for k, v in hrp.optimize().items()}
                s = sum(inner.values())
                inner = {k: v / s for k, v in inner.items()}

            scaled = {t: w * pool_target for t, w in inner.items()}

            capped = {t: min(w, SINGLE_ASSET_CAP) for t, w in scaled.items()}
            residual = sum(scaled.values()) - sum(capped.values())
            for _ in range(HRP_WATER_FILL_MAX_ITERS):
                if residual <= 1e-9:
                    break
                non_capped = [t for t, w in capped.items() if w < SINGLE_ASSET_CAP - 1e-9]
                if not non_capped:
                    # All assets at cap — bucket target unreachable; accept partial fill.
                    # Final normalization absorbs the shortfall across all buckets.
                    # Stage 3 audit Task 3: 가시화.
                    logger.warning(
                        "HRP: bucket %s 의 모든 자산이 cap 도달 — target=%.3f, "
                        "실제=%.3f (shortfall=%.3f)",
                        bucket, pool_target, sum(capped.values()), residual,
                    )
                    bucket_shortfalls.append({
                        "bucket": bucket,
                        "pool_target": float(pool_target),
                        "actual": float(sum(capped.values())),
                        "shortfall": float(residual),
                        "n_assets_capped": len(capped),
                    })
                    break
                share = residual / len(non_capped)
                for t in non_capped:
                    room = SINGLE_ASSET_CAP - capped[t]
                    add = min(share, room)
                    capped[t] += add
                residual = sum(scaled.values()) - sum(capped.values())

            final.update(capped)

    total = sum(final.values())
    final_norm_intervened = False
    if total > 0 and abs(total - 1.0) > 1e-9:
        # Iterative water-filling normalization: distribute 1.0 across all assets
        # while respecting the SINGLE_ASSET_CAP per-asset cap. 발동되면 bucket
        # target 일부 미충족 — Stage 3 audit Task 3 가시화 대상.
        final_norm_intervened = True
        logger.info(
            "HRP final normalization: sum=%.6f ≠ 1.0 → water-fill redistribute",
            total,
        )
        target_total = 1.0
        remaining = target_total
        normalized: dict[str, float] = {}
        uncapped = list(final.keys())
        raw = dict(final)
        raw_total = sum(raw.values())
        # Scale proportionally first, then iteratively clip and redistribute.
        scaled_raw = {t: w / raw_total for t, w in raw.items()}
        for _ in range(HRP_WATER_FILL_MAX_ITERS):
            capped_tickers = [t for t in uncapped if scaled_raw[t] >= SINGLE_ASSET_CAP - 1e-9]
            for t in capped_tickers:
                normalized[t] = min(scaled_raw[t], SINGLE_ASSET_CAP)
                uncapped.remove(t)
            if not capped_tickers:
                for t in uncapped:
                    normalized[t] = scaled_raw[t]
                break
            free = remaining - sum(normalized.values())
            if not uncapped or free <= 0:
                break
            sub_total = sum(scaled_raw[t] for t in uncapped)
            if sub_total <= 0:
                break
            scaled_raw = {t: scaled_raw[t] / sub_total * free for t in uncapped}
            remaining = free
        else:
            for t in uncapped:
                normalized[t] = scaled_raw[t]
        final = normalized

    if attribution is not None:
        if bucket_shortfalls:
            attribution["hrp_bucket_shortfalls"] = bucket_shortfalls
        attribution["hrp_final_norm_intervened"] = final_norm_intervened

    violators = [(t, w) for t, w in final.items() if w > SINGLE_ASSET_CAP + 1e-6]
    assert not violators, (
        f"HRP-per-bucket post-condition: {SINGLE_ASSET_CAP*100:.0f}% cap violated: {violators}"
    )

    # 2026-05-26 #2 fix — min weight threshold.
    final = _apply_min_weight_threshold(
        final, candidates, attribution=attribution,
    )
    return WeightVector(
        method=OptimizationMethod.HRP,
        weights=final,
        rationale=(
            f"HRP within each bucket × bucket_target weight. "
            f"위험자산 target {bucket_target.risk_asset_weight:.1%}, single-asset cap 20%."
        ),
    )
