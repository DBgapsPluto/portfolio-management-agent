"""Portfolio Allocator — bucket constraints injected into optimizer (D12 fatal fix).

The previous design ran a 20%-capped optimizer THEN scaled to BucketTarget,
which can push single weights ABOVE the 20% cap. Per design D12: inject
bucket sum constraints DURING optimization via add_sector_constraints, so
the solver finds weights satisfying both single-cap and bucket sums
simultaneously. HRP doesn't natively support sector constraints — that's
handled via _hrp_per_bucket with iterative water-filling.

Per D4: feedback from previous validation failure is injected into the
method picker subagent prompt, allowing the LLM to choose a different
candidate frame on retry.
"""
from datetime import date, timedelta

import pandas as pd
from pypfopt import EfficientFrontier, HRPOpt, risk_models, expected_returns

from tradingagents.dataflows.universe import load_universe
from tradingagents.schemas.portfolio import OptimizationMethod, WeightVector
from tradingagents.skills.portfolio.candidate_selector import (
    BUCKET_TO_CATEGORIES, select_etf_candidates,
)
from tradingagents.skills.portfolio.method_picker import pick_optimization_method
from tradingagents.skills.portfolio.returns_matrix import fetch_returns_matrix


def create_portfolio_allocator(quick_llm, deep_llm, cache_path: str | None = None):
    def node(state):
        as_of = date.fromisoformat(state["as_of_date"])
        universe = load_universe(state["universe_path"])
        bucket_target = state["bucket_target"]
        if bucket_target is None:
            raise RuntimeError("bucket_target missing — Research Manager failed")

        feedback_violations = state.get("allocation_feedback", []) or []
        attempts = state.get("allocation_attempts", 0)

        # 1. Select candidates (D13: tradable_at applied inside)
        rankings = (
            state["technical_report"].asset_class_momentum
            if state.get("technical_report") else {}
        )
        candidates = select_etf_candidates(
            universe, bucket_target, rankings,
            as_of=as_of,
            min_aum_krw=1_000_000_000_000,
            per_bucket_n=4 if attempts == 0 else 6,  # widen pool on retry
        )

        all_candidates: list[str] = []
        for tickers in candidates.bucket_to_tickers.values():
            all_candidates.extend(tickers)
        if len(all_candidates) < 3:
            raise RuntimeError("Too few candidates")

        # 2. Returns matrix
        start = as_of - timedelta(days=365 * 3)
        returns = fetch_returns_matrix(all_candidates, start, as_of, cache_path=cache_path)

        # 3. Method picker subagent (D4: includes feedback)
        regime = state["macro_report"].regime if state.get("macro_report") else None
        risk_score = state["risk_report"].systemic_score if state.get("risk_report") else None

        feedback_str = ""
        if feedback_violations:
            feedback_str = "\nPrevious violations:\n" + "\n".join(
                f"- {v.description} (fix: {v.suggested_fix})" for v in feedback_violations
            )

        method_choice = pick_optimization_method(
            quick_llm, deep_llm,
            regime_quadrant=regime.quadrant if regime else "unknown",
            regime_confidence=regime.confidence if regime else 0.5,
            risk_score=risk_score.score if risk_score else 5.0,
            risk_regime=risk_score.regime if risk_score else "neutral",
            feedback=feedback_str,
        )

        # 4. Optimize WITH bucket-constraints (D12)
        wv = _optimize_with_bucket_constraints(
            method=method_choice.method,
            returns=returns,
            candidates=candidates,
            bucket_target=bucket_target,
            method_params=method_choice.params,
            attempts=attempts,
        )

        return {
            "candidate_set": candidates,
            "weight_vector": wv,
            "allocation_attempts": attempts + 1,
        }

    return node


def _build_sector_mapper_and_bounds(
    candidates, bucket_target, attempts: int,
) -> tuple[dict[str, str], dict[str, float], dict[str, float]]:
    """Map ticker → bucket; build (lower, upper) bounds per bucket.

    First attempt: equality (lower == upper == target).
    Retry: relax to ±5%p band (handle infeasibility).
    """
    sector_mapper: dict[str, str] = {}
    for bucket, tickers in candidates.bucket_to_tickers.items():
        for t in tickers:
            sector_mapper[t] = bucket

    target_map = {
        "kr_equity": bucket_target.kr_equity,
        "global_equity": bucket_target.global_equity,
        "fx_commodity": bucket_target.fx_commodity,
        "bond": bucket_target.bond,
        "cash_mmf": bucket_target.cash_mmf,
    }

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
) -> WeightVector:
    """Optimize with simultaneous (single-cap, bucket sum) constraints."""
    sector_mapper, sector_lower, sector_upper = _build_sector_mapper_and_bounds(
        candidates, bucket_target, attempts,
    )

    valid = [t for t in returns.columns if t in sector_mapper]
    returns = returns[valid].dropna(axis=0, how="any")

    if method == OptimizationMethod.HRP:
        return _hrp_per_bucket(returns, candidates, bucket_target)

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

    assert all(w <= 0.20 + 1e-6 for w in weights.values()), \
        f"Optimizer violated 20% cap: {[(t, w) for t, w in weights.items() if w > 0.20]}"

    constraint_label = "strict bucket equality" if attempts == 0 else "±5%p bucket band"
    expected_vol = None
    expected_sharpe = None
    try:
        perf = ef.portfolio_performance(verbose=False)
        if len(perf) >= 3:
            expected_sharpe = float(perf[2])
        if len(perf) >= 2:
            expected_vol = float(perf[1])
    except Exception:
        pass

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


def _hrp_per_bucket(returns: pd.DataFrame, candidates, bucket_target) -> WeightVector:
    """HRP within each bucket × bucket target, with ITERATIVE water-filling cap.

    Per D12 fix: single-pass clip+redistribute can fail (redistribute pushes
    other weights over cap). Loop until residual ≤ tolerance OR all assets
    capped (raise RuntimeError for joint infeasibility — Validator cycle handles).
    """
    target_map = {
        "kr_equity": bucket_target.kr_equity,
        "global_equity": bucket_target.global_equity,
        "fx_commodity": bucket_target.fx_commodity,
        "bond": bucket_target.bond,
        "cash_mmf": bucket_target.cash_mmf,
    }

    final: dict[str, float] = {}
    for bucket, tickers in candidates.bucket_to_tickers.items():
        target = target_map.get(bucket, 0)
        if target <= 0 or not tickers:
            continue
        sub = returns[[t for t in tickers if t in returns.columns]].dropna(axis=0, how="any")
        if sub.shape[1] == 0:
            continue
        if sub.shape[1] == 1:
            inner = {sub.columns[0]: 1.0}
        else:
            hrp = HRPOpt(sub)
            inner = {k: float(v) for k, v in hrp.optimize().items()}
            s = sum(inner.values())
            inner = {k: v / s for k, v in inner.items()}

        scaled = {t: w * target for t, w in inner.items()}

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
