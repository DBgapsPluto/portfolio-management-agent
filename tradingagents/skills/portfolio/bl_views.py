"""
Phase 3b: Black-Litterman views adapter.

Generates absolute BL views (P, Q) and view_confidences from Stage 2 scenario +
regime_confidence using a deterministic rulebook (no LLM).

Used by portfolio_allocator BL branch when method_picker outputs BLACK_LITTERMAN
with params={"_bl_trigger": True}, or when state["force_method"]="black_litterman".
"""
from __future__ import annotations

# 9 scenario × 5 bucket → annualized expected return (decimal).
# scenario keys MUST equal method_picker._SCENARIO_METHOD keys (test enforced).
# cash_mmf ≈ KOFR floor (2.5%). Returns capped at |0.30| (test enforced).
SCENARIO_BUCKET_RULEBOOK: dict[str, dict[str, float]] = {
    "goldilocks":       {"kr_equity": 0.10, "global_equity": 0.12,
                         "fx_commodity": 0.02, "bond": 0.04,  "cash_mmf": 0.025},
    "overheating":      {"kr_equity": 0.06, "global_equity": 0.08,
                         "fx_commodity": 0.10, "bond": 0.02,  "cash_mmf": 0.025},
    "late_cycle":       {"kr_equity": 0.02, "global_equity": 0.04,
                         "fx_commodity": 0.08, "bond": 0.06,  "cash_mmf": 0.025},
    "stagflation":      {"kr_equity": -0.05, "global_equity": -0.03,
                         "fx_commodity": 0.12, "bond": 0.01,  "cash_mmf": 0.025},
    "broad_recession":  {"kr_equity": -0.08, "global_equity": -0.05,
                         "fx_commodity": -0.02, "bond": 0.08, "cash_mmf": 0.025},
    "kr_stress":        {"kr_equity": -0.10, "global_equity": 0.05,
                         "fx_commodity": 0.03, "bond": 0.05,  "cash_mmf": 0.025},
    "global_credit":    {"kr_equity": -0.05, "global_equity": -0.08,
                         "fx_commodity": -0.02, "bond": 0.07, "cash_mmf": 0.025},
    "ai_concentration": {"kr_equity": 0.05, "global_equity": 0.10,
                         "fx_commodity": 0.02, "bond": 0.03,  "cash_mmf": 0.025},
    "kr_boom":          {"kr_equity": 0.13, "global_equity": 0.08,
                         "fx_commodity": 0.02, "bond": 0.03,  "cash_mmf": 0.025},
}

# Idzorek-Walters Ω 가 numerically 안정하려면 view confidence > 0 이어야 함.
BL_VIEW_MIN_CONFIDENCE: float = 0.10


def generate_bl_views(
    *,
    scenario: str | None,
    regime_confidence: float,
    candidates: dict[str, list[str]],
    sub_category_lookup: dict[str, str] | None = None,
    breakdown_out: dict | None = None,
) -> tuple[dict[str, float], list[float]]:
    """
    Generate absolute Black-Litterman views from rulebook.

    Each ticker in bucket B gets SCENARIO_BUCKET_RULEBOOK[scenario][B] as its
    absolute view return. Each view's confidence = max(regime_confidence,
    BL_VIEW_MIN_CONFIDENCE).

    Returns ({}, []) when scenario unknown to rulebook — caller should fall
    back to historical mu.
    """
    if scenario is None or scenario not in SCENARIO_BUCKET_RULEBOOK:
        if breakdown_out is not None:
            breakdown_out["fallback_reason"] = "unknown_scenario"
            breakdown_out["scenario"] = scenario
        return {}, []

    bucket_returns = SCENARIO_BUCKET_RULEBOOK[scenario]
    conf_value = max(regime_confidence, BL_VIEW_MIN_CONFIDENCE)

    absolute_views: dict[str, float] = {}
    view_confidences: list[float] = []
    n_per_bucket: dict[str, int] = {}
    for bucket, tickers in candidates.items():
        if bucket not in bucket_returns:
            continue
        expected_ret = bucket_returns[bucket]
        for ticker in tickers:
            absolute_views[ticker] = expected_ret
            view_confidences.append(conf_value)
        n_per_bucket[bucket] = len(tickers)

    if breakdown_out is not None:
        breakdown_out["scenario"] = scenario
        breakdown_out["regime_confidence_raw"] = regime_confidence
        breakdown_out["confidence_used"] = conf_value
        breakdown_out["n_views_per_bucket"] = n_per_bucket
        breakdown_out["rulebook_returns_used"] = {
            b: bucket_returns[b] for b in n_per_bucket
        }

    return absolute_views, view_confidences
