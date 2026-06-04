"""Stage 2 bucket anchors: scenario body + covenant (regime modifiers on non-risk).

Grill-me A8: scenario owns bucket body; anchor_covenant = scenario pure + layer-0
regime modifiers on non-risk buckets only. Legacy blend_bucket_anchors wraps compose.
"""
from __future__ import annotations

from typing import Final

from tradingagents.schemas.macro import RegimeQuadrant
from tradingagents.skills.portfolio.bl_views import SCENARIO_BUCKET_RULEBOOK
from tradingagents.skills.research.factor_to_bucket import (
    BUCKETS,
    INITIAL_TIPS_BASELINE,
    RISK_BUCKETS,
)

NON_RISK_BUCKETS: Final[tuple[str, ...]] = tuple(
    b for b in BUCKETS if b not in RISK_BUCKETS
)

# Scenario keys must match bl_views.SCENARIO_BUCKET_RULEBOOK and derive_dominant_scenario.
SCENARIO_ANCHOR_KEYS: Final[tuple[str, ...]] = tuple(SCENARIO_BUCKET_RULEBOOK.keys())

DEFAULT_REGIME_WEIGHT: Final[float] = 0.45
DEFAULT_SCENARIO_WEIGHT: Final[float] = 0.55

_ANCHOR_SUM_TOL: Final[float] = 1e-6
_RISK_CAP: Final[float] = 0.70

# Hand-tuned regime anchors (sum=1, risk≤0.70). Cyclical capped for narrow db_gaps universe.
REGIME_BUCKET_ANCHORS: Final[dict[RegimeQuadrant, dict[str, float]]] = {
    "growth_inflation": {
        "kr_equity": 0.12,
        "global_equity": 0.22,
        "precious_metals": 0.08,
        "cyclical_commodity_fx": 0.10,
        "kr_bond": 0.10,
        "credit": 0.08,
        "global_duration": 0.08,
        "cash_mmf": 0.22,
    },
    "growth_disinflation": {
        "kr_equity": 0.14,
        "global_equity": 0.26,
        "precious_metals": 0.05,
        "cyclical_commodity_fx": 0.07,
        "kr_bond": 0.13,
        "credit": 0.11,
        "global_duration": 0.13,
        "cash_mmf": 0.11,
    },
    "recession_inflation": {
        "kr_equity": 0.06,
        "global_equity": 0.08,
        "precious_metals": 0.18,
        "cyclical_commodity_fx": 0.11,
        "kr_bond": 0.12,
        "credit": 0.04,
        "global_duration": 0.10,
        "cash_mmf": 0.31,
    },
    "recession_disinflation": {
        "kr_equity": 0.08,
        "global_equity": 0.10,
        "precious_metals": 0.07,
        "cyclical_commodity_fx": 0.05,
        "kr_bond": 0.18,
        "credit": 0.06,
        "global_duration": 0.20,
        "cash_mmf": 0.26,
    },
}

# Scenario anchors: economics-first weights; rulebook signs inform tilts, not literal returns.
SCENARIO_BUCKET_ANCHORS: Final[dict[str, dict[str, float]]] = {
    "goldilocks": {
        "kr_equity": 0.15,
        "global_equity": 0.28,
        "precious_metals": 0.05,
        "cyclical_commodity_fx": 0.07,
        "kr_bond": 0.12,
        "credit": 0.12,
        "global_duration": 0.10,
        "cash_mmf": 0.11,
    },
    "overheating": {
        "kr_equity": 0.11,
        "global_equity": 0.20,
        "precious_metals": 0.09,
        "cyclical_commodity_fx": 0.12,
        "kr_bond": 0.09,
        "credit": 0.09,
        "global_duration": 0.07,
        "cash_mmf": 0.23,
    },
    "late_cycle": {
        "kr_equity": 0.10,
        "global_equity": 0.16,
        "precious_metals": 0.11,
        "cyclical_commodity_fx": 0.09,
        "kr_bond": 0.14,
        "credit": 0.07,
        "global_duration": 0.14,
        "cash_mmf": 0.19,
    },
    "stagflation": {
        "kr_equity": 0.06,
        "global_equity": 0.07,
        "precious_metals": 0.17,
        "cyclical_commodity_fx": 0.11,
        "kr_bond": 0.11,
        "credit": 0.04,
        "global_duration": 0.09,
        "cash_mmf": 0.35,
    },
    "broad_recession": {
        "kr_equity": 0.07,
        "global_equity": 0.09,
        "precious_metals": 0.08,
        "cyclical_commodity_fx": 0.05,
        "kr_bond": 0.17,
        "credit": 0.05,
        "global_duration": 0.18,
        "cash_mmf": 0.31,
    },
    "kr_stress": {
        "kr_equity": 0.08,
        "global_equity": 0.18,
        "precious_metals": 0.10,
        "cyclical_commodity_fx": 0.08,
        "kr_bond": 0.12,
        "credit": 0.08,
        "global_duration": 0.12,
        "cash_mmf": 0.24,
    },
    "global_credit": {
        "kr_equity": 0.08,
        "global_equity": 0.10,
        "precious_metals": 0.07,
        "cyclical_commodity_fx": 0.05,
        "kr_bond": 0.15,
        "credit": 0.04,
        "global_duration": 0.19,
        "cash_mmf": 0.32,
    },
    "ai_concentration": {
        "kr_equity": 0.12,
        "global_equity": 0.26,
        "precious_metals": 0.05,
        "cyclical_commodity_fx": 0.06,
        "kr_bond": 0.11,
        "credit": 0.11,
        "global_duration": 0.10,
        "cash_mmf": 0.19,
    },
    "kr_boom": {
        "kr_equity": 0.20,
        "global_equity": 0.22,
        "precious_metals": 0.04,
        "cyclical_commodity_fx": 0.08,
        "kr_bond": 0.10,
        "credit": 0.11,
        "global_duration": 0.09,
        "cash_mmf": 0.16,
    },
}

# TIPS share baselines by scenario/regime (bond bucket inflation hedge dial).
_SCENARIO_TIPS_ANCHOR: Final[dict[str, float]] = {
    "goldilocks": 0.22,
    "overheating": 0.35,
    "late_cycle": 0.30,
    "stagflation": 0.42,
    "broad_recession": 0.28,
    "kr_stress": 0.26,
    "global_credit": 0.25,
    "ai_concentration": 0.24,
    "kr_boom": 0.20,
}

_REGIME_TIPS_ANCHOR: Final[dict[RegimeQuadrant, float]] = {
    "growth_inflation": 0.38,
    "growth_disinflation": 0.24,
    "recession_inflation": 0.40,
    "recession_disinflation": 0.26,
}


def _normalize_weights(raw: dict[str, float]) -> dict[str, float]:
    total = sum(float(raw.get(b, 0.0)) for b in BUCKETS)
    if total <= 0.0:
        uniform = 1.0 / len(BUCKETS)
        return {b: uniform for b in BUCKETS}
    return {b: float(raw.get(b, 0.0)) / total for b in BUCKETS}


def validate_anchor(weights: dict[str, float], *, risk_cap: float = _RISK_CAP) -> bool:
    """True when weights sum≈1, all keys known, risk bucket sum ≤ risk_cap."""
    if not all(b in BUCKETS for b in weights):
        return False
    if abs(sum(float(weights.get(b, 0.0)) for b in BUCKETS) - 1.0) > _ANCHOR_SUM_TOL:
        return False
    risk = sum(float(weights.get(b, 0.0)) for b in RISK_BUCKETS)
    return risk <= risk_cap + _ANCHOR_SUM_TOL


def anchor_scenario_pure(scenario: str) -> dict[str, float]:
    """Scenario body anchor from SCENARIO_BUCKET_ANCHORS, normalized."""
    row = SCENARIO_BUCKET_ANCHORS.get(scenario)
    if row is None:
        row = SCENARIO_BUCKET_ANCHORS["goldilocks"]
    return _normalize_weights(dict(row))


def apply_scenario_real_caps(
    scenario: str,
    weights: dict[str, float],
    *,
    goldilocks_pc_cap: float = 0.14,
    overheating_cyclical_cap: float = 0.12,
    stagflation_cyclical_cap: float = 0.12,
) -> dict[str, float]:
    """D0+D1: scenario real-asset caps on pure anchor before regime modifiers."""
    w = dict(weights)
    if scenario == "goldilocks":
        pc = precious_cyclical_sum(w)
        if pc > goldilocks_pc_cap + 1e-12:
            scale = goldilocks_pc_cap / pc
            w["precious_metals"] = float(w["precious_metals"]) * scale
            w["cyclical_commodity_fx"] = float(w["cyclical_commodity_fx"]) * scale
    elif scenario == "overheating":
        cap = overheating_cyclical_cap
        if float(w.get("cyclical_commodity_fx", 0.0)) > cap + 1e-12:
            w["cyclical_commodity_fx"] = cap
    elif scenario == "stagflation":
        cap = stagflation_cyclical_cap
        if float(w.get("cyclical_commodity_fx", 0.0)) > cap + 1e-12:
            w["cyclical_commodity_fx"] = cap
    return _normalize_weights(w)


def apply_regime_modifiers(
    scenario_anchor: dict[str, float],
    regime_quadrant: RegimeQuadrant | str,
    *,
    max_pp: float = 0.02,
) -> tuple[dict[str, float], dict[str, object]]:
    """M3 layer-0: ±max_pp per non-risk bucket vs regime anchor, then renormalize."""
    regime_key = regime_quadrant  # type: ignore[assignment]
    regime_w = REGIME_BUCKET_ANCHORS.get(regime_key)  # type: ignore[arg-type]
    if regime_w is None:
        regime_w = REGIME_BUCKET_ANCHORS["growth_disinflation"]

    covenant = dict(scenario_anchor)
    modifiers_pp: dict[str, float] = {}
    cap = float(max_pp)
    for b in NON_RISK_BUCKETS:
        delta = float(regime_w[b]) - float(scenario_anchor.get(b, 0.0))
        clamped = max(-cap, min(cap, delta))
        modifiers_pp[b] = clamped * 100.0
        covenant[b] = float(scenario_anchor.get(b, 0.0)) + clamped

    return _normalize_weights(covenant), {
        "regime_modifiers_pp": modifiers_pp,
        "layer": 0,
    }


def compose_anchor_covenant(
    regime_quadrant: RegimeQuadrant | str,
    scenario: str,
    *,
    max_regime_pp: float = 0.02,
    goldilocks_pc_cap: float = 0.14,
    overheating_cyclical_cap: float = 0.12,
    stagflation_cyclical_cap: float = 0.12,
) -> tuple[dict[str, float], dict[str, float], dict[str, object]]:
    """Returns (anchor_covenant, anchor_scenario_pure, audit)."""
    pure = anchor_scenario_pure(scenario)
    capped = apply_scenario_real_caps(
        scenario,
        pure,
        goldilocks_pc_cap=goldilocks_pc_cap,
        overheating_cyclical_cap=overheating_cyclical_cap,
        stagflation_cyclical_cap=stagflation_cyclical_cap,
    )
    covenant, regime_audit = apply_regime_modifiers(
        capped, regime_quadrant, max_pp=max_regime_pp,
    )
    audit: dict[str, object] = {
        "anchor_scenario_pure": dict(pure),
        "anchor_scenario_capped": dict(capped),
        **regime_audit,
    }
    return covenant, pure, audit


def thesis_tags(
    regime_quadrant: RegimeQuadrant | str,
    scenario: str,
) -> list[str]:
    """G2: narrative thesis tags for tilt gates."""
    tags: list[str] = []
    if regime_quadrant == "growth_inflation":
        tags.append("inflation_background")
    if scenario == "goldilocks":
        tags.append("goldilocks_narrative")
    if scenario in ("overheating", "stagflation"):
        tags.append("cyclical_capped_scenario")
    return tags


def blend_bucket_anchors(
    regime_quadrant: RegimeQuadrant | str,
    scenario: str,
    *,
    regime_weight: float = DEFAULT_REGIME_WEIGHT,
    scenario_weight: float = DEFAULT_SCENARIO_WEIGHT,
) -> dict[str, float]:
    """Deprecated wrapper — returns anchor_covenant (ignores legacy 45/55 weights)."""
    _ = (regime_weight, scenario_weight)
    covenant, _, _ = compose_anchor_covenant(regime_quadrant, scenario)
    return covenant


def anchor_tips_share(
    scenario: str,
    regime_quadrant: RegimeQuadrant | str,
    *,
    regime_weight: float = DEFAULT_REGIME_WEIGHT,
    scenario_weight: float = DEFAULT_SCENARIO_WEIGHT,
) -> float:
    """Blended TIPS share anchor ∈ [0, 1] for bond sub-allocation."""
    rw = float(regime_weight)
    sw = float(scenario_weight)
    denom = rw + sw
    if denom <= 0.0:
        rw, sw, denom = 0.5, 0.5, 1.0
    rw /= denom
    sw /= denom
    regime_key = regime_quadrant  # type: ignore[assignment]
    tips_r = _REGIME_TIPS_ANCHOR.get(regime_key, INITIAL_TIPS_BASELINE)  # type: ignore[arg-type]
    tips_s = _SCENARIO_TIPS_ANCHOR.get(scenario, INITIAL_TIPS_BASELINE)
    tips = rw * float(tips_r) + sw * float(tips_s)
    return max(0.0, min(1.0, tips))


def rulebook_implied_weights(scenario: str) -> dict[str, float]:
    """Diagnostic: positive-part normalization of SCENARIO_BUCKET_RULEBOOK returns."""
    row = SCENARIO_BUCKET_RULEBOOK.get(scenario)
    if row is None:
        return dict(SCENARIO_BUCKET_ANCHORS["goldilocks"])
    floor = 0.02
    shifted = {b: max(floor, float(row.get(b, 0.0)) + 0.15) for b in BUCKETS}
    return _normalize_weights(shifted)


def risk_bucket_sum(weights: dict[str, float]) -> float:
    return sum(float(weights.get(b, 0.0)) for b in RISK_BUCKETS)


def precious_cyclical_sum(weights: dict[str, float]) -> float:
    return (
        float(weights.get("precious_metals", 0.0))
        + float(weights.get("cyclical_commodity_fx", 0.0))
    )
