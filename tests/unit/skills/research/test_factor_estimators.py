"""Tests for Tasks 5.1 + 5.2: FACTORS tuple (12 entries), FactorScores extension,
NEWS_DERIVED_COMPONENTS (geopolitical_surge removed), LIVE_ONLY_QUANT_COMPONENTS.
"""
import pytest
from tradingagents.skills.research.factor_estimators import (
    FACTORS, FactorScore, FactorScores,
    NEWS_DERIVED_COMPONENTS, LIVE_ONLY_QUANT_COMPONENTS,
)


def test_factors_tuple_has_12_entries_with_renamed_f9():
    assert len(FACTORS) == 12
    assert "F9_market_dispersion" in FACTORS
    assert "F9_liquidity_regime" not in FACTORS
    assert "F11_earnings_revision" in FACTORS
    assert "F12_china_credit_impulse" in FACTORS


def test_factor_scores_to_dict_includes_new_factors():
    def _s(name, z=0.0): return FactorScore(name=name, z_score=z)
    fs = FactorScores(
        growth_surprise=_s("F1_growth", 1.0),
        inflation_surprise=_s("F2_inflation"),
        real_rate=_s("F3_real_rate"),
        term_premium=_s("F4_term_premium"),
        credit_cycle=_s("F5_credit_cycle"),
        krw_regime=_s("F6_krw_regime"),
        equity_vol_regime=_s("F7_equity_vol"),
        valuation=_s("F8_valuation"),
        market_dispersion=_s("F9_market_dispersion"),
        systemic_liquidity=_s("F10_systemic_liquidity", 0.5),
        earnings_revision=_s("F11_earnings_revision", 0.3),
        china_credit_impulse=_s("F12_china_credit_impulse", -0.2),
    )
    d = fs.to_dict()
    assert d["F1_growth"] == 1.0
    assert d["F9_market_dispersion"] == 0.0
    assert d["F11_earnings_revision"] == 0.3
    assert d["F12_china_credit_impulse"] == -0.2


def test_factor_scores_to_dict_drops_none_optional():
    """F11 staggered: when None, not in dict."""
    def _s(name, z=0.0): return FactorScore(name=name, z_score=z)
    fs = FactorScores(
        growth_surprise=_s("F1_growth"),
        inflation_surprise=_s("F2_inflation"),
        real_rate=_s("F3_real_rate"),
        term_premium=_s("F4_term_premium"),
        credit_cycle=_s("F5_credit_cycle"),
        krw_regime=_s("F6_krw_regime"),
        equity_vol_regime=_s("F7_equity_vol"),
        valuation=_s("F8_valuation"),
        market_dispersion=_s("F9_market_dispersion"),
        systemic_liquidity=None,
        earnings_revision=None,
        china_credit_impulse=None,
    )
    d = fs.to_dict()
    assert "F11_earnings_revision" not in d
    assert "F12_china_credit_impulse" not in d
    assert "F10_systemic_liquidity" not in d


def test_geopolitical_surge_removed_from_news_set():
    assert "geopolitical_surge" not in NEWS_DERIVED_COMPONENTS


def test_gdpnow_in_live_only_quant():
    assert "gdpnow" in LIVE_ONLY_QUANT_COMPONENTS


# === Tier 0 F1 reform tests ===

def test_f1_no_longer_uses_nfci_or_curve():
    """Tier 0 F1 reform: nfci/curve removed."""
    from tradingagents.skills.research.factor_estimators import compute_growth_surprise
    from types import SimpleNamespace

    state = SimpleNamespace(
        macro_report=SimpleNamespace(
            financial_conditions=SimpleNamespace(
                nfci=2.0, cfnai=0.0, cfnai_3m_avg=0.0,  # strong nfci
                staleness_days=0,
            ),
            gdp_nowcast=SimpleNamespace(nowcast_pct=2.0, staleness_days=0),
            employment=SimpleNamespace(sahm_rule_triggered=False, staleness_days=0),
            yield_curve=SimpleNamespace(spread_10y_2y_bps=80.0, staleness_days=0),  # neutral curve
            us_indpro_yoy_pct=2.0,
            us_real_pce_yoy_pct=2.5,
        ),
        news_report=None,
    )
    score = compute_growth_surprise(state, mode="historical")
    # F1 z should be ~0 (all components at baseline). nfci/curve should NOT contribute.
    assert abs(score.z_score) < 0.5


def test_f1_responds_to_indpro_real_pce():
    """Strong INDPRO YoY shock → F1 positive."""
    from tradingagents.skills.research.factor_estimators import compute_growth_surprise
    from types import SimpleNamespace

    state = SimpleNamespace(
        macro_report=SimpleNamespace(
            financial_conditions=SimpleNamespace(cfnai=0.0, cfnai_3m_avg=0.0, staleness_days=0),
            gdp_nowcast=SimpleNamespace(nowcast_pct=2.0, staleness_days=0),
            employment=SimpleNamespace(sahm_rule_triggered=False, staleness_days=0),
            us_indpro_yoy_pct=8.0,  # +2σ above baseline (mean=2, sd=3)
            us_real_pce_yoy_pct=2.5,
        ),
        news_report=None,
    )
    score = compute_growth_surprise(state, mode="historical")
    assert score.z_score > 0.3  # positive growth signal
