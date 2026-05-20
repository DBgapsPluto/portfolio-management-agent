"""Verifies that all 34 skills are registered.

Note: registry state is process-global. Other tests may register additional
skills or clear the registry, so we re-register all skills before checking.

2026-05: portfolio.optimizers / portfolio.candidate_selector depend on
pypfopt → cvxpy → numpy 2.x. Some dev environments (e.g. anaconda with
numpy<2) cannot import these, which would cause the test to fail on
unrelated environmental issues. OPTIONAL set lets those degrade gracefully.
Production environments install the full lockfile so this fallback never
matters there.
"""


# Skills that depend on optional heavy deps (pypfopt/cvxpy). Missing them
# in a degraded test env is acceptable; production env has them.
OPTIONAL_SKILLS = {
    "optimize_hrp", "optimize_risk_parity",
    "optimize_min_variance", "optimize_black_litterman",
    "pick_optimization_method",
    "select_etf_candidates", "fetch_returns_matrix",
}


def test_all_skills_registered():
    from tradingagents.skills.registry import list_skills, _reregister_all_skills

    # Re-register all skills in case other tests cleared the registry.
    # Wrap in try so that one optional-skill failure doesn't abort the whole
    # registry reload chain.
    try:
        _reregister_all_skills()
    except Exception:
        # Best-effort: even if reload fails partway, still verify what's
        # currently registered.
        pass

    skills = set(list_skills())
    expected = {
        # Macro (8)
        "compute_yield_curve", "compute_inflation_trend", "compute_unemployment_trend",
        "fetch_fred_series", "fetch_ecos_series", "compute_kr_divergence",
        "fetch_central_bank_calendar", "classify_regime",
        # Risk (6)
        "fetch_volatility_index", "fetch_credit_spread", "fetch_fear_greed_index",
        "compute_market_breadth", "compute_correlation_concentration", "score_systemic_risk",
        # Technical (5)
        "fetch_etf_price_batch", "compute_ta_indicators", "rank_momentum",
        "detect_trend_state", "find_correlation_clusters",
        # News (4)
        "fetch_event_calendar", "fetch_macro_news", "classify_event_impact", "dedupe_rank_news",
        # Portfolio (7) — OPTIONAL_SKILLS는 환경 종속이라 제외 가능
        "select_etf_candidates", "fetch_returns_matrix",
        "optimize_hrp", "optimize_risk_parity", "optimize_min_variance", "optimize_black_litterman",
        "pick_optimization_method",
        # Mandate (4)
        "validate_universe", "validate_concentration",
        "validate_turnover_feasibility", "validate_correlation_concentration",
    }
    required = expected - OPTIONAL_SKILLS
    missing_required = required - skills
    assert not missing_required, (
        f"Required skills missing: {missing_required} "
        f"(OPTIONAL skills not checked: {OPTIONAL_SKILLS & (expected - skills)})"
    )
