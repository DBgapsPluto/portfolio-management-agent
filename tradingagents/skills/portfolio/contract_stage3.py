"""Stage 3 helpers when Allocation Contract is active (Phase 2)."""
from __future__ import annotations

import logging
from typing import Any

from tradingagents.schemas.allocation_contract import AllocationContract, ThemeLimit
from tradingagents.skills.research.factor_to_bucket import (
    BUCKETS,
    MANDATE_RISK_CAP,
    RISK_BUCKETS,
    project_to_mandate_qp,
)

logger = logging.getLogger(__name__)


def contract_stage3_active(
    research_decision: Any | None,
    *,
    allocation_contract_enabled: bool,
) -> bool:
    if not allocation_contract_enabled or research_decision is None:
        return False
    return getattr(research_decision, "allocation_contract", None) is not None


def realized_bucket_weights(
    weights: dict[str, float],
    bucket_to_tickers: dict[str, list[str]],
) -> dict[str, float]:
    """Aggregate ticker weights to bucket totals."""
    out = {b: 0.0 for b in bucket_to_tickers}
    ticker_bucket = {
        t: b for b, tickers in bucket_to_tickers.items() for t in tickers
    }
    for t, w in weights.items():
        b = ticker_bucket.get(t)
        if b:
            out[b] = out.get(b, 0.0) + float(w)
    return out


def build_implementation_alignment(
    contract: AllocationContract,
    realized: dict[str, float],
) -> dict[str, object]:
    """Prior vs feasible vs envelope vs realized (audit / UI)."""
    drift_pf: dict[str, float] = {}
    drift_fr: dict[str, float] = {}
    envelope_status: dict[str, object] = {}
    for bucket in contract.feasible_weights:
        prior_b = float(contract.prior_weights.get(bucket, 0.0))
        feas_b = float(contract.feasible_weights.get(bucket, 0.0))
        real_b = float(realized.get(bucket, 0.0))
        drift_pf[bucket] = feas_b - prior_b
        drift_fr[bucket] = real_b - feas_b
        env = contract.envelope.get(bucket)
        if env is None:
            envelope_status[bucket] = {"status": "missing_envelope"}
        else:
            within = env.lo - 1e-9 <= real_b <= env.hi + 1e-9
            envelope_status[bucket] = {
                "lo": env.lo,
                "hi": env.hi,
                "realized": real_b,
                "within": within,
            }
    all_within = all(
        s.get("within") is True for s in envelope_status.values()
        if isinstance(s, dict) and "within" in s
    )
    return {
        "prior_weights": dict(contract.prior_weights),
        "feasible_weights": dict(contract.feasible_weights),
        "realized_bucket_weights": dict(realized),
        "drift_prior_to_feasible_pp": {k: v * 100 for k, v in drift_pf.items()},
        "drift_feasible_to_realized_pp": {k: v * 100 for k, v in drift_fr.items()},
        "envelope_by_bucket": envelope_status,
        "all_buckets_within_envelope": all_within,
        "binding_stage2": dict(contract.binding_stage2),
    }


def enforce_stage3_mandate_qp(
    weights: dict[str, float],
    bucket_to_tickers: dict[str, list[str]],
    w_ref: dict[str, float],
    *,
    unallocated_mass: float = 0.0,
) -> tuple[dict[str, float], dict[str, object]]:
    """Conditional Stage 3 B: QP toward feasible w_ref when risk>70% or mass gap."""
    from tradingagents.skills.portfolio.hrp_shortfall import (
        rescale_weights_to_bucket_targets,
    )

    realized = realized_bucket_weights(weights, bucket_to_tickers)
    risk_sum = sum(float(realized.get(b, 0.0)) for b in RISK_BUCKETS)
    total = sum(realized.values())
    audit: dict[str, object] = {
        "triggered": False,
        "risk_sum_pre": round(risk_sum, 4),
        "portfolio_sum_pre": round(total, 4),
        "unallocated_mass_in": round(float(unallocated_mass), 6),
    }
    trigger = (
        risk_sum > MANDATE_RISK_CAP + 1e-9
        or float(unallocated_mass) > 1e-9
        or total < 1.0 - 1e-6
    )
    if not trigger:
        return dict(weights), audit

    w_ref_full = {b: float(w_ref.get(b, 0.0)) for b in BUCKETS}
    projected = project_to_mandate_qp(w_ref_full)
    new_weights = rescale_weights_to_bucket_targets(
        weights, bucket_to_tickers, projected,
    )
    post = realized_bucket_weights(new_weights, bucket_to_tickers)
    audit.update({
        "triggered": True,
        "clip_applied": True,
        "risk_sum_post": round(
            sum(float(post.get(b, 0.0)) for b in RISK_BUCKETS), 4,
        ),
        "portfolio_sum_post": round(sum(post.values()), 4),
        "projection_l2_distance": round(
            sum((projected[b] - w_ref_full[b]) ** 2 for b in BUCKETS) ** 0.5,
            6,
        ),
    })
    return new_weights, audit


def clip_overlay_bucket_risk(
    weights: dict[str, float],
    bucket_to_tickers: dict[str, list[str]],
) -> tuple[dict[str, float], dict[str, object]]:
    """P2b: post-overlay mandate QP on bucket totals + within-bucket rescale."""
    realized = realized_bucket_weights(weights, bucket_to_tickers)
    risk_sum = sum(float(realized.get(b, 0.0)) for b in RISK_BUCKETS)
    audit: dict[str, object] = {
        "risk_sum_pre_clip": round(risk_sum, 4),
        "clip_applied": False,
    }
    if risk_sum <= MANDATE_RISK_CAP + 1e-9:
        return dict(weights), audit

    target_buckets = project_to_mandate_qp(
        {b: float(realized.get(b, 0.0)) for b in BUCKETS},
    )
    new_weights: dict[str, float] = {}
    for bucket, tickers in bucket_to_tickers.items():
        old_bucket_sum = sum(float(weights.get(t, 0.0)) for t in tickers)
        new_bucket_sum = float(target_buckets.get(bucket, 0.0))
        if old_bucket_sum > 1e-12 and tickers:
            scale = new_bucket_sum / old_bucket_sum
            for t in tickers:
                new_weights[t] = float(weights.get(t, 0.0)) * scale
        elif tickers:
            share = new_bucket_sum / len(tickers)
            for t in tickers:
                new_weights[t] = share

    total = sum(new_weights.values())
    if total > 1e-12 and abs(total - 1.0) > 1e-6:
        new_weights = {t: w / total for t, w in new_weights.items()}

    audit["clip_applied"] = True
    audit["risk_sum_post_clip"] = round(
        sum(float(target_buckets.get(b, 0.0)) for b in RISK_BUCKETS), 4,
    )
    return new_weights, audit


def apply_theme_portfolio_limits(
    weights: dict[str, float],
    theme_limits: list[ThemeLimit],
    sub_category_lookup: dict[str, str | None],
    *,
    cash_tickers: list[str] | None = None,
) -> tuple[dict[str, float], list[dict]]:
    """Cap portfolio-wide sub_category exposure; excess → cash tickers if any."""
    if not weights or not theme_limits:
        return weights, []

    new_weights = dict(weights)
    events: list[dict] = []
    total = sum(new_weights.values())
    if total <= 0:
        return new_weights, events

    cash_tickers = [t for t in (cash_tickers or []) if t in new_weights]
    portfolio_total = sum(new_weights.values())

    for limit in theme_limits:
        sc = limit.sub_category
        cap = limit.max_portfolio_share * portfolio_total
        themed = [
            t for t in new_weights
            if (sub_category_lookup.get(t) or "") == sc
        ]
        sc_sum = sum(new_weights[t] for t in themed)
        if sc_sum <= cap + 1e-9:
            continue
        excess = sc_sum - cap
        scale = cap / sc_sum
        for t in themed:
            new_weights[t] *= scale
        if cash_tickers:
            share = excess / len(cash_tickers)
            for t in cash_tickers:
                new_weights[t] = new_weights.get(t, 0.0) + share
        else:
            others = [t for t in new_weights if t not in themed]
            others_total = sum(new_weights[t] for t in others)
            if others_total > 0:
                for t in others:
                    new_weights[t] += excess * (new_weights[t] / others_total)
            else:
                logger.warning(
                    "theme limit %s: no cash or other tickers for excess %.4f",
                    sc, excess,
                )
        events.append({
            "sub_category": sc,
            "max_portfolio_share": limit.max_portfolio_share,
            "original_sum": float(sc_sum),
            "capped_to": float(cap),
            "routed_to_cash": bool(cash_tickers),
        })

    return new_weights, events


def redistribute_subcategory_excess_to_cash(
    weights: dict[str, float],
    tickers: list[str],
    excess: float,
    cash_tickers: list[str],
) -> dict[str, float]:
    """Scale capped tickers and park excess on cash_mmf names."""
    new_weights = dict(weights)
    if excess <= 1e-12:
        return new_weights
    if cash_tickers:
        share = excess / len(cash_tickers)
        for t in cash_tickers:
            new_weights[t] = new_weights.get(t, 0.0) + share
        return new_weights
    others = [t for t in new_weights if t not in tickers]
    others_total = sum(new_weights[t] for t in others)
    if others_total > 0:
        for t in others:
            new_weights[t] += excess * (new_weights[t] / others_total)
    return new_weights
