"""Tier 0 end-to-end integration: build minimal stage1 → 12-factor scores."""
import pytest
from datetime import date
from tradingagents.skills.research.factor_estimators import compute_all_factors


class _Obj:
    """Helper for nested attribute mock objects."""
    def __init__(self, **d):
        self.__dict__.update(d)


@pytest.fixture
def stage1_minimal():
    """Minimal mock stage1 with required snapshots — most Tier 0 Optional fields None."""
    return _Obj(
        macro_report=_Obj(
            financial_conditions=_Obj(
                cfnai=0.0, cfnai_3m_avg=0.0, staleness_days=0,
                nfci=0.0, anfci=0.0,
            ),
            gdp_nowcast=_Obj(nowcast_pct=2.0, staleness_days=0),
            employment=_Obj(sahm_rule_triggered=False, staleness_days=0),
            yield_curve=_Obj(
                spread_10y_2y_bps=80.0, spread_30y_5y_bps=80.0,
                acm_term_premium_10y_pct=None, staleness_days=0,
            ),
            inflation=_Obj(cpi_yoy=2.5, staleness_days=0),
            inflation_expectations=_Obj(breakeven_5y5y=2.3, michigan_1y=3.0, staleness_days=0),
            fed_path=_Obj(path_bps=0.0, staleness_days=0),
            fx=_Obj(
                usd_krw=1300, krw_change_6m_pct=0.0, krw_reer=None, staleness_days=0,
            ),
            kr_divergence=_Obj(us_kr_rate_gap_bps=100.0, staleness_days=0),
            foreign_flow=_Obj(net_20d_normalized=0.0, staleness_days=0),
            kr_export=_Obj(yoy_pct=5.0, staleness_days=0),
            tail_risk=_Obj(move=80.0, staleness_days=0),
            kr_valuation=_Obj(kospi_pbr=1.0, kospi_per=13.0, kospi_div_yield=2.0, staleness_days=0),
            us_indpro_yoy_pct=2.0, us_real_pce_yoy_pct=2.5,
            us_equity_valuation=None,
            geopolitical_risk=None,
            china_credit_impulse=None,
            earnings_revision=None,
            commodity_momentum=None,
            china_leading=_Obj(iron_ore_change_3m_pct=0.0, staleness_days=0),
        ),
        risk_report=_Obj(
            real_yields=_Obj(tips_10y=2.0, staleness_days=0),
            credit_spread_us_hy=_Obj(current_bps=400.0, momentum_zscore=0.0, staleness_days=0),
            credit_quality=_Obj(quality_spread_bps=90.0, staleness_days=0),
            funding_stress=_Obj(spread_bps=10.0, staleness_days=0),
            vix=_Obj(current_value=20.0, zscore_30d=0.0, staleness_days=0),
            vix_term=_Obj(ratio=1.0, staleness_days=0),
            real_vol=_Obj(realized_vol_60d=0.15, vrp_60d=0.0, staleness_days=0),
            skew=_Obj(change_1m_z=0.0, staleness_days=0),
            equity_bond_corr=_Obj(correlation_120d=-0.2, staleness_days=0),
            breadth_kr=_Obj(advancing_pct=0.55, staleness_days=0),
            breadth_us=_Obj(sector_return_dispersion=0.05, staleness_days=0),
            excess_bond_premium=None,
            kr_corp_spread=None,
        ),
        news_report=None,
    )


def test_compute_all_factors_returns_factor_scores(stage1_minimal):
    """End-to-end: 12-factor compute_all_factors works with minimal mocks."""
    fs = compute_all_factors(stage1_minimal, mode="production")
    d = fs.to_dict()
    # F1-F9 always present
    for f in ["F1_growth", "F2_inflation", "F3_real_rate", "F4_term_premium",
              "F5_credit_cycle", "F6_krw_regime", "F7_equity_vol_regime",
              "F8_valuation", "F9_market_dispersion"]:
        assert f in d, f"{f} missing from to_dict output"
    # F10/F11/F12 may be None (Optional) → not in dict
    assert 9 <= len(d) <= 12


def test_historical_mode_drops_news_and_gdpnow(stage1_minimal):
    """Tier 0: historical mode drops gdpnow + news-derived components."""
    fs = compute_all_factors(stage1_minimal, mode="historical")
    f1_keys = set(fs.growth_surprise.component_weights.keys())
    assert "gdpnow" not in f1_keys, "gdpnow should drop in historical mode (LIVE_ONLY)"
    # News-derived components also dropped
    for news_key in ("release_surprise", "hawkish_bias", "macro_sent"):
        assert news_key not in f1_keys


def test_dynamic_baseline_param_threading(stage1_minimal):
    """compute_all_factors accepts as_of_date + use_dynamic_baseline params."""
    fs = compute_all_factors(
        stage1_minimal, mode="historical",
        as_of_date=date(2020, 1, 1),
        use_dynamic_baseline=False,  # default off — backward compat
    )
    assert fs is not None
    # With dynamic_baseline=False, equivalent to existing behavior
