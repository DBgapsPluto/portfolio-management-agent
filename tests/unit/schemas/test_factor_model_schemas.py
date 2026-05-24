"""Stage 1 enhance 의 신규 schema fields 검증 (C3-C7 — factor model F1 / F4 / F7 / F8 / F9 components)."""
from datetime import date, datetime

import pytest

from tradingagents.schemas.macro import (
    FinancialConditionsSnapshot, KRValuationSnapshot, YieldCurveSnapshot,
)
from tradingagents.schemas.reports import MacroReport, RiskReport
from tradingagents.schemas.risk import BreadthSnapshot, RealVolSnapshot


def test_financial_conditions_has_cfnai_field():
    """cfnai field 가 default 0.0."""
    fci = FinancialConditionsSnapshot(
        nfci=0.0, anfci=0.0, regime="neutral", tightening=False,
        source_date=date.today(),
    )
    assert fci.cfnai == 0.0
    assert fci.cfnai_3m_avg == 0.0


def test_financial_conditions_accepts_cfnai_value():
    fci = FinancialConditionsSnapshot(
        nfci=0.0, anfci=0.0, regime="neutral", tightening=False,
        source_date=date.today(),
        cfnai=+0.5,
        cfnai_3m_avg=+0.3,
    )
    assert fci.cfnai == +0.5
    assert fci.cfnai_3m_avg == +0.3


def test_yield_curve_has_spread_30y_5y_field():
    """spread_30y_5y_bps field 가 default 0.0 (C4 — F4 term_premium component)."""
    yc = YieldCurveSnapshot(
        spread_10y_2y_bps=80.0, spread_10y_3m_bps=120.0,
        inverted_days_count=0, percentile_5y=0.5,
        source_date=date.today(),
    )
    assert yc.spread_30y_5y_bps == 0.0


def test_yield_curve_accepts_spread_30y_5y():
    yc = YieldCurveSnapshot(
        spread_10y_2y_bps=80.0, spread_10y_3m_bps=120.0,
        inverted_days_count=0, percentile_5y=0.5,
        source_date=date.today(),
        spread_30y_5y_bps=120.0,
    )
    assert yc.spread_30y_5y_bps == 120.0


# ---------- C5 — KOSPI PBR + KRValuationSnapshot 신설 (F8 valuation component) ----------


def test_kr_valuation_snapshot_basic():
    kv = KRValuationSnapshot(
        kospi_pbr=1.0, kospi_per=12.0, kospi_div_yield=2.0,
        source_date=datetime.now().date(),
    )
    assert kv.kospi_pbr == 1.0
    assert kv.kospi_per == 12.0
    assert kv.kospi_div_yield == 2.0


def test_kr_valuation_optional_in_macro_report():
    """MacroReport.kr_valuation 가 Optional, default None — backward compat."""
    macro = _build_minimal_macro_report()
    assert macro.kr_valuation is None


def test_kr_valuation_accepted_in_macro_report():
    kv = KRValuationSnapshot(
        kospi_pbr=0.95, kospi_per=11.0, kospi_div_yield=2.2,
        source_date=datetime.now().date(),
    )
    macro = _build_minimal_macro_report(kr_valuation=kv)
    assert macro.kr_valuation is not None
    assert macro.kr_valuation.kospi_pbr == 0.95


def _build_minimal_macro_report(**override) -> MacroReport:
    """Minimal MacroReport — integration test 의 _build_baseline_macro_report 와 동일
    schema 를 직접 빌드 (unit test 가 integration test 모듈에 의존하지 않도록).
    """
    from tradingagents.schemas.macro import (
        ChinaLeadingSnapshot, DivergenceScore, EmploymentSnapshot,
        FedPathSnapshot, ForeignFlowSnapshot, FXSnapshot, GDPNowSnapshot,
        InflationExpectationsSnapshot, InflationSnapshot,
        KRBusinessSurveySnapshot, KRExportSnapshot, KRLeadingIndexSnapshot,
        PolicyUncertaintySnapshot, RegimeClassification, RiskAppetiteSnapshot,
        TailRiskSnapshot, USLeadingIndexSnapshot,
    )
    today = date.today()
    base = dict(
        narrative="minimal", summary_for_downstream="minimal",
        yield_curve=YieldCurveSnapshot(
            spread_10y_2y_bps=80.0, spread_10y_3m_bps=120.0,
            inverted_days_count=0, percentile_5y=0.5, source_date=today,
        ),
        inflation=InflationSnapshot(
            cpi_yoy=2.5, core_cpi_yoy=2.5, momentum_3mo=2.5, momentum_6mo=2.5,
            accelerating=False, source_date=today,
        ),
        employment=EmploymentSnapshot(
            unemployment_rate=4.0, rate_change_3mo=0.0,
            sahm_rule_triggered=False, non_farm_payrolls_3mo_avg=150.0,
            source_date=today,
        ),
        kr_divergence=DivergenceScore(
            us_kr_rate_gap_bps=-100.0, us_kr_inflation_gap=0.0, score=0.0,
            source_date=today,
        ),
        regime=RegimeClassification(
            quadrant="growth_disinflation", confidence=0.7,
            drivers=["baseline"], reasoning="baseline", source_date=today,
        ),
        upcoming_events=[],
        kr_export=KRExportSnapshot(
            yoy_pct=5.0, momentum_3mo_pct=5.0, momentum_6mo_pct=5.0,
            accelerating=False, source_date=today,
        ),
        kr_leading=KRLeadingIndexSnapshot(
            cli_value=100.0, change_3mo=0.0, change_6mo=0.0,
            phase="expansion", source_date=today,
        ),
        kr_business_survey=KRBusinessSurveySnapshot(
            mfg_bsi=90.0, change_3mo=0.0, contraction_signal=False,
            source_date=today,
        ),
        us_leading=USLeadingIndexSnapshot(
            cfnai_value=0.0, cfnai_ma3=0.0, recession_signal=False,
            source_date=today,
        ),
        gdp_nowcast=GDPNowSnapshot(
            nowcast_pct=2.0, change_from_prior=0.0, source_date=today,
        ),
        financial_conditions=FinancialConditionsSnapshot(
            nfci=0.0, anfci=0.0, regime="neutral", tightening=False,
            source_date=today,
        ),
        inflation_expectations=InflationExpectationsSnapshot(
            breakeven_5y5y=2.3, michigan_1y=3.0, anchored=True,
            unanchored_direction="none", source_date=today,
        ),
        fed_path=FedPathSnapshot(
            current_rate_pct=5.0, implied_2y_rate_pct=5.0, path_bps=0.0,
            market_view="hold", source_date=today,
        ),
        fx=FXSnapshot(
            usd_krw=1250.0, dxy=100.0, krw_change_1m_pct=0.0,
            dxy_change_1m_pct=0.0, regime="neutral", source_date=today,
        ),
        risk_appetite=RiskAppetiteSnapshot(
            copper_price=4.0, gold_price=2000.0, ratio=0.2,
            ratio_percentile_5y=0.5, signal="neutral", source_date=today,
        ),
        china_leading=ChinaLeadingSnapshot(
            cli_value=100.0, change_3mo=0.0, phase="expansion",
            source_date=today,
        ),
        foreign_flow=ForeignFlowSnapshot(
            net_5d_krw=0.0, net_20d_krw=0.0, signal="neutral",
            source_date=today,
        ),
        policy_uncertainty=PolicyUncertaintySnapshot(
            us_epu=120.0, global_epu=120.0, us_epu_percentile_5y=0.5,
            regime="normal", source_date=today,
        ),
        tail_risk=TailRiskSnapshot(
            vvix=90.0, move=90.0, vvix_percentile_1y=0.5,
            move_percentile_1y=0.5, signal="calm", source_date=today,
        ),
    )
    base.update(override)
    return MacroReport(**base)


# ---------- C6 — SPY realized vol + RealVolSnapshot 신설 (F7 + F9 components) ----------


def test_real_vol_snapshot_basic():
    rv = RealVolSnapshot(
        realized_vol_60d=0.12, realized_vol_20d=0.10,
        source_date=datetime.now().date(),
    )
    assert rv.realized_vol_60d == pytest.approx(0.12)
    assert rv.realized_vol_20d == pytest.approx(0.10)
    assert rv.vrp_60d == 0.0  # default


def test_real_vol_snapshot_with_vrp():
    rv = RealVolSnapshot(
        realized_vol_60d=0.12, realized_vol_20d=0.10, vrp_60d=120.0,
        source_date=datetime.now().date(),
    )
    assert rv.vrp_60d == 120.0


def test_risk_report_real_vol_optional_default_none():
    """RiskReport.real_vol Optional, default None — backward compat."""
    risk = _build_minimal_risk_report()
    assert risk.real_vol is None


def test_risk_report_real_vol_accepted():
    rv = RealVolSnapshot(
        realized_vol_60d=0.15, realized_vol_20d=0.13, vrp_60d=80.0,
        source_date=datetime.now().date(),
    )
    risk = _build_minimal_risk_report(real_vol=rv)
    assert risk.real_vol is not None
    assert risk.real_vol.realized_vol_60d == pytest.approx(0.15)


# ---------- C7 — sector dispersion + BreadthSnapshot 확장 (F9 liquidity component) ----------


def test_breadth_has_sector_dispersion_default():
    """sector_return_dispersion field default 0.0 (C7 — F9 liquidity component)."""
    breadth = BreadthSnapshot(
        market="SP500",
        advancing_pct=0.55,
        declining_pct=0.45,
        new_highs_minus_lows=0,
        source_date=datetime.now().date(),
    )
    assert breadth.sector_return_dispersion == 0.0


def test_breadth_accepts_sector_dispersion():
    breadth = BreadthSnapshot(
        market="SP500",
        advancing_pct=0.55,
        declining_pct=0.45,
        new_highs_minus_lows=0,
        source_date=datetime.now().date(),
        sector_return_dispersion=2.5,
    )
    assert breadth.sector_return_dispersion == pytest.approx(2.5)


# ---------- C7.5 — SkewSnapshot.change_1m_z field (F7 skew_change placeholder 해소) ----------


def test_skew_has_change_1m_z_default():
    """change_1m_z default 0.0 — F7 equity_vol_regime component."""
    from tradingagents.schemas.risk import SkewSnapshot
    skew = SkewSnapshot(
        skew_value=118.0,
        percentile_1y=0.5,
        tail_hedge_signal="normal",
        source_date=datetime.now().date(),
    )
    assert skew.change_1m_z == 0.0


def test_skew_accepts_change_1m_z():
    from tradingagents.schemas.risk import SkewSnapshot
    skew = SkewSnapshot(
        skew_value=130.0,
        percentile_1y=0.7,
        tail_hedge_signal="elevated",
        source_date=datetime.now().date(),
        change_1m_z=+1.5,
    )
    assert skew.change_1m_z == pytest.approx(1.5)


def _build_minimal_risk_report(**override) -> RiskReport:
    """Minimal RiskReport — integration test 의 _build_baseline_risk_report 와 동일
    schema 를 직접 빌드 (unit test 가 integration test 모듈에 의존하지 않도록).
    """
    from tradingagents.schemas.risk import (
        BreadthSnapshot, CreditQualitySnapshot, EquityBondCorrelationSnapshot,
        FundingStressSnapshot, KRCorpSpreadSnapshot, KRMarginDebtSnapshot,
        KRMarketTierSnapshot, KRYieldCurveSnapshot, PCASnapshot,
        RealYieldsSnapshot, SentimentSnapshot, SkewSnapshot, SpreadSnapshot,
        SystemicRiskScore, VIXTermStructureSnapshot, VolatilitySnapshot,
        VxnSnapshot,
    )
    today = date.today()
    base = dict(
        narrative="minimal", summary_for_downstream="minimal",
        vix=VolatilitySnapshot(
            index_name="VIX", current_value=20.0, zscore_30d=0.0,
            percentile_5y=0.5, change_4w=0.0, source_date=today,
        ),
        vkospi=VolatilitySnapshot(
            index_name="VKOSPI", current_value=20.0, zscore_30d=0.0,
            percentile_5y=0.5, change_4w=0.0, source_date=today,
        ),
        credit_spread_us_ig=SpreadSnapshot(
            region="US_IG", current_bps=120.0, percentile_5y=0.5,
            widening=False, momentum_zscore=0.0, source_date=today,
        ),
        credit_spread_us_hy=SpreadSnapshot(
            region="US_HY", current_bps=400.0, percentile_5y=0.5,
            widening=False, momentum_zscore=0.0, source_date=today,
        ),
        fear_greed=SentimentSnapshot(
            index_name="fear_greed_cnn", current_value=50,
            label="neutral", trend_7d="flat", source_date=today,
        ),
        breadth_kr=BreadthSnapshot(
            market="KOSPI200", advancing_pct=0.55, declining_pct=0.45,
            new_highs_minus_lows=0, source_date=today,
        ),
        breadth_us=BreadthSnapshot(
            market="SP500", advancing_pct=0.55, declining_pct=0.45,
            new_highs_minus_lows=0, source_date=today,
        ),
        correlation_concentration=PCASnapshot(
            first_eigenvalue_share=0.4, n_assets_analyzed=20,
            is_concentrated=False, source_date=today,
        ),
        systemic_score=SystemicRiskScore(
            score=5.0, regime="neutral", drivers=["baseline"],
            reasoning="baseline", source_date=today,
        ),
        vix_term=VIXTermStructureSnapshot(
            vix_front=20.0, vix_3m=20.0, ratio=1.0, regime="flat",
            source_date=today,
        ),
        skew=SkewSnapshot(
            skew_value=118.0, percentile_1y=0.5, tail_hedge_signal="normal",
            source_date=today,
        ),
        vxn=VxnSnapshot(
            current_value=22.0, zscore_30d=0.0, percentile_5y=0.5,
            spread_vs_vix=2.0, tech_focused_stress=False, source_date=today,
        ),
        real_yields=RealYieldsSnapshot(
            tips_10y=0.5, tips_5y=0.3, spread_10y_5y=0.2, regime="neutral",
            source_date=today,
        ),
        funding_stress=FundingStressSnapshot(
            sofr=5.3, tbill_3m=5.2, spread_bps=10.0, regime="calm",
            source_date=today,
        ),
        credit_quality=CreditQualitySnapshot(
            aaa_oas_bps=60.0, bbb_oas_bps=150.0, quality_spread_bps=90.0,
            percentile_5y=0.5, regime="calm", source_date=today,
        ),
        kr_yield_curve=KRYieldCurveSnapshot(
            treasury_3y=3.5, treasury_10y=4.0, spread_10y_3y_bps=50.0,
            inverted=False, regime="flat", source_date=today,
        ),
        kr_corp_spread=KRCorpSpreadSnapshot(
            corp_yield_3y=4.5, treasury_3y=3.5, spread_bps=100.0,
            percentile_5y=0.5, regime="calm", source_date=today,
        ),
        kr_margin_debt=KRMarginDebtSnapshot(
            balance_krw=20e12, change_20d_pct=0.0, percentile_1y=0.5,
            signal="normal", source_date=today,
        ),
        kr_market_tier=KRMarketTierSnapshot(
            kospi_return_20d_pct=0.0, kosdaq_return_20d_pct=0.0,
            relative_perf_pct=0.0, signal="neutral", source_date=today,
        ),
        equity_bond_corr=EquityBondCorrelationSnapshot(
            correlation_120d=-0.2, change_3m=0.0, regime="normal_hedge",
            source_date=today,
        ),
    )
    base.update(override)
    return RiskReport(**base)
