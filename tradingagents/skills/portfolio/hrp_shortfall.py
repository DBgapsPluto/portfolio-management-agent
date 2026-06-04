"""HRP/NCO per-bucket mass: R1–R3 shortfall rules (no risk-bucket spill)."""
from __future__ import annotations

import logging
from typing import Any

from tradingagents.skills.portfolio.contract_stage3 import realized_bucket_weights
from tradingagents.skills.research.factor_to_bucket import BUCKETS, RISK_BUCKETS

logger = logging.getLogger(__name__)

NON_RISK_BUCKETS: tuple[str, ...] = tuple(b for b in BUCKETS if b not in RISK_BUCKETS)

_MASS_TOL = 1e-9


def _risk_sum(bucket_sums: dict[str, float]) -> float:
    return sum(float(bucket_sums.get(b, 0.0)) for b in RISK_BUCKETS)


def _scale_bucket_down(
    weights: dict[str, float],
    tickers: list[str],
    factor: float,
) -> None:
    if factor >= 1.0 - _MASS_TOL:
        return
    for t in tickers:
        if t in weights:
            weights[t] = float(weights[t]) * factor


def _add_bucket_mass(
    weights: dict[str, float],
    tickers: list[str],
    amount: float,
) -> None:
    if amount <= _MASS_TOL or not tickers:
        return
    existing = sum(float(weights.get(t, 0.0)) for t in tickers)
    if existing > _MASS_TOL:
        for t in tickers:
            if t in weights:
                weights[t] = float(weights[t]) + amount * (
                    float(weights[t]) / existing
                )
    else:
        share = amount / len(tickers)
        for t in tickers:
            weights[t] = float(weights.get(t, 0.0)) + share


def finalize_per_bucket_mass(
    weights: dict[str, float],
    bucket_to_tickers: dict[str, list[str]],
    target_map: dict[str, float],
    *,
    label: str = "hrp",
) -> tuple[dict[str, float], dict[str, Any]]:
    """R1–R3: no risk spill; shortfall → non-risk headroom; else leave mass for Stage 3 QP."""
    out = dict(weights)
    audit: dict[str, Any] = {
        f"{label}_final_norm_intervened": False,
        f"{label}_unallocated_mass": 0.0,
        f"{label}_shortfall_to_non_risk_pp": 0.0,
        f"{label}_risk_bucket_trimmed": [],
    }

    # R1: risk bucket totals must not exceed targets.
    trimmed: list[str] = []
    for b in RISK_BUCKETS:
        tickers = bucket_to_tickers.get(b) or []
        cap = float(target_map.get(b, 0.0))
        b_sum = sum(float(out.get(t, 0.0)) for t in tickers)
        if b_sum > cap + _MASS_TOL and b_sum > _MASS_TOL:
            _scale_bucket_down(out, tickers, cap / b_sum)
            trimmed.append(b)
    if trimmed:
        audit[f"{label}_risk_bucket_trimmed"] = trimmed

    bucket_sums = realized_bucket_weights(out, bucket_to_tickers)
    total = sum(bucket_sums.values())

    if total < 1.0 - _MASS_TOL:
        shortfall = 1.0 - total
        room = {
            b: max(0.0, float(target_map.get(b, 0.0)) - float(bucket_sums.get(b, 0.0)))
            for b in NON_RISK_BUCKETS
        }
        room_sum = sum(room.values())
        absorbed = 0.0
        if room_sum > _MASS_TOL:
            for b in NON_RISK_BUCKETS:
                add = shortfall * (room[b] / room_sum)
                _add_bucket_mass(out, bucket_to_tickers.get(b) or [], add)
                absorbed += add
            audit[f"{label}_shortfall_to_non_risk_pp"] = round(absorbed * 100, 4)
            audit[f"{label}_final_norm_intervened"] = absorbed > _MASS_TOL
        remaining = shortfall - absorbed
        if remaining > _MASS_TOL:
            audit[f"{label}_unallocated_mass"] = round(remaining, 6)
            logger.info(
                "%s: %.4f mass unallocated after non-risk spill — Stage 3 QP (B)",
                label,
                remaining,
            )

    elif total > 1.0 + _MASS_TOL:
        excess = total - 1.0
        audit[f"{label}_final_norm_intervened"] = True
        # Trim excess without raising risk above target.
        for _ in range(32):
            bucket_sums = realized_bucket_weights(out, bucket_to_tickers)
            if sum(bucket_sums.values()) <= 1.0 + _MASS_TOL:
                break
            for b in NON_RISK_BUCKETS:
                tickers = bucket_to_tickers.get(b) or []
                b_sum = float(bucket_sums.get(b, 0.0))
                if b_sum <= _MASS_TOL:
                    continue
                cut = min(excess, b_sum * 0.5)
                _scale_bucket_down(out, tickers, (b_sum - cut) / b_sum)
                excess = sum(
                    realized_bucket_weights(out, bucket_to_tickers).values(),
                ) - 1.0
                if excess <= _MASS_TOL:
                    break
            if excess <= _MASS_TOL:
                break
            for b in RISK_BUCKETS:
                tickers = bucket_to_tickers.get(b) or []
                cap = float(target_map.get(b, 0.0))
                b_sum = float(bucket_sums.get(b, 0.0))
                if b_sum > cap + _MASS_TOL:
                    _scale_bucket_down(out, tickers, cap / b_sum)
            bucket_sums = realized_bucket_weights(out, bucket_to_tickers)
            excess = sum(bucket_sums.values()) - 1.0
            if excess <= _MASS_TOL:
                break

    return out, audit


def place_unallocated_in_cash(
    weights: dict[str, float],
    cash_tickers: list[str],
    unallocated_mass: float,
) -> dict[str, float]:
    """Bookkeeping sink so ticker weights sum to 1 without scaling risk buckets."""
    if float(unallocated_mass) <= _MASS_TOL or not cash_tickers:
        return weights
    out = dict(weights)
    _add_bucket_mass(out, cash_tickers, float(unallocated_mass))
    return out


def rescale_weights_to_bucket_targets(
    weights: dict[str, float],
    bucket_to_tickers: dict[str, list[str]],
    target_buckets: dict[str, float],
) -> dict[str, float]:
    """Within-bucket proportional rescale to match 8-bucket targets."""
    new_weights: dict[str, float] = {}
    for bucket, tickers in bucket_to_tickers.items():
        old_bucket_sum = sum(float(weights.get(t, 0.0)) for t in tickers)
        new_bucket_sum = float(target_buckets.get(bucket, 0.0))
        if old_bucket_sum > _MASS_TOL and tickers:
            scale = new_bucket_sum / old_bucket_sum
            for t in tickers:
                if t in weights:
                    new_weights[t] = float(weights[t]) * scale
        elif tickers and new_bucket_sum > _MASS_TOL:
            share = new_bucket_sum / len(tickers)
            for t in tickers:
                new_weights[t] = share

    total = sum(new_weights.values())
    if total > _MASS_TOL and abs(total - 1.0) > 1e-6:
        new_weights = {t: w / total for t, w in new_weights.items()}
    return new_weights
