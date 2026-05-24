"""Factor estimators: news-derived components shift z in expected direction.

핵심 Option Z 의 검증 — NewsReport 의 *quantitative scalar* 가 *factor z*
에 *유의미하게* 기여하는지.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import pytest

from tradingagents.skills.research import factor_estimators as fe
from tradingagents.skills.research.factor_estimators import (
    compute_growth_surprise,
    compute_real_rate,
    compute_term_premium,
)


def _base_stage1():
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
def test_growth_release_surprise_lifts_z(_pe, _krw):
    """surprise_index_30d 가 +2 (강한 surprise) → F1 z 상승."""
    s1 = _base_stage1()
    z_before = compute_growth_surprise(s1).z_score

    # mutate release_surprise.surprise_index_30d only
    s1.news_report.release_surprise.surprise_index_30d = 2.0
    z_after = compute_growth_surprise(s1).z_score

    assert z_after > z_before
    assert z_after - z_before > 0.1  # nontrivial contribution


@patch.object(fe, "fetch_krw_usd_level", return_value=1250.0)
@patch.object(fe, "fetch_sp_trailing_pe", return_value=18.0)
def test_real_rate_fed_voting_dovish_lowers_z(_pe, _krw):
    """fed_voting_balance = -1 (dovish) → F3 z 감소."""
    s1 = _base_stage1()
    z_before = compute_real_rate(s1).z_score

    s1.news_report.cb_speakers.fed_voting_balance = -1.0
    z_after = compute_real_rate(s1).z_score

    assert z_after < z_before
    # baseline (0, 0.5) → voting -1 = z -2 → 0.35 weight capped at 0.40 → contribution
    assert z_before - z_after > 0.5


@patch.object(fe, "fetch_krw_usd_level", return_value=1250.0)
@patch.object(fe, "fetch_sp_trailing_pe", return_value=18.0)
def test_term_premium_fed_tone_hawkish_lifts_z(_pe, _krw):
    """fed_tone_balance = +1 (hawkish) → F4 z 상승 (term premium ↑)."""
    s1 = _base_stage1()
    z_before = compute_term_premium(s1).z_score

    s1.news_report.cb_speakers.fed_tone_balance = 1.0
    z_after = compute_term_premium(s1).z_score

    assert z_after > z_before
    assert z_after - z_before > 0.3


@patch.object(fe, "fetch_krw_usd_level", return_value=1250.0)
@patch.object(fe, "fetch_sp_trailing_pe", return_value=18.0)
def test_growth_hawkish_bias_lifts_z(_pe, _krw):
    """bias_30d='hawkish_surprise' (strong macro releases) → F1 z 상승."""
    s1 = _base_stage1()
    z_before = compute_growth_surprise(s1).z_score

    s1.news_report.release_surprise.bias_30d = "hawkish_surprise"
    z_after = compute_growth_surprise(s1).z_score

    assert z_after > z_before
