"""Verifies that all 34 skills are registered.

Note: registry state is process-global. Other tests may register additional
skills or clear the registry, so we re-register all skills before checking.
"""


def test_all_skills_registered():
    from tradingagents.skills.registry import list_skills, _reregister_all_skills

    # Re-register all skills in case other tests cleared the registry
    _reregister_all_skills()

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
        # Portfolio (7)
        "select_etf_candidates", "fetch_returns_matrix",
        "optimize_hrp", "optimize_risk_parity", "optimize_min_variance", "optimize_black_litterman",
        "pick_optimization_method",
        # Mandate (4)
        "validate_universe", "validate_concentration",
        "validate_turnover_feasibility", "validate_correlation_concentration",
    }
    missing = expected - skills
    assert not missing, f"Missing skills: {missing}"
