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
    BUCKET_TO_CATEGORIES, list_eligible_tickers, select_etf_candidates,
)
from tradingagents.skills.portfolio.method_picker import pick_optimization_method
from tradingagents.skills.portfolio.returns_matrix import fetch_returns_matrix

logger = logging.getLogger(__name__)


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

        tech_report = state.get("technical_report")
        if tech_report is None or not tech_report.factor_panel:
            raise RuntimeError(
                "technical_report.factor_panel missing — Stage 1 technical analyst failed"
            )
        factor_panel = tech_report.factor_panel
        regime = state["macro_report"].regime if state.get("macro_report") else None
        risk_score = state["risk_report"].systemic_score if state.get("risk_report") else None
        research_decision = state.get("research_decision")

        # per_bucket_n: low conviction이면 후보 다양화, retry 시 확장.
        per_bucket_n = 4
        if research_decision is not None and getattr(research_decision, "conviction", "medium") == "low":
            per_bucket_n = 5
        if attempts > 0:
            per_bucket_n = max(per_bucket_n + 2, 6)

        # 1. eligible 후보 universe로 returns matrix fetch
        start = as_of - timedelta(days=365 * 3)
        eligible_by_bucket = list_eligible_tickers(
            universe, bucket_target, as_of=as_of,
            min_aum_krw=1_000_000_000_000,
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
        if research_decision is not None:
            dominant_scenario = getattr(research_decision, "dominant_scenario", None)
        candidates = select_etf_candidates(
            universe, bucket_target,
            as_of=as_of,
            min_aum_krw=1_000_000_000_000,
            per_bucket_n=per_bucket_n,
            returns=returns,
            factor_panel=factor_panel,
            regime_quadrant=regime.quadrant if regime else None,
            regime_confidence=regime.confidence if regime else 0.5,
            correlation_threshold=0.85,
            dominant_scenario=dominant_scenario,
        )

        all_candidates = [
            t for tickers in candidates.bucket_to_tickers.values() for t in tickers
        ]
        if len(all_candidates) < 3:
            raise RuntimeError(f"Too few candidates ({len(all_candidates)})")

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
        )

        # 4. Optimize WITH bucket-constraints (D12).
        # bond bucket의 sub-bucket(TIPS/nominal) weight 강제 위해 sub_category lookup 전달.
        sub_category_lookup = {e.ticker: e.sub_category for e in universe.etfs}
        wv = _optimize_with_bucket_constraints(
            method=method_choice.method,
            returns=returns,
            candidates=candidates,
            bucket_target=bucket_target,
            method_params=method_choice.params,
            attempts=attempts,
            sub_category_lookup=sub_category_lookup,
        )

        return {
            "candidate_set": candidates,
            "weight_vector": wv,
            "method_choice": method_choice,
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
        band = 0.05
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
) -> WeightVector:
    """Optimize with simultaneous (single-cap, bucket sum) constraints.

    sub_category_lookup이 주어지면 bond bucket이 (bond_tips, bond_nominal)로
    분리되어 Stage 2 bond_tips_share intent가 weight constraint로 강제됨.
    """
    sector_mapper, sector_lower, sector_upper = _build_sector_mapper_and_bounds(
        candidates, bucket_target, attempts, sub_category_lookup,
    )

    valid = [t for t in returns.columns if t in sector_mapper]
    returns = returns[valid].dropna(axis=0, how="any")

    if method == OptimizationMethod.HRP:
        return _hrp_per_bucket(returns, candidates, bucket_target, sub_category_lookup)

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

    ef = EfficientFrontier(mu, S, weight_bounds=(0, 0.20))
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
    if any(w > 0.20 for w in weights.values()):
        clipped = {t: min(w, 0.20) for t, w in weights.items()}
        residual = 1.0 - sum(clipped.values())
        non_capped = [t for t, w in clipped.items() if w < 0.20 - 1e-9]
        if non_capped and residual > 0:
            # 잔여를 non-capped 자산에 비례 분배 (다시 cap 초과 안 하도록 iter)
            for _ in range(10):
                share = residual / max(len(non_capped), 1)
                for t in non_capped:
                    add = min(share, 0.20 - clipped[t])
                    clipped[t] += add
                residual = 1.0 - sum(clipped.values())
                non_capped = [t for t, w in clipped.items() if w < 0.20 - 1e-9]
                if residual <= 1e-9 or not non_capped:
                    break
        weights = clipped

    assert all(w <= 0.20 + 1e-4 for w in weights.values()), \
        f"Optimizer violated 20% cap after clip: {[(t, w) for t, w in weights.items() if w > 0.20 + 1e-4]}"

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


def _hrp_per_bucket(
    returns: pd.DataFrame, candidates, bucket_target,
    sub_category_lookup: dict[str, str | None] | None = None,
) -> WeightVector:
    """HRP within each bucket × bucket target, with ITERATIVE water-filling cap.

    Per D12 fix: single-pass clip+redistribute can fail (redistribute pushes
    other weights over cap). Loop until residual ≤ tolerance OR all assets
    capped (raise RuntimeError for joint infeasibility — Validator cycle handles).

    bond bucket: bond_tips_share > 0이면 (TIPS, nominal) sub-pool로 분리해서 각각
    HRP × sub-target. Stage 2 bond_tips_share intent enforce.
    """
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

            capped = {t: min(w, 0.20) for t, w in scaled.items()}
            residual = sum(scaled.values()) - sum(capped.values())
            max_iters = 10
            for _ in range(max_iters):
                if residual <= 1e-9:
                    break
                non_capped = [t for t, w in capped.items() if w < 0.20 - 1e-9]
                if not non_capped:
                    # All assets at cap — bucket target unreachable; accept partial fill.
                    # Final normalization absorbs the shortfall across all buckets.
                    break
                share = residual / len(non_capped)
                for t in non_capped:
                    room = 0.20 - capped[t]
                    add = min(share, room)
                    capped[t] += add
                residual = sum(scaled.values()) - sum(capped.values())

            final.update(capped)

    total = sum(final.values())
    if total > 0 and abs(total - 1.0) > 1e-9:
        # Iterative water-filling normalization: distribute 1.0 across all assets
        # while respecting the 0.20 per-asset cap.
        target_total = 1.0
        remaining = target_total
        normalized: dict[str, float] = {}
        uncapped = list(final.keys())
        raw = dict(final)
        raw_total = sum(raw.values())
        # Scale proportionally first, then iteratively clip and redistribute.
        scaled_raw = {t: w / raw_total for t, w in raw.items()}
        for _ in range(20):
            capped_tickers = [t for t in uncapped if scaled_raw[t] >= 0.20 - 1e-9]
            for t in capped_tickers:
                normalized[t] = min(scaled_raw[t], 0.20)
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

    assert all(w <= 0.20 + 1e-6 for w in final.values()), \
        "HRP-per-bucket post-condition: 20% cap violated"

    return WeightVector(
        method=OptimizationMethod.HRP,
        weights=final,
        rationale=(
            f"HRP within each bucket × bucket_target weight. "
            f"위험자산 target {bucket_target.risk_asset_weight:.1%}, single-asset cap 20%."
        ),
    )
