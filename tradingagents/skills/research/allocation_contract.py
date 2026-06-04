"""Build Stage 2 allocation contract (prior → investability → feasible)."""
from __future__ import annotations

import logging
from datetime import date
from typing import Any

import numpy as np

from tradingagents.dataflows.universe import Universe
from tradingagents.schemas.allocation_contract import (
    AllocationContract,
    BucketEnvelope,
    InvestabilitySnapshot,
    ThemeLimit,
)
from tradingagents.schemas.portfolio import BucketTarget
from tradingagents.skills.portfolio.bucket_sync import (
    ContractInfeasibleError,
    build_infeasibility_report,
    compute_bucket_selectability,
    format_infeasibility_message,
)
from tradingagents.skills.portfolio.candidate_selector import list_eligible_tickers
from tradingagents.skills.research.factor_to_bucket import BUCKETS, RISK_BUCKETS

logger = logging.getLogger(__name__)

NUMERICAL_TOLERANCE: float = 1e-9
CASH_CAP_FOR_OVERFLOW: float = 0.40

DEFAULT_THEME_LIMITS: tuple[ThemeLimit, ...] = (
    ThemeLimit(sub_category="gold", max_portfolio_share=0.50),
)

IMPLIED_RETURN_SCALE: float = 0.10
IMPLIED_RETURN_CLIP: float = 0.15


def _config_float(config: dict[str, Any] | None, key: str, default: float) -> float:
    if isinstance(config, dict) and key in config:
        return float(config[key])
    return default


def compute_investability(
    prior_weights: dict[str, float],
    eligible_by_bucket: dict[str, list[str]],
    *,
    single_etf_cap: float,
    alpha_scores_by_bucket: dict[str, dict[str, float]] | None = None,
    n_selectable_by_bucket: dict[str, int] | None = None,
) -> dict[str, InvestabilitySnapshot]:
    """Per-bucket eligible / selectable counts and max realizable weight."""
    if n_selectable_by_bucket is None and alpha_scores_by_bucket is not None:
        n_selectable_by_bucket = compute_bucket_selectability(
            eligible_by_bucket=eligible_by_bucket,
            alpha_scores_by_bucket=alpha_scores_by_bucket,
        )
    out: dict[str, InvestabilitySnapshot] = {}
    for bucket in BUCKETS:
        tickers = eligible_by_bucket.get(bucket, [])
        n_elig = len(tickers)
        n_sel = (
            n_selectable_by_bucket.get(bucket, n_elig)
            if n_selectable_by_bucket is not None
            else n_elig
        )
        prior_b = float(prior_weights.get(bucket, 0.0))
        if n_sel == 0:
            max_r = 0.0
        elif n_sel == 1:
            max_r = min(prior_b, single_etf_cap)
        else:
            max_r = prior_b
        out[bucket] = InvestabilitySnapshot(
            n_eligible=n_elig,
            n_selectable=n_sel,
            max_realizable_weight=float(max_r),
            tickers_sample=tickers[:5],
        )
    return out


def project_investability_risk_overflow(
    prior_weights: dict[str, float],
    investability: dict[str, InvestabilitySnapshot],
    *,
    cash_cap_floor: float = CASH_CAP_FOR_OVERFLOW,
    as_of_date: str | None = None,
) -> tuple[dict[str, float], dict[str, str], dict[str, object]]:
    """Thin / capped buckets → cash or selectable buckets (P1-2 / P1-2a)."""
    feasible = {b: float(prior_weights.get(b, 0.0)) for b in BUCKETS}
    binding: dict[str, str] = {}
    removed_to_cash: dict[str, float] = {}

    for bucket in BUCKETS:
        inv = investability[bucket]
        prior_b = float(prior_weights.get(bucket, 0.0))
        if inv.n_eligible == 0 and prior_b > NUMERICAL_TOLERANCE:
            feasible[bucket] = 0.0
            binding[bucket] = "thin_universe"
            removed_to_cash[bucket] = prior_b
        elif inv.n_selectable == 0 and inv.n_eligible > 0 and prior_b > NUMERICAL_TOLERANCE:
            feasible[bucket] = 0.0
            binding[bucket] = "no_positive_alpha"
            removed_to_cash[bucket] = prior_b
        elif prior_b > inv.max_realizable_weight + NUMERICAL_TOLERANCE:
            feasible[bucket] = inv.max_realizable_weight
            binding[bucket] = "capped_realizable"
            removed_to_cash[bucket] = prior_b - inv.max_realizable_weight
        else:
            binding[bucket] = "ok"

    lost = sum(removed_to_cash.values())
    audit: dict[str, object] = {
        "removed_to_cash": removed_to_cash,
        "lost_mass": lost,
    }
    if lost <= NUMERICAL_TOLERANCE:
        total = sum(feasible.values())
        if abs(total - 1.0) > NUMERICAL_TOLERANCE:
            feasible = _renormalize(feasible)
        return feasible, binding, audit

    n_sel_cash = investability["cash_mmf"].n_selectable
    if n_sel_cash == 0:
        recipients = [
            b for b in BUCKETS
            if investability[b].n_selectable > 0
        ]
        if not recipients:
            report = build_infeasibility_report(
                error_kind="contract_infeasible",
                as_of_date=as_of_date,
                prior_weights=prior_weights,
                feasible_weights=feasible,
                binding_stage2=binding,
                eligible_by_bucket=None,
                n_selectable_by_bucket={
                    b: investability[b].n_selectable for b in BUCKETS
                },
                bucket_chosen=None,
                alpha_scores_by_bucket=None,
                lost_mass_pp=round(lost * 100, 4),
            )
            msg = format_infeasibility_message(report)
            logger.error(msg)
            raise ContractInfeasibleError(msg)

        denom = sum(float(prior_weights.get(b, 0.0)) for b in recipients)
        for b in recipients:
            share = (
                float(prior_weights.get(b, 0.0)) / denom
                if denom > NUMERICAL_TOLERANCE
                else 1.0 / len(recipients)
            )
            feasible[b] += lost * share
        audit["lost_routed_skip_cash"] = {
            b: lost * (
                float(prior_weights.get(b, 0.0)) / denom
                if denom > NUMERICAL_TOLERANCE
                else 1.0 / len(recipients)
            )
            for b in recipients
        }
    else:
        feasible["cash_mmf"] = feasible.get("cash_mmf", 0.0) + lost
        prior_cash = float(prior_weights.get("cash_mmf", 0.0))
        effective_cap = max(cash_cap_floor, prior_cash)
        overflow = 0.0
        if feasible["cash_mmf"] > effective_cap + NUMERICAL_TOLERANCE:
            overflow = feasible["cash_mmf"] - effective_cap
            feasible["cash_mmf"] = effective_cap
            audit["cash_cap_triggered"] = True
            audit["cash_overflow"] = overflow
        else:
            audit["cash_cap_triggered"] = False

        if overflow > NUMERICAL_TOLERANCE:
            risk_targets = [
                b for b in RISK_BUCKETS
                if investability[b].n_selectable > 0 and b not in removed_to_cash
            ]
            if not risk_targets:
                risk_targets = [
                    b for b in RISK_BUCKETS if investability[b].n_selectable > 0
                ]
            if risk_targets:
                denom = sum(float(prior_weights.get(b, 0.0)) for b in risk_targets)
                for b in risk_targets:
                    share = (
                        float(prior_weights.get(b, 0.0)) / denom
                        if denom > NUMERICAL_TOLERANCE
                        else 1.0 / len(risk_targets)
                    )
                    feasible[b] += overflow * share
                audit["overflow_to_risk_buckets"] = {
                    b: overflow * (
                        float(prior_weights.get(b, 0.0)) / denom
                        if denom > NUMERICAL_TOLERANCE
                        else 1.0 / len(risk_targets)
                    )
                    for b in risk_targets
                }
            else:
                feasible["cash_mmf"] += overflow
                logger.warning(
                    "investability overflow %.4f kept in cash (no selectable RISK bucket)",
                    overflow,
                )
                audit["overflow_kept_in_cash"] = overflow

    total = sum(feasible.values())
    if abs(total - 1.0) > NUMERICAL_TOLERANCE:
        feasible = _renormalize(feasible)
        audit["renormalized"] = True

    return feasible, binding, audit


def _renormalize(weights: dict[str, float]) -> dict[str, float]:
    total = sum(weights.values())
    if total <= NUMERICAL_TOLERANCE:
        raise RuntimeError("investability projection: all bucket weights zero")
    return {b: weights[b] / total for b in BUCKETS}


def compute_implied_bucket_returns(
    factor_contributions: dict[str, dict[str, float]],
    *,
    scale: float = IMPLIED_RETURN_SCALE,
    clip: float = IMPLIED_RETURN_CLIP,
) -> dict[str, float]:
    implied: dict[str, float] = {}
    for bucket in BUCKETS:
        raw = sum(
            float((factor_contributions.get(factor) or {}).get(bucket, 0.0))
            for factor in factor_contributions
        )
        implied[bucket] = float(np.clip(scale * raw, -clip, clip))
    return implied


def build_envelope_around_center(
    center: dict[str, float],
    *,
    band: float,
    investability: dict[str, InvestabilitySnapshot],
) -> dict[str, BucketEnvelope]:
    envelope: dict[str, BucketEnvelope] = {}
    for bucket in BUCKETS:
        c = float(center[bucket])
        inv = investability[bucket]
        hi = min(c + band, inv.max_realizable_weight, 1.0)
        lo = max(0.0, c - band)
        if inv.n_selectable == 0:
            lo = hi = 0.0
        elif lo > hi:
            lo = hi = min(c, hi)
        envelope[bucket] = BucketEnvelope(lo=lo, hi=hi)
    return envelope


def build_allocation_contract(
    *,
    prior_weights: dict[str, float],
    bond_tips_share: float,
    universe: Universe | None,
    as_of: date | None,
    factor_contributions: dict[str, dict[str, float]],
    config: dict[str, Any] | None = None,
    eligible_by_bucket: dict[str, list[str]] | None = None,
    alpha_scores_by_bucket: dict[str, dict[str, float]] | None = None,
) -> AllocationContract:
    """prior (post-LLM) → investability → feasible; mandate already in prior path."""
    config = config or {}
    single_etf_cap = _config_float(config, "contract_single_etf_cap", 0.05)
    envelope_band = _config_float(config, "contract_envelope_band_pp", 0.02)

    prior = {b: float(prior_weights.get(b, 0.0)) for b in BUCKETS}
    total_prior = sum(prior.values())
    if abs(total_prior - 1.0) > 1e-5:
        prior = _renormalize(prior)

    investability: dict[str, InvestabilitySnapshot] = {
        b: InvestabilitySnapshot(n_eligible=0, n_selectable=0, max_realizable_weight=0.0)
        for b in BUCKETS
    }
    binding = {b: "universe_skipped" for b in BUCKETS}
    projection_audit: dict[str, object] = {"universe_loaded": False}

    if universe is not None and as_of is not None:
        if eligible_by_bucket is None:
            probe = BucketTarget(
                weights=dict(prior),
                bond_tips_share=bond_tips_share,
                rationale="contract probe",
            )
            eligible_by_bucket = list_eligible_tickers(universe, probe, as_of=as_of)
        investability = compute_investability(
            prior,
            eligible_by_bucket,
            single_etf_cap=single_etf_cap,
            alpha_scores_by_bucket=alpha_scores_by_bucket,
        )
        as_of_str = as_of.isoformat() if hasattr(as_of, "isoformat") else str(as_of)
        feasible, binding, projection_audit = project_investability_risk_overflow(
            prior,
            investability,
            as_of_date=as_of_str,
        )
        projection_audit["universe_loaded"] = True
        projection_audit["eligible_counts"] = {
            b: len(eligible_by_bucket.get(b, [])) for b in BUCKETS
        }
        projection_audit["selectable_counts"] = {
            b: investability[b].n_selectable for b in BUCKETS
        }
    else:
        feasible = dict(prior)
        binding = {b: "ok" for b in BUCKETS}
        projection_audit["feasible_equals_prior"] = True

    envelope = build_envelope_around_center(
        feasible, band=envelope_band, investability=investability,
    )
    implied = compute_implied_bucket_returns(factor_contributions)

    return AllocationContract(
        prior_weights=prior,
        feasible_weights=feasible,
        envelope=envelope,
        theme_limits=list(DEFAULT_THEME_LIMITS),
        implied_bucket_returns=implied,
        bond_tips_share=bond_tips_share,
        investability=investability,
        binding_stage2=binding,
        projection_audit=projection_audit,
    )
