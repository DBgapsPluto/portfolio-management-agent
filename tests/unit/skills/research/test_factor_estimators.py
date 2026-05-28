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


def test_f4_uses_acm_term_premium():
    """ACM TP component contributes to F4."""
    from tradingagents.skills.research.factor_estimators import compute_term_premium

    class _Obj:
        def __init__(self, **d): self.__dict__.update(d)

    state = _Obj(
        macro_report=_Obj(
            yield_curve=_Obj(
                spread_10y_2y_bps=80.0,
                spread_30y_5y_bps=80.0,
                acm_term_premium_10y_pct=2.0,  # +1.5σ from baseline (mean=0.5, sd=1.0)
                staleness_days=0,
            ),
        ),
        news_report=None,
    )
    score = compute_term_premium(state, mode="historical")
    # ACM z=+1.5, renormalized weight among 3 present components → z_score > 0.2
    assert score.z_score > 0.2  # ACM +1.5σ drives positive F4


def test_f5_uses_gz_ebp_and_kr_corp_spread():
    """GZ EBP and KR corp spread contribute to F5."""
    from tradingagents.skills.research.factor_estimators import compute_credit_cycle

    class _Obj:
        def __init__(self, **d): self.__dict__.update(d)

    state = _Obj(
        macro_report=None,
        risk_report=_Obj(
            excess_bond_premium=_Obj(ebp=1.0, staleness_days=0),       # +2σ
            kr_corp_spread=_Obj(spread_bps=140.0, staleness_days=0),    # +2σ
            credit_spread_us_hy=_Obj(current_bps=400.0, momentum_zscore=0.0, staleness_days=0),
            credit_quality=_Obj(quality_spread_bps=90.0, staleness_days=0),
            funding_stress=_Obj(spread_bps=10.0, staleness_days=0),
        ),
        news_report=None,
    )
    score = compute_credit_cycle(state, mode="historical")
    # gz_ebp z=+2.0, kr_corp z=+2.0; renormalized among 6 present components → z > 0.25
    assert score.z_score > 0.25  # gz_ebp + kr_corp_spread drive credit stress signal


# === Tier 0 F6/F7/F8 reform + F9 rename tests (Tasks 5.6–5.9) ===

def test_f6_no_longer_uses_krw_level():
    """Tier 0 F6 reform: krw_level removed."""
    from tradingagents.skills.research.factor_estimators import compute_krw_regime
    class _Obj:
        def __init__(self, **d): self.__dict__.update(d)
    state = _Obj(
        macro_report=_Obj(
            fx=_Obj(krw_change_6m_pct=10.0, krw_reer=None, staleness_days=0),  # +2σ
            kr_divergence=_Obj(us_kr_rate_gap_bps=0.0, staleness_days=0),
            foreign_flow=_Obj(net_20d_normalized=0.0, staleness_days=0),
            kr_export=_Obj(yoy_pct=5.0, staleness_days=0),
        ),
        news_report=None,
    )
    score = compute_krw_regime(state, mode="historical")
    assert score.z_score > 0.3  # 6m %change shock → weaker KRW signal


def test_f7_uses_gpr_index():
    """F7 uses GPR Index (replaces geopolitical_surge)."""
    from tradingagents.skills.research.factor_estimators import compute_equity_vol_regime
    class _Obj:
        def __init__(self, **d): self.__dict__.update(d)
    state = _Obj(
        macro_report=_Obj(
            tail_risk=_Obj(move=100.0, staleness_days=0),
            geopolitical_risk=_Obj(gpr_monthly=120.0, gpr_zscore_60m=2.0, staleness_days=0),
        ),
        risk_report=_Obj(
            vix=_Obj(current_value=20.0, zscore_30d=0.0, staleness_days=0),
            vix_term=_Obj(ratio=1.0, staleness_days=0),
            real_vol=_Obj(realized_vol_60d=0.15, staleness_days=0),
            skew=_Obj(change_1m_z=0.0, staleness_days=0),
        ),
        news_report=None,
    )
    score = compute_equity_vol_regime(state, mode="historical")
    assert score.z_score > 0.2  # GPR +2σ should lift F7


def test_f8_uses_us_cape_and_kospi():
    """F8 uses CAPE + KOSPI PER + Div Yield activated."""
    from unittest.mock import patch
    from tradingagents.skills.research.factor_estimators import compute_valuation
    class _Obj:
        def __init__(self, **d): self.__dict__.update(d)
    state = _Obj(
        macro_report=_Obj(
            us_equity_valuation=_Obj(cape=36.0, staleness_days=0),  # +2σ from (20, 8)
            kr_valuation=_Obj(kospi_pbr=1.0, kospi_per=13.0, kospi_div_yield=2.0, staleness_days=0),
        ),
        risk_report=_Obj(
            real_yields=_Obj(tips_10y=2.0, staleness_days=0),
        ),
        news_report=None,
    )
    with patch("tradingagents.skills.research.factor_estimators.fetch_sp_trailing_pe",
               return_value=25.0):
        score = compute_valuation(state, mode="historical")
    assert score.z_score > 0.2  # CAPE +2σ × 0.20 weight; other components partially offset


def test_f9_renamed_to_market_dispersion():
    """compute_market_dispersion function exists (was compute_liquidity_regime)."""
    from tradingagents.skills.research import factor_estimators
    assert hasattr(factor_estimators, "compute_market_dispersion")
    assert not hasattr(factor_estimators, "compute_liquidity_regime")


# === Task 5.13: compute_all_factors 12-factor integration tests ===

def test_compute_all_factors_12_factor_returns():
    """compute_all_factors returns FactorScores with up to 12 factors."""
    from tradingagents.skills.research.factor_estimators import compute_all_factors

    class _Obj:
        def __init__(self, **d): self.__dict__.update(d)

    # Minimal mock stage1 — most snapshots None → confidence 0 → factors may be None
    state = _Obj(macro_report=None, risk_report=None, news_report=None)
    fs = compute_all_factors(state, mode="historical")
    d = fs.to_dict()
    # At minimum F1-F9 always present (their compute funcs return FactorScore not None)
    assert "F1_growth" in d
    assert "F9_market_dispersion" in d
    # F10/F11/F12 may be None (Optional) → not in dict when confidence=0
    # (all components missing for minimal state)


def test_compute_all_factors_f11_f12_present_when_data_available():
    """F11 and F12 are wired: with real data they produce FactorScore."""
    from tradingagents.skills.research.factor_estimators import (
        compute_all_factors, compute_earnings_revision, compute_china_credit_impulse_factor,
    )

    class _Obj:
        def __init__(self, **d): self.__dict__.update(d)

    # State with F11 and F12 data present
    state = _Obj(
        macro_report=_Obj(
            earnings_revision=_Obj(
                sp500_net_revision=0.1,
                kospi200_net_revision=0.05,
                staleness_days=0,
            ),
            china_credit_impulse=_Obj(
                credit_impulse=1.5,
                credit_yoy_pct=8.0,
                staleness_days=0,
            ),
            china_leading=None,
        ),
        risk_report=None,
        news_report=None,
    )
    fs = compute_all_factors(state, mode="historical")
    d = fs.to_dict()
    # F11: sp500_net_revision=0.1 → z=(0.1-0.0)/0.3 ≈ +0.33 → F11 present
    assert "F11_earnings_revision" in d
    # F12: credit_impulse=1.5 → z=(1.5-0.0)/2.0=0.75 → F12 present
    assert "F12_china_credit_impulse" in d


def test_safely_returns_none_on_exception():
    """_safely catches exceptions and returns None."""
    from tradingagents.skills.research.factor_estimators import _safely

    def _bad_fn(stage1, mode):
        raise ValueError("oops")

    result = _safely(_bad_fn, None, "production")
    assert result is None


def test_safely_returns_none_on_zero_confidence():
    """_safely returns None when all components missing (confidence=0)."""
    from tradingagents.skills.research.factor_estimators import _safely, compute_earnings_revision

    class _Obj:
        def __init__(self, **d): self.__dict__.update(d)

    # No earnings_revision data → confidence=0
    state = _Obj(macro_report=None, risk_report=None, news_report=None)
    result = _safely(compute_earnings_revision, state, "historical")
    assert result is None
