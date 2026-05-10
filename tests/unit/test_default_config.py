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
