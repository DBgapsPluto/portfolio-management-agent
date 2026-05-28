import pytest
from pydantic import ValidationError
from tradingagents.schemas.reports import (
    MacroReport, RiskReport, TechnicalReport, NewsReport,
)
from tradingagents.schemas.macro import (
    YieldCurveSnapshot, InflationSnapshot, EmploymentSnapshot,
    DivergenceScore, RegimeClassification,
    KRExportSnapshot, KRLeadingIndexSnapshot, KRBusinessSurveySnapshot,
    USLeadingIndexSnapshot, GDPNowSnapshot,
    FinancialConditionsSnapshot, InflationExpectationsSnapshot, FedPathSnapshot,
    FXSnapshot, RiskAppetiteSnapshot, ChinaLeadingSnapshot, ForeignFlowSnapshot,
    PolicyUncertaintySnapshot, TailRiskSnapshot,
)


_TIER_DEFAULTS = dict(
    # Tier 1
    kr_export=KRExportSnapshot(
        yoy_pct=0.0, momentum_3mo_pct=0.0, momentum_6mo_pct=0.0, accelerating=False,
    ),
    kr_leading=KRLeadingIndexSnapshot(
        cli_value=100.0, change_3mo=0.0, change_6mo=0.0, phase="expansion",
    ),
    kr_business_survey=KRBusinessSurveySnapshot(
        mfg_bsi=100.0, change_3mo=0.0, contraction_signal=False,
    ),
    us_leading=USLeadingIndexSnapshot(
        cfnai_value=0.0, cfnai_ma3=0.0, recession_signal=False,
    ),
    gdp_nowcast=GDPNowSnapshot(nowcast_pct=2.0, change_from_prior=0.0),
    # Tier 2
    financial_conditions=FinancialConditionsSnapshot(
        nfci=0.0, anfci=0.0, regime="neutral", tightening=False,
    ),
    inflation_expectations=InflationExpectationsSnapshot(
        breakeven_5y5y=2.0, michigan_1y=3.0, anchored=True, unanchored_direction="none",
    ),
    fed_path=FedPathSnapshot(
        current_rate_pct=4.5, implied_2y_rate_pct=4.5, path_bps=0.0, market_view="hold",
    ),
    # Tier 3
    fx=FXSnapshot(
        usd_krw=1300.0, dxy=100.0, krw_change_1m_pct=0.0, dxy_change_1m_pct=0.0,
        regime="neutral",
    ),
    risk_appetite=RiskAppetiteSnapshot(
        copper_price=4.0, gold_price=2000.0, ratio=0.2, ratio_percentile_5y=0.5,
        signal="neutral",
    ),
    china_leading=ChinaLeadingSnapshot(
        cli_value=100.0, change_3mo=0.0, phase="expansion",
    ),
    foreign_flow=ForeignFlowSnapshot(
        net_5d_krw=0.0, net_20d_krw=0.0, signal="neutral",
    ),
    # Tier 4
    policy_uncertainty=PolicyUncertaintySnapshot(
        us_epu=100.0, global_epu=100.0, us_epu_percentile_5y=0.5, regime="normal",
    ),
    tail_risk=TailRiskSnapshot(
        vvix=90.0, move=100.0, vvix_percentile_1y=0.5, move_percentile_1y=0.5,
        signal="calm",
    ),
)


_TIER_DEFAULTS_DICT = dict(
    kr_export={"yoy_pct": 0, "momentum_3mo_pct": 0, "momentum_6mo_pct": 0, "accelerating": False},
    kr_leading={"cli_value": 100, "change_3mo": 0, "change_6mo": 0, "phase": "expansion"},
    kr_business_survey={"mfg_bsi": 100, "change_3mo": 0, "contraction_signal": False},
    us_leading={"cfnai_value": 0, "cfnai_ma3": 0, "recession_signal": False},
    gdp_nowcast={"nowcast_pct": 2.0, "change_from_prior": 0},
    financial_conditions={"nfci": 0, "anfci": 0, "regime": "neutral", "tightening": False},
    inflation_expectations={
        "breakeven_5y5y": 2.0, "michigan_1y": 3.0, "anchored": True,
        "unanchored_direction": "none",
    },
    fed_path={
        "current_rate_pct": 4.5, "implied_2y_rate_pct": 4.5, "path_bps": 0.0,
        "market_view": "hold",
    },
    fx={
        "usd_krw": 1300.0, "dxy": 100.0, "krw_change_1m_pct": 0.0,
        "dxy_change_1m_pct": 0.0, "regime": "neutral",
    },
    risk_appetite={
        "copper_price": 4.0, "gold_price": 2000.0, "ratio": 0.2,
        "ratio_percentile_5y": 0.5, "signal": "neutral",
    },
    china_leading={"cli_value": 100.0, "change_3mo": 0, "phase": "expansion"},
    foreign_flow={"net_5d_krw": 0, "net_20d_krw": 0, "signal": "neutral"},
    policy_uncertainty={
        "us_epu": 100.0, "global_epu": 100.0, "us_epu_percentile_5y": 0.5,
        "regime": "normal",
    },
    tail_risk={
        "vvix": 90.0, "move": 100.0, "vvix_percentile_1y": 0.5,
        "move_percentile_1y": 0.5, "signal": "calm",
    },
)


def test_macro_report_narrative_max_length():
    yc = YieldCurveSnapshot(
        spread_10y_2y_bps=-25.0, spread_10y_3m_bps=-30.0,
        inverted_days_count=120, percentile_5y=0.05,
    )
    infl = InflationSnapshot(
        cpi_yoy=2.8, core_cpi_yoy=3.2, momentum_3mo=2.5,
        momentum_6mo=3.0, accelerating=False,
    )
    emp = EmploymentSnapshot(
        unemployment_rate=4.2, rate_change_3mo=0.5,
        sahm_rule_triggered=True, non_farm_payrolls_3mo_avg=140_000,
    )
    div = DivergenceScore(us_kr_rate_gap_bps=200.0, us_kr_inflation_gap=0.5, score=2.5)
    regime = RegimeClassification(
        quadrant="recession_disinflation", confidence=0.85,
        drivers=["yield curve"], reasoning="x",
    )
    report = MacroReport(
        yield_curve=yc, inflation=infl, employment=emp,
        kr_divergence=div, regime=regime,
        upcoming_events=[], narrative="짧은 매크로 요약",
        summary_for_downstream="recession-disinflation, 35% risk asset",
        **_TIER_DEFAULTS,
    )
    assert len(report.narrative) <= 500


def test_narrative_too_long_rejected():
    with pytest.raises(ValidationError):
        MacroReport.model_validate({
            "yield_curve": {"spread_10y_2y_bps": 0, "spread_10y_3m_bps": 0,
                            "inverted_days_count": 0, "percentile_5y": 0.5},
            "inflation": {"cpi_yoy": 0, "core_cpi_yoy": 0, "momentum_3mo": 0,
                          "momentum_6mo": 0, "accelerating": False},
            "employment": {"unemployment_rate": 0, "rate_change_3mo": 0,
                           "sahm_rule_triggered": False, "non_farm_payrolls_3mo_avg": 0},
            "kr_divergence": {"us_kr_rate_gap_bps": 0, "us_kr_inflation_gap": 0, "score": 0},
            "regime": {"quadrant": "growth_inflation", "confidence": 0.5,
                       "drivers": ["x"], "reasoning": "y"},
            "upcoming_events": [],
            "narrative": "x" * 501,
            "summary_for_downstream": "y",
            **_TIER_DEFAULTS_DICT,
        })
