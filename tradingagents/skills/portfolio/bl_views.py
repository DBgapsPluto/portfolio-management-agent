"""
Phase 3b: Black-Litterman views adapter.

Generates absolute BL views (P, Q) and view_confidences from Stage 2 scenario +
regime_confidence using a deterministic rulebook (no LLM).

Used by portfolio_allocator BL branch when method_picker outputs BLACK_LITTERMAN
with params={"_bl_trigger": True}, or when state["force_method"]="black_litterman".
"""
from __future__ import annotations

# 9 scenario × 8 bucket → annualized expected return (decimal).
# scenario keys MUST equal method_picker._SCENARIO_METHOD keys (test enforced).
# cash_mmf ≈ KOFR floor (2.5%). Returns capped at |0.30| (test enforced).
# fx_commodity → precious_metals + cyclical_commodity_fx;
# bond → kr_bond + credit + global_duration (Tier 1 INITIAL_BETA 부호 파생).
SCENARIO_BUCKET_RULEBOOK: dict[str, dict[str, float]] = {
    "goldilocks":       {"kr_equity": 0.10, "global_equity": 0.12,
                         "precious_metals": 0.02, "cyclical_commodity_fx": 0.03,
                         "kr_bond": 0.02, "credit": 0.05, "global_duration": 0.03,
                         "cash_mmf": 0.025},
    "overheating":      {"kr_equity": 0.06, "global_equity": 0.08,
                         "precious_metals": 0.06, "cyclical_commodity_fx": 0.12,
                         "kr_bond": 0.01, "credit": 0.03, "global_duration": -0.01,
                         "cash_mmf": 0.025},
    "late_cycle":       {"kr_equity": 0.02, "global_equity": 0.04,
                         "precious_metals": 0.07, "cyclical_commodity_fx": 0.06,
                         "kr_bond": 0.06, "credit": 0.00, "global_duration": 0.07,
                         "cash_mmf": 0.025},
    "stagflation":      {"kr_equity": -0.05, "global_equity": -0.03,
                         "precious_metals": 0.13, "cyclical_commodity_fx": 0.10,
                         "kr_bond": 0.00, "credit": -0.03, "global_duration": 0.00,
                         "cash_mmf": 0.025},
    "broad_recession":  {"kr_equity": -0.08, "global_equity": -0.05,
                         "precious_metals": 0.04, "cyclical_commodity_fx": -0.06,
                         "kr_bond": 0.07, "credit": -0.04, "global_duration": 0.10,
                         "cash_mmf": 0.025},
    "kr_stress":        {"kr_equity": -0.10, "global_equity": 0.05,
                         "precious_metals": 0.06, "cyclical_commodity_fx": 0.04,
                         "kr_bond": 0.03, "credit": 0.01, "global_duration": 0.07,
                         "cash_mmf": 0.025},
    "global_credit":    {"kr_equity": -0.05, "global_equity": -0.08,
                         "precious_metals": 0.02, "cyclical_commodity_fx": -0.05,
                         "kr_bond": 0.05, "credit": -0.08, "global_duration": 0.10,
                         "cash_mmf": 0.025},
    "ai_concentration": {"kr_equity": 0.05, "global_equity": 0.10,
                         "precious_metals": 0.02, "cyclical_commodity_fx": 0.02,
                         "kr_bond": 0.03, "credit": 0.04, "global_duration": 0.02,
                         "cash_mmf": 0.025},
    "kr_boom":          {"kr_equity": 0.13, "global_equity": 0.08,
                         "precious_metals": 0.01, "cyclical_commodity_fx": 0.04,
                         "kr_bond": 0.00, "credit": 0.04, "global_duration": 0.01,
                         "cash_mmf": 0.025},
}

# Idzorek-Walters Ω 가 numerically 안정하려면 view confidence > 0 이어야 함.
BL_VIEW_MIN_CONFIDENCE: float = 0.10

# Phase 4b — BL tilt dial

# Idzorek-Walters Ω 안정성 boundary (post-multiplier clipping)
BL_VIEW_CONF_MIN_AFTER_MULTI: float = 0.05
BL_VIEW_CONF_MAX_AFTER_MULTI: float = 1.0

# Unknown scenario fallback (Phase 3b 동작 보존)
BL_TAU_DEFAULT: float = 0.05
BL_VIEW_CONF_MULTI_DEFAULT: float = 1.0

# 9 scenario × (tau, view_conf_multi)
# tau ∈ [0.025, 0.10], view_conf_multi ∈ [0.5, 1.5]
SCENARIO_BL_TILT: dict[str, dict[str, float]] = {
    "goldilocks":       {"tau": 0.10, "view_conf_multi": 1.3},
    "kr_boom":          {"tau": 0.10, "view_conf_multi": 1.3},
    "overheating":      {"tau": 0.07, "view_conf_multi": 1.0},
    "ai_concentration": {"tau": 0.07, "view_conf_multi": 1.0},
    "late_cycle":       {"tau": 0.05, "view_conf_multi": 0.8},
    "stagflation":      {"tau": 0.05, "view_conf_multi": 0.7},
    "broad_recession":  {"tau": 0.025, "view_conf_multi": 0.5},
    "kr_stress":        {"tau": 0.025, "view_conf_multi": 0.5},
    "global_credit":    {"tau": 0.025, "view_conf_multi": 0.5},
}


def generate_bl_views(
    *,
    scenario: str | None,
    regime_confidence: float,
    candidates: dict[str, list[str]],
    sub_category_lookup: dict[str, str] | None = None,
    bucket_returns_override: dict[str, float] | None = None,
    breakdown_out: dict | None = None,
) -> tuple[dict[str, float], list[float], dict[str, float | bool]]:
    """
    Generate absolute BL views + post-multiplier confidences + tilt params.

    Returns:
        absolute_views: {ticker: expected_return}
        view_confidences: list[float] — post-multiplier, clipped [0.05, 1.0]
        tilt_params: {"tau", "view_conf_multi", "view_conf_multi_applied"}
    """
    default_tilt: dict[str, float | bool] = {
        "tau": BL_TAU_DEFAULT,
        "view_conf_multi": BL_VIEW_CONF_MULTI_DEFAULT,
        "view_conf_multi_applied": False,
    }

    if bucket_returns_override:
        bucket_returns = dict(bucket_returns_override)
        if breakdown_out is not None:
            breakdown_out["returns_source"] = "allocation_contract"
            breakdown_out["scenario"] = scenario
    elif scenario is not None and scenario in SCENARIO_BUCKET_RULEBOOK:
        bucket_returns = SCENARIO_BUCKET_RULEBOOK[scenario]
        if breakdown_out is not None:
            breakdown_out["returns_source"] = "scenario_rulebook"
    else:
        if breakdown_out is not None:
            breakdown_out["fallback_reason"] = "unknown_scenario"
            breakdown_out["scenario"] = scenario
            breakdown_out["tilt_params"] = default_tilt
        return {}, [], default_tilt
    conf_value = max(regime_confidence, BL_VIEW_MIN_CONFIDENCE)

    tilt_raw = SCENARIO_BL_TILT.get(scenario)
    if tilt_raw is None:
        tilt_params: dict[str, float | bool] = dict(default_tilt)
    else:
        tilt_params = {
            "tau": tilt_raw["tau"],
            "view_conf_multi": tilt_raw["view_conf_multi"],
            "view_conf_multi_applied": True,
        }
    multi = float(tilt_params["view_conf_multi"])

    absolute_views: dict[str, float] = {}
    view_confidences: list[float] = []
    n_per_bucket: dict[str, int] = {}
    for bucket, tickers in candidates.items():
        if bucket not in bucket_returns:
            continue
        expected_ret = bucket_returns[bucket]
        for ticker in tickers:
            absolute_views[ticker] = expected_ret
            post = conf_value * multi
            clipped = min(
                BL_VIEW_CONF_MAX_AFTER_MULTI,
                max(BL_VIEW_CONF_MIN_AFTER_MULTI, post),
            )
            view_confidences.append(clipped)
        n_per_bucket[bucket] = len(tickers)

    if breakdown_out is not None:
        breakdown_out["scenario"] = scenario
        breakdown_out["regime_confidence_raw"] = regime_confidence
        breakdown_out["confidence_used"] = conf_value
        breakdown_out["n_views_per_bucket"] = n_per_bucket
        breakdown_out["rulebook_returns_used"] = {
            b: bucket_returns[b] for b in n_per_bucket
        }
        breakdown_out["tilt_params"] = tilt_params

    return absolute_views, view_confidences, tilt_params
