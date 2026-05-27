"""Factor estimators: news_report (or its individual tiers) None → graceful fallback.

Verify Option Z 의 *degraded but functional* 약속:
- news_report = None → quant-only components 만 사용, confidence 감소.
- 개별 tier (global_overnight / release_surprise / news_sentiment / cb_speakers)
  None → 해당 tier 의 components skip, 나머지 사용.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import pytest

from tradingagents.skills.research import factor_estimators as fe
from tradingagents.skills.research.factor_estimators import (
    compute_all_factors,
    compute_growth_surprise,
    compute_inflation_surprise,
    compute_real_rate,
)


def _full_stage1():
    macro_growth = SimpleNamespace(gdp_nowcast=2.0, cfnai=0.0, nfci=0.0)
    macro_employment = SimpleNamespace(sahm_trigger=False)
    macro_yc = SimpleNamespace(slope_2_10y_bps=80.0, slope_5_30y_bps=120.0)
    macro_cpi = SimpleNamespace(yoy_pct=2.5, three_month_annualized_pct=2.5, core_pce_yoy=2.0)
    macro_infexp = SimpleNamespace(five_y_five_y_pct=2.3, michigan_1y_pct=3.0)
    macro_real = SimpleNamespace(ten_y_pct=0.5)
    macro_fedpath = SimpleNamespace(implied_change_6m_bps=0.0)
    macro_kr = SimpleNamespace(bok_us_rate_diff_bps=-100.0, exports_yoy_pct=5.0)
    macro_ff = SimpleNamespace(net_flow_z=0.0)
    macro_report = SimpleNamespace(
        growth=macro_growth, employment=macro_employment, yield_curve=macro_yc,
        cpi=macro_cpi, inflation_exp=macro_infexp, real_yields=macro_real,
        fed_path=macro_fedpath, kr_macro=macro_kr, foreign_flow=macro_ff,
    )

    risk_vix = SimpleNamespace(current_value=20.0, z_score=0.0, term_ratio=1.0)
    risk_move = SimpleNamespace(current_value=90.0)
    risk_rv = SimpleNamespace(sixty_d=0.012)
    risk_skew = SimpleNamespace(change_1m=0.0)
    risk_hy = SimpleNamespace(current_bps=400.0, momentum_z=0.0)
    risk_quality = SimpleNamespace(quality_spread_bps=90.0)
    risk_funding = SimpleNamespace(spread_bps=10.0)
    risk_corr = SimpleNamespace(correlation_120d=-0.2)
    risk_report = SimpleNamespace(
        vix=risk_vix, move=risk_move, realized_vol=risk_rv, skew=risk_skew,
        credit_spread_us_hy=risk_hy, credit_quality=risk_quality,
        funding_stress=risk_funding, equity_bond_corr=risk_corr,
    )

    technical_report = SimpleNamespace(
        sector_dispersion=1.0, breadth=0.55, kospi_pbr=1.0,
    )

    krw = SimpleNamespace(change_pct=0.0)
    overnight = SimpleNamespace(krw=krw, risk_regime_overnight="mixed")
    release = SimpleNamespace(
        surprise_index_30d=0.0, bias_30d="balanced", high_importance_today=2,
    )
    sentiment = SimpleNamespace(
        avg_sentiment={"macro": 0.0, "corporate": 0.0, "geopolitical": 0.0},
        count_change_vs_7d={"corporate": 0.0, "geopolitical": 0.0},
        sentiment_dispersion=0.3,
        rising_category=None,
    )
    cb = SimpleNamespace(
        fed_voting_balance=0.0, fed_tone_balance=0.0, bok_tone_balance=0.0,
    )
    news_report = SimpleNamespace(
        global_overnight=overnight, release_surprise=release,
        news_sentiment=sentiment, cb_speakers=cb,
    )
    return SimpleNamespace(
        macro_report=macro_report, risk_report=risk_report,
        technical_report=technical_report, news_report=news_report,
    )


@patch.object(fe, "fetch_krw_usd_level", return_value=1250.0)
@patch.object(fe, "fetch_sp_trailing_pe", return_value=18.0)
def test_factor_news_report_none_falls_back(_pe, _krw):
    """news_report=None → 모든 news components skip, factor 가 quant 만으로 계산."""
    s1 = _full_stage1()
    s1_with = s1
    s1_without = SimpleNamespace(
        macro_report=s1.macro_report,
        risk_report=s1.risk_report,
        technical_report=s1.technical_report,
        news_report=None,
    )

    g_with = compute_growth_surprise(s1_with)
    g_without = compute_growth_surprise(s1_without)

    # 둘 다 z=0 (baseline), 그러나 confidence 가 감소.
    assert g_with.z_score == pytest.approx(0.0, abs=0.05)
    assert g_without.z_score == pytest.approx(0.0, abs=0.1)
    assert g_without.confidence < g_with.confidence
    # No news components present
    for name in ("release_surprise", "hawkish_bias", "macro_sent",
                 "risk_regime_overnight"):
        assert name not in g_without.components


@patch.object(fe, "fetch_krw_usd_level", return_value=1250.0)
@patch.object(fe, "fetch_sp_trailing_pe", return_value=18.0)
def test_factor_news_tier_partial_missing(_pe, _krw):
    """global_overnight=None → risk_regime_overnight skip but release_surprise 등 사용."""
    s1 = _full_stage1()
    s1.news_report = SimpleNamespace(
        global_overnight=None,
        release_surprise=s1.news_report.release_surprise,
        news_sentiment=s1.news_report.news_sentiment,
        cb_speakers=s1.news_report.cb_speakers,
    )

    g = compute_growth_surprise(s1)

    assert "release_surprise" in g.components       # tier-2 still works
    assert "risk_regime_overnight" not in g.components  # tier-1 lost


@patch.object(fe, "fetch_krw_usd_level", return_value=1250.0)
@patch.object(fe, "fetch_sp_trailing_pe", return_value=18.0)
def test_factor_all_news_tiers_missing(_pe, _krw):
    """모든 news tier None → quant-only."""
    s1 = _full_stage1()
    s1.news_report = SimpleNamespace(
        global_overnight=None, release_surprise=None,
        news_sentiment=None, cb_speakers=None,
    )

    g = compute_growth_surprise(s1)
    infl = compute_inflation_surprise(s1)
    rr = compute_real_rate(s1)

    # No news components in any.
    for name in ("release_surprise", "hawkish_bias", "macro_sent",
                 "risk_regime_overnight"):
        assert name not in g.components
    for name in ("release_hawkish", "macro_sent"):
        assert name not in infl.components
    assert "fed_voting_balance" not in rr.components

    # All factors still produce a z (z ≈ 0 since values are baseline).
    # 다소 의 numerical drift 가능 (sahm signal 0.5, curve 등이 capped renorm 후 weight 변동).
    assert g.z_score == pytest.approx(0.0, abs=0.2)
    assert infl.z_score == pytest.approx(0.0, abs=0.2)
    assert rr.z_score == pytest.approx(0.0, abs=0.2)


@patch.object(fe, "fetch_krw_usd_level", return_value=1250.0)
@patch.object(fe, "fetch_sp_trailing_pe", return_value=18.0)
def test_compute_all_factors_returns_9(_pe, _krw):
    """2026-05-27 — F10 추가. fixture 에 systemic_liquidity components 없으면
    9 keys 만, 있으면 10. base 9 keys 항상 존재."""
    s1 = _full_stage1()
    fs = compute_all_factors(s1)
    d = fs.to_dict()
    assert len(d) >= 9
    base_keys = {
        "F1_growth", "F2_inflation", "F3_real_rate", "F4_term_premium",
        "F5_credit_cycle", "F6_krw_regime", "F7_equity_vol_regime",
        "F8_valuation", "F9_liquidity_regime",
    }
    assert base_keys.issubset(set(d.keys()))
