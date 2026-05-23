"""Stage 1 enhance 의 신규 schema fields 검증 (C3-C5 — factor model F1 / F4 / F8 components)."""
from datetime import date, datetime

from tradingagents.schemas.macro import (
    FinancialConditionsSnapshot, KRValuationSnapshot, YieldCurveSnapshot,
)
from tradingagents.schemas.reports import MacroReport


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
            ratio_percentile_1y=0.5, signal="neutral", source_date=today,
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
