from tradingagents.default_config import DEFAULT_CONFIG


def test_db_gaps_keys_present():
    required = [
        "preset_dir", "prompt_dir", "universe_path",
        "artifacts_dir", "default_preset",
        "subagent_model_policy",
        "etf_price_cache_path", "macro_cache_dir",
        "publication_lag_days",
        "langsmith_enabled", "langsmith_project",
    ]
    for key in required:
        assert key in DEFAULT_CONFIG, f"missing key: {key}"


def test_subagent_model_policy_has_critical_skills():
    policy = DEFAULT_CONFIG["subagent_model_policy"]
    assert policy["classify_regime"] == "deep"
    assert policy["pick_optimization_method"] == "deep"
    assert policy["classify_event_impact"] == "quick"


def test_publication_lag_days_has_critical_series():
    lag = DEFAULT_CONFIG["publication_lag_days"]
    assert lag["us_cpi"] == 15  # CPI ~mid-month next month
    assert lag["kr_base_rate"] == 0  # MPC same-day
    assert lag["us_10y"] == 1  # daily series, T-1 default


def test_live_rebalance_dials_default_to_bl():
    """LIVE default is the Black-Litterman allocator path with calibrated dials.

    The old quadrant+tilt (project_to_band) path is retained as a reversible
    fallback reachable via use_bl=False; only the live config flips use_bl=True.
    """
    dials = DEFAULT_CONFIG["rebalance"]
    assert dials["use_bl"] is True
    assert dials["bl_turnover_cap"] == 0.50  # calibrated (was 0.35)
    assert dials["bl_delta"] == 2.5
    assert dials["bl_base_spread"] == 0.04
