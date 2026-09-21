from tradingagents.default_config import DEFAULT_CONFIG


def test_db_gaps_keys_present():
    required = [
        "preset_dir", "universe_path", "artifacts_dir",
        "etf_price_cache_path", "publication_lag_days",
    ]
    for key in required:
        assert key in DEFAULT_CONFIG, f"missing key: {key}"


def test_publication_lag_days_has_critical_series():
    lag = DEFAULT_CONFIG["publication_lag_days"]
    assert lag["us_cpi"] == 15  # CPI ~mid-month next month
    assert lag["kr_base_rate"] == 0  # MPC same-day
    assert lag["us_10y"] == 1  # daily series, T-1 default


def test_cluster_full_universe_dial_default_off():
    """F5/WP-D: full-universe clustering ships behind a dial that defaults OFF.

    OFF = production top-tier pool + average linkage, byte-identical. Flipping
    ON (complete-linkage@0.7 full pool — D0-2 decision) is a separate
    user-approved commit after WP-F.
    """
    assert DEFAULT_CONFIG["rebalance"]["cluster_full_universe"] is False


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
