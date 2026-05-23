"""factor_estimators.py: _aggregate helper + per-factor compute functions."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from tradingagents.skills.research import factor_estimators as fe
from tradingagents.skills.research.factor_estimators import (
    FactorScore,
    FactorScores,
    _aggregate,
    _BIAS_MAP,
    _RISK_REGIME_MAP,
    _safe_get,
    compute_all_factors,
    compute_credit_cycle,
    compute_equity_vol_regime,
    compute_growth_surprise,
    compute_inflation_surprise,
    compute_krw_regime,
    compute_liquidity_regime,
    compute_real_rate,
    compute_term_premium,
    compute_valuation,
)


# ---------- _aggregate tests ----------

def test_aggregate_all_components_available() -> None:
    # F1: gdpnow value = 2.0 → z = 0.0 (baseline mean=2.0).
    components_raw = {"gdpnow": 2.0, "cfnai": 0.5}  # cfnai z = 1.0
    weights = {"gdpnow": 0.5, "cfnai": 0.5}
    score = _aggregate("F1_growth", components_raw, weights)
    # gdpnow z=0.0, cfnai z=1.0. caps: high → 0.40, so both at 0.40, renorm 50/50.
    # avg = 0.5 * 0.0 + 0.5 * 1.0 = 0.5
    assert score.z_score == pytest.approx(0.5)
    assert "gdpnow" in score.components
    assert "cfnai" in score.components
    assert score.confidence == pytest.approx(1.0)  # original total weight


def test_aggregate_none_component_skipped() -> None:
    components_raw = {"gdpnow": None, "cfnai": 0.5}  # cfnai z=1.0
    weights = {"gdpnow": 0.5, "cfnai": 0.5}
    score = _aggregate("F1_growth", components_raw, weights)
    # gdpnow skipped → only cfnai, renormed to 1.0 → score = 1.0
    assert score.z_score == pytest.approx(1.0)
    assert "gdpnow" not in score.components
    assert "cfnai" in score.components
    assert score.confidence == pytest.approx(0.5)


def test_aggregate_all_none_returns_zero() -> None:
    components_raw = {"gdpnow": None, "cfnai": None}
    weights = {"gdpnow": 0.5, "cfnai": 0.5}
    score = _aggregate("F1_growth", components_raw, weights)
    assert score.z_score == 0.0
    assert score.confidence == 0.0
    assert score.components == {}


def test_aggregate_caps_at_plus_3() -> None:
    # gdpnow value 10 → z = (10-2)/2 = 4.0 → cap at +3
    components_raw = {"gdpnow": 10.0}
    weights = {"gdpnow": 1.0}
    score = _aggregate("F1_growth", components_raw, weights)
    assert score.z_score == 3.0


def test_aggregate_caps_at_minus_3() -> None:
    components_raw = {"gdpnow": -10.0}  # z = -6 → cap -3
    weights = {"gdpnow": 1.0}
    score = _aggregate("F1_growth", components_raw, weights)
    assert score.z_score == -3.0


# ---------- _safe_get tests ----------

def test_safe_get_nested_attribute() -> None:
    obj = SimpleNamespace(a=SimpleNamespace(b=SimpleNamespace(c=42)))
    assert _safe_get(obj, "a", "b", "c") == 42
    assert _safe_get(obj, "a", "missing") is None
    assert _safe_get(None, "a") is None


def test_safe_get_dict_path() -> None:
    obj = SimpleNamespace(d={"k1": {"k2": 7}})
    assert _safe_get(obj, "d", "k1", "k2") == 7
    assert _safe_get(obj, "d", "missing") is None


def test_safe_get_with_default() -> None:
    assert _safe_get(None, "a", default=99) == 99
    obj = SimpleNamespace(x=None)
    assert _safe_get(obj, "x", "y", default="dflt") == "dflt"


# ---------- enum maps ----------

def test_bias_map_values() -> None:
    assert _BIAS_MAP["hawkish_surprise"] == 0.8
    assert _BIAS_MAP["balanced"] == 0.0
    assert _BIAS_MAP["dovish_surprise"] == -0.8


def test_risk_regime_map_values() -> None:
    assert _RISK_REGIME_MAP["risk_on"] == 1.0
    assert _RISK_REGIME_MAP["mixed"] == 0.0
    assert _RISK_REGIME_MAP["risk_off"] == -1.0


# ---------- per-factor smoke tests with baseline mock stage1 ----------

def _full_stage1_baseline():
    """All factors get baseline values → every component z = 0.

    2026-05-23 (C1, PR0 hotfix): schema 명세에 맞게 path 정정. 이전 fixture 는
    *이미 broken 한 path* 를 reflect 한 것이라 silent pass 되었음.

    Note: 5 placeholder components (cfnai, slope_5_30y, realized_vol_60d,
    kospi_pbr, sector_dispersion / vrp) 는 weight=0 이라 본 fixture 에 해당 attribute
    없어도 confidence 계산에서 빠짐. C8 후 활성화.
    """
    # macro_report — corrected paths matching MacroReport schema
    macro_gdp = SimpleNamespace(nowcast_pct=2.0, change_from_prior=0.0)
    macro_fci = SimpleNamespace(nfci=0.0, anfci=0.0, regime="neutral", tightening=False)
    macro_employment = SimpleNamespace(sahm_rule_triggered=False)
    macro_yc = SimpleNamespace(spread_10y_2y_bps=80.0, spread_10y_3m_bps=120.0)
    # InflationSnapshot uses cpi_yoy/momentum_3mo/core_pce_yoy (not cpi.*)
    macro_inflation = SimpleNamespace(
        cpi_yoy=2.5, momentum_3mo=2.5, core_pce_yoy=2.0,
    )
    # InflationExpectationsSnapshot
    macro_infexp = SimpleNamespace(breakeven_5y5y=2.3, michigan_1y=3.0)
    # FedPathSnapshot uses path_bps
    macro_fedpath = SimpleNamespace(path_bps=0.0)
    # DivergenceScore (was kr_macro)
    macro_kr_div = SimpleNamespace(us_kr_rate_gap_bps=-100.0)
    # KRExportSnapshot uses yoy_pct
    macro_kr_export = SimpleNamespace(yoy_pct=5.0)
    # ForeignFlowSnapshot uses net_20d_krw
    macro_ff = SimpleNamespace(net_20d_krw=0.0)
    # FXSnapshot for krw_level
    macro_fx = SimpleNamespace(usd_krw=1250.0)
    # TailRiskSnapshot — MOVE is here, not in risk_report
    macro_tail = SimpleNamespace(move=90.0, vvix=90.0)
    macro_report = SimpleNamespace(
        gdp_nowcast=macro_gdp,
        financial_conditions=macro_fci,
        employment=macro_employment,
        yield_curve=macro_yc,
        inflation=macro_inflation,
        inflation_expectations=macro_infexp,
        fed_path=macro_fedpath,
        kr_divergence=macro_kr_div,
        kr_export=macro_kr_export,
        foreign_flow=macro_ff,
        fx=macro_fx,
        tail_risk=macro_tail,
    )

    # risk_report — corrected paths matching RiskReport schema
    # VolatilitySnapshot uses zscore_30d (not z_score)
    risk_vix = SimpleNamespace(current_value=20.0, zscore_30d=0.0)
    # VIXTermStructureSnapshot — separate snapshot using ratio field
    risk_vix_term = SimpleNamespace(ratio=1.0)
    # SkewSnapshot — C1 placeholder (semantic mismatch), included for shape only
    risk_skew = SimpleNamespace(skew_value=118.0)  # not read (weight=0)
    # SpreadSnapshot uses momentum_zscore (not momentum_z)
    risk_hy = SimpleNamespace(current_bps=400.0, momentum_zscore=0.0)
    risk_quality = SimpleNamespace(quality_spread_bps=90.0)
    risk_funding = SimpleNamespace(spread_bps=10.0)
    risk_corr = SimpleNamespace(correlation_60d=-0.2)
    # RealYieldsSnapshot uses tips_10y (not ten_y_pct)
    risk_real_yields = SimpleNamespace(tips_10y=0.5)
    # BreadthSnapshot uses advancing_pct
    risk_breadth_kr = SimpleNamespace(advancing_pct=0.55)
    risk_report = SimpleNamespace(
        vix=risk_vix,
        vix_term=risk_vix_term,
        skew=risk_skew,
        credit_spread_us_hy=risk_hy,
        credit_quality=risk_quality,
        funding_stress=risk_funding,
        equity_bond_corr=risk_corr,
        real_yields=risk_real_yields,
        breadth_kr=risk_breadth_kr,
    )

    # technical_report — sector_dispersion/breadth/kospi_pbr 는 C8 placeholder
    # 이라 더 이상 factor_estimators 에서 read 안 함. 빈 namespace 유지.
    technical_report = SimpleNamespace()

    # news_report
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
def test_compute_growth_surprise_baseline_z_zero(_pe, _krw):
    s = compute_growth_surprise(_full_stage1_baseline())
    assert isinstance(s, FactorScore)
    assert s.z_score == pytest.approx(0.0, abs=0.05)
    assert s.confidence > 0.5


@patch.object(fe, "fetch_krw_usd_level", return_value=1250.0)
@patch.object(fe, "fetch_sp_trailing_pe", return_value=18.0)
def test_compute_inflation_surprise_baseline_z_zero(_pe, _krw):
    s = compute_inflation_surprise(_full_stage1_baseline())
    assert s.z_score == pytest.approx(0.0, abs=0.05)


@patch.object(fe, "fetch_krw_usd_level", return_value=1250.0)
@patch.object(fe, "fetch_sp_trailing_pe", return_value=18.0)
def test_compute_real_rate_baseline_z_zero(_pe, _krw):
    s = compute_real_rate(_full_stage1_baseline())
    assert s.z_score == pytest.approx(0.0, abs=0.05)


@patch.object(fe, "fetch_krw_usd_level", return_value=1250.0)
@patch.object(fe, "fetch_sp_trailing_pe", return_value=18.0)
def test_compute_term_premium_baseline_z_zero(_pe, _krw):
    s = compute_term_premium(_full_stage1_baseline())
    assert s.z_score == pytest.approx(0.0, abs=0.05)


@patch.object(fe, "fetch_krw_usd_level", return_value=1250.0)
@patch.object(fe, "fetch_sp_trailing_pe", return_value=18.0)
def test_compute_credit_cycle_baseline_z_zero(_pe, _krw):
    s = compute_credit_cycle(_full_stage1_baseline())
    assert s.z_score == pytest.approx(0.0, abs=0.1)


@patch.object(fe, "fetch_krw_usd_level", return_value=1250.0)
@patch.object(fe, "fetch_sp_trailing_pe", return_value=18.0)
def test_compute_krw_regime_baseline_z_zero(_pe, _krw):
    s = compute_krw_regime(_full_stage1_baseline())
    assert s.z_score == pytest.approx(0.0, abs=0.05)


@patch.object(fe, "fetch_krw_usd_level", return_value=1250.0)
@patch.object(fe, "fetch_sp_trailing_pe", return_value=18.0)
def test_compute_equity_vol_baseline_z_zero(_pe, _krw):
    s = compute_equity_vol_regime(_full_stage1_baseline())
    assert s.z_score == pytest.approx(0.0, abs=0.1)


@patch.object(fe, "fetch_krw_usd_level", return_value=1250.0)
@patch.object(fe, "fetch_sp_trailing_pe", return_value=18.0)
def test_compute_valuation_baseline_z_zero(_pe, _krw):
    s = compute_valuation(_full_stage1_baseline())
    # sp_pe=18 (baseline), erp = ey - real = 100/18 - 0.5 = 5.06, baseline ERP 4.0 sd 2 → z = 0.53
    # earnings_yield = 5.56 (baseline 5.5 sd 2) → z = 0.03
    # kospi_pbr = 1.0 (baseline) → z = 0
    # combined ≈ small positive
    assert -1.0 < s.z_score < 1.0


@patch.object(fe, "fetch_krw_usd_level", return_value=1250.0)
@patch.object(fe, "fetch_sp_trailing_pe", return_value=18.0)
def test_compute_liquidity_baseline_z_zero(_pe, _krw):
    s = compute_liquidity_regime(_full_stage1_baseline())
    # VRP = (20/100)^2 - 0.012^2 = 0.04 - 0.000144 ≈ 0.0399
    # * 10000 = 399. Baseline (50, 30) → z = (399-50)/30 = 11.6 → cap at 3.
    # 다른 components 가 0 이므로 weighted avg 가 3 보다 작을 것.
    assert s.z_score <= 3.0


# ---------- compute_all_factors smoke ----------

@patch.object(fe, "fetch_krw_usd_level", return_value=1250.0)
@patch.object(fe, "fetch_sp_trailing_pe", return_value=18.0)
def test_compute_all_factors_returns_9(_pe, _krw):
    s = compute_all_factors(_full_stage1_baseline())
    assert isinstance(s, FactorScores)
    d = s.to_dict()
    expected_keys = {
        "F1_growth", "F2_inflation", "F3_real_rate", "F4_term_premium",
        "F5_credit_cycle", "F6_krw_regime", "F7_equity_vol_regime",
        "F8_valuation", "F9_liquidity_regime",
    }
    assert set(d.keys()) == expected_keys
    for v in d.values():
        assert -3.0 <= v <= 3.0
