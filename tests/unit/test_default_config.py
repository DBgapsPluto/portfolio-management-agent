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


def test_stage2_llm_overlay_defaults_to_low_impact_live():
    assert DEFAULT_CONFIG["stage2_llm_overlay_mode"] == "low_impact"
    assert DEFAULT_CONFIG["stage2_llm_max_mix"] == 0.20
    assert DEFAULT_CONFIG["stage2_llm_band"] == 0.03
    assert DEFAULT_CONFIG["stage3_llm_overlay_mode"] == "shadow"
    assert DEFAULT_CONFIG["allocation_contract_enabled"] is True
    assert DEFAULT_CONFIG["stage3_llm_candidate_boost_cap"] == 0.08
    assert DEFAULT_CONFIG["stage3_llm_longlist_max_per_bucket"] == 8
    assert "stage3_cash_spillover_enabled" not in DEFAULT_CONFIG
    assert "stage3_scenario_boost_enabled" not in DEFAULT_CONFIG
    assert DEFAULT_CONFIG["contract_optimizer_method"] == "hrp"
    assert DEFAULT_CONFIG["cov_factor_proxy_enabled"] is True
    assert DEFAULT_CONFIG["stage2_regime_modifier_pp"] == 0.02
    assert DEFAULT_CONFIG["stage2_scenario_real_cap_goldilocks_pc"] == 0.14
