"""Real Stage 1 schema instance 으로 factor estimator 검증 (C2).

목적: PR0 의 silent path mismatch 차단 — MagicMock 의 attribute 자동 생성 으로
인해 broken path 가 silent pass 되던 문제 영구 방지.

본 test 는 *진짜* pydantic-validated MacroReport / RiskReport / TechnicalReport /
NewsReport instance 로 compute_all_factors 를 실행해, 각 factor 가 *적어도 1*
active component (confidence > 0) 를 갖는지 + extreme perturbation 이
정확한 sign 으로 전파되는지 검증.

C1 의 path fix 정확도 의 최종 gate.
"""
from __future__ import annotations

from datetime import date
from typing import Any
from unittest.mock import patch

import pytest

from tradingagents.schemas.macro import (
    ChinaLeadingSnapshot,
    DivergenceScore,
    EmploymentSnapshot,
    FedPathSnapshot,
    FinancialConditionsSnapshot,
    ForeignFlowSnapshot,
    FXSnapshot,
    GDPNowSnapshot,
    InflationExpectationsSnapshot,
    InflationSnapshot,
    KRBusinessSurveySnapshot,
    KRExportSnapshot,
    KRLeadingIndexSnapshot,
    PolicyUncertaintySnapshot,
    RegimeClassification,
    RiskAppetiteSnapshot,
    TailRiskSnapshot,
    USLeadingIndexSnapshot,
    YieldCurveSnapshot,
)
from tradingagents.schemas.reports import (
    MacroReport,
    NewsReport,
    RiskReport,
    TechnicalReport,
)
from tradingagents.schemas.risk import (
    BreadthSnapshot,
    CreditQualitySnapshot,
    EquityBondCorrelationSnapshot,
    FundingStressSnapshot,
    KRCorpSpreadSnapshot,
    KRMarginDebtSnapshot,
    KRMarketTierSnapshot,
    KRYieldCurveSnapshot,
    PCASnapshot,
    RealYieldsSnapshot,
    SentimentSnapshot,
    SkewSnapshot,
    SpreadSnapshot,
    SystemicRiskScore,
    VIXTermStructureSnapshot,
    VolatilitySnapshot,
    VxnSnapshot,
)
from tradingagents.skills.research import factor_estimators as fe
from tradingagents.skills.research.factor_estimators import compute_all_factors


# ---------------- helpers: per-schema builders (baseline values) ---------------


def _build_baseline_macro_report() -> MacroReport:
    """모든 required field 채움; factor estimator 가 *읽는* field 는
    LONG_RUN_BASELINE 의 mean 값 (z=0).
    """
    return MacroReport(
        narrative="baseline macro",
        summary_for_downstream="baseline macro summary",
        yield_curve=YieldCurveSnapshot(
            spread_10y_2y_bps=80.0,     # F1.curve baseline mean = 80.0
            spread_10y_3m_bps=120.0,
            inverted_days_count=0,
            percentile_5y=0.5,
        ),
        inflation=InflationSnapshot(
            cpi_yoy=2.5,                # F2.cpi_yoy mean = 2.5
            core_cpi_yoy=2.5,
            momentum_3mo=2.5,           # F2.cpi_3m mean = 2.5
            momentum_6mo=2.5,
            accelerating=False,
            pce_yoy=2.0,
            core_pce_yoy=2.0,           # F2.core_pce mean = 2.0
            pce_momentum_3mo=2.0,
        ),
        employment=EmploymentSnapshot(
            unemployment_rate=4.0,
            rate_change_3mo=0.0,
            sahm_rule_triggered=False,  # F1.sahm → 0.5 (not triggered)
            non_farm_payrolls_3mo_avg=150.0,
            job_openings_3mo_avg=8000.0,
            quits_rate=2.5,
            quits_rate_change_6mo=0.0,
        ),
        kr_divergence=DivergenceScore(
            us_kr_rate_gap_bps=-100.0,  # F6.kr_us_rate_diff mean = -100.0
            us_kr_inflation_gap=0.0,
            score=0.0,
        ),
        regime=RegimeClassification(
            quadrant="growth_disinflation",
            confidence=0.7,
            drivers=["baseline"],
            reasoning="baseline regime",
        ),
        upcoming_events=[],
        kr_export=KRExportSnapshot(
            yoy_pct=5.0,                # F6.kr_exports_yoy mean = 5.0
            momentum_3mo_pct=5.0,
            momentum_6mo_pct=5.0,
            accelerating=False,
        ),
        kr_leading=KRLeadingIndexSnapshot(
            cli_value=100.0,
            change_3mo=0.0,
            change_6mo=0.0,
            phase="expansion",
        ),
        kr_business_survey=KRBusinessSurveySnapshot(
            mfg_bsi=90.0,
            change_3mo=0.0,
            contraction_signal=False,
        ),
        us_leading=USLeadingIndexSnapshot(
            cfnai_value=0.0,
            cfnai_ma3=0.0,
            recession_signal=False,
            recession_severity="none",
        ),
        gdp_nowcast=GDPNowSnapshot(
            nowcast_pct=2.0,            # F1.gdpnow mean = 2.0
            change_from_prior=0.0,
        ),
        financial_conditions=FinancialConditionsSnapshot(
            nfci=0.0,                   # F1.nfci → -nfci = 0.0 (mean 0)
            anfci=0.0,
            regime="neutral",
            tightening=False,
        ),
        inflation_expectations=InflationExpectationsSnapshot(
            breakeven_5y5y=2.3,         # F2.five_y_five_y mean = 2.3
            michigan_1y=3.0,            # F2.michigan_1y mean = 3.0
            anchored=True,
            unanchored_direction="none",
        ),
        fed_path=FedPathSnapshot(
            current_rate_pct=5.0,
            implied_2y_rate_pct=5.0,
            path_bps=0.0,               # F2.fed_path_bps / F3.fed_path_implied mean = 0.0
            market_view="hold",
        ),
        fx=FXSnapshot(
            usd_krw=1250.0,             # F6.krw_level mean = 1250.0
            dxy=100.0,
            krw_change_1m_pct=0.0,
            dxy_change_1m_pct=0.0,
            regime="neutral",
        ),
        risk_appetite=RiskAppetiteSnapshot(
            copper_price=4.0,
            gold_price=2000.0,
            ratio=0.2,
            ratio_percentile_1y=0.5,
            signal="neutral",
        ),
        china_leading=ChinaLeadingSnapshot(
            cli_value=100.0,
            change_3mo=0.0,
            phase="expansion",
        ),
        foreign_flow=ForeignFlowSnapshot(
            net_5d_krw=0.0,
            net_20d_krw=0.0,            # F6.foreign_flow_z mean = 0.0 (raw scale)
            signal="neutral",
        ),
        policy_uncertainty=PolicyUncertaintySnapshot(
            us_epu=120.0,
            global_epu=120.0,
            us_epu_percentile_5y=0.5,
            regime="normal",
        ),
        tail_risk=TailRiskSnapshot(
            vvix=90.0,
            move=90.0,                  # F7.move mean = 90.0
            vvix_percentile_1y=0.5,
            move_percentile_1y=0.5,
            signal="calm",
        ),
    )


def _build_baseline_risk_report() -> RiskReport:
    """RiskReport baseline — VIX 20, hy_oas 400 bps, real_yields tips_10y 0.5 등."""
    return RiskReport(
        narrative="baseline risk",
        summary_for_downstream="baseline risk summary",
        vix=VolatilitySnapshot(
            index_name="VIX",
            current_value=20.0,         # F7.vix_level mean = 20.0
            zscore_30d=0.0,             # F7.vix_z_score mean = 0.0
            percentile_5y=0.5,
            change_4w=0.0,
        ),
        vkospi=VolatilitySnapshot(
            index_name="VKOSPI",
            current_value=20.0,
            zscore_30d=0.0,
            percentile_5y=0.5,
            change_4w=0.0,
        ),
        credit_spread_us_ig=SpreadSnapshot(
            region="US_IG",
            current_bps=120.0,
            percentile_5y=0.5,
            widening=False,
            momentum_zscore=0.0,
        ),
        credit_spread_us_hy=SpreadSnapshot(
            region="US_HY",
            current_bps=400.0,          # F5.hy_oas_bps mean = 400.0
            percentile_5y=0.5,
            widening=False,
            momentum_zscore=0.0,        # F5.hy_oas_momentum mean = 0.0
        ),
        fear_greed=SentimentSnapshot(
            index_name="fear_greed_cnn",
            current_value=50,
            label="neutral",
            trend_7d="flat",
        ),
        breadth_kr=BreadthSnapshot(
            market="KOSPI200",
            advancing_pct=0.55,         # F9.breadth mean = 0.55
            declining_pct=0.45,
            new_highs_minus_lows=0,
        ),
        breadth_us=BreadthSnapshot(
            market="SP500",
            advancing_pct=0.55,
            declining_pct=0.45,
            new_highs_minus_lows=0,
        ),
        correlation_concentration=PCASnapshot(
            first_eigenvalue_share=0.4,
            n_assets_analyzed=20,
            is_concentrated=False,
        ),
        systemic_score=SystemicRiskScore(
            score=5.0,
            regime="neutral",
            drivers=["baseline"],
            reasoning="baseline",
        ),
        vix_term=VIXTermStructureSnapshot(
            vix_front=20.0,
            vix_3m=20.0,
            ratio=1.0,                  # F7.vix_term_ratio mean = 1.0
            regime="flat",
        ),
        skew=SkewSnapshot(
            skew_value=118.0,
            percentile_1y=0.5,
            tail_hedge_signal="normal",
        ),
        vxn=VxnSnapshot(
            current_value=22.0,
            zscore_30d=0.0,
            percentile_5y=0.5,
            spread_vs_vix=2.0,
            tech_focused_stress=False,
        ),
        real_yields=RealYieldsSnapshot(
            tips_10y=0.5,               # F3.tips_yield mean = 0.5;
                                        # F2.real_yield_inv = -0.5 (mean -0.5)
            tips_5y=0.3,
            spread_10y_5y=0.2,
            regime="neutral",
        ),
        funding_stress=FundingStressSnapshot(
            sofr=5.3,
            tbill_3m=5.2,
            spread_bps=10.0,            # F5.funding_bps mean = 10.0
            regime="calm",
        ),
        credit_quality=CreditQualitySnapshot(
            aaa_oas_bps=60.0,
            bbb_oas_bps=150.0,
            quality_spread_bps=90.0,    # F5.credit_quality_bps mean = 90.0
            percentile_5y=0.5,
            regime="calm",
        ),
        kr_yield_curve=KRYieldCurveSnapshot(
            treasury_3y=3.5,
            treasury_10y=4.0,
            spread_10y_3y_bps=50.0,
            inverted=False,
            regime="flat",
        ),
        kr_corp_spread=KRCorpSpreadSnapshot(
            corp_yield_3y=4.5,
            treasury_3y=3.5,
            spread_bps=100.0,
            percentile_5y=0.5,
            regime="calm",
        ),
        kr_margin_debt=KRMarginDebtSnapshot(
            balance_krw=20e12,
            change_20d_pct=0.0,
            percentile_1y=0.5,
            signal="normal",
        ),
        kr_market_tier=KRMarketTierSnapshot(
            kospi_return_20d_pct=0.0,
            kosdaq_return_20d_pct=0.0,
            relative_perf_pct=0.0,
            signal="neutral",
        ),
        equity_bond_corr=EquityBondCorrelationSnapshot(
            correlation_60d=-0.2,       # F9.eq_bond_corr mean = -0.2
            change_3m=0.0,
            regime="normal_hedge",
        ),
    )


def _build_baseline_technical_report() -> TechnicalReport:
    """TechnicalReport — factor_estimators 는 technical_report 의 어떤 field
    도 *직접* 읽지 않음 (C1 placeholder/C8). 따라서 empty 로 OK.
    """
    return TechnicalReport(
        narrative="baseline technical",
        summary_for_downstream="baseline technical summary",
        asset_class_momentum={},
        individual_etf_states={},
        correlation_clusters=[],
    )


def _build_baseline_news_report() -> NewsReport:
    """NewsReport — release_surprise / news_sentiment / cb_speakers /
    global_overnight 의 baseline value 채움.

    global_overnight 의 OvernightMove schema 는 N225 등 9 자산을 요구하지만
    factor_estimators 는 그 중 `krw.change_pct` 와 `risk_regime_overnight` 만
    read. Pydantic schema validation 위해 적어도 krw OvernightMove 1개와
    risk_regime_overnight 채움. fetched_count = 1, narrative_seed 채움.
    """
    from tradingagents.schemas.news import (
        GlobalOvernightSnapshot,
        NewsSentimentSnapshot,
        OvernightMove,
        ReleaseSurpriseSnapshot,
        SpeakerToneAggregate,
    )

    krw_move = OvernightMove(
        name="USDKRW",
        ticker="KRW=X",
        value=1250.0,
        prior=1250.0,
        change_abs=0.0,
        change_pct=0.0,                 # F6.krw_overnight_pct mean = 0.0
        direction="flat",
    )

    return NewsReport(
        narrative="baseline news",
        summary_for_downstream="baseline news summary",
        upcoming_events=[],
        ranked_news=[],
        global_overnight=GlobalOvernightSnapshot(
            europe={},
            asia={},
            commodities={},
            krw=krw_move,
            risk_regime_overnight="mixed",  # F1.risk_regime_overnight → 0.0
            narrative_seed="baseline overnight",
            fetched_count=1,
        ),
        release_surprise=ReleaseSurpriseSnapshot(
            today_releases=[],
            last_5d_releases=[],
            surprise_index_30d=0.0,     # F1.release_surprise mean = 0.0
            high_importance_today=2,    # F9.event_cluster (mean 1.5, sd 1.5)
            bias_30d="balanced",        # F1.hawkish_bias → 0.0; F5.dovish_bias → 0.0
        ),
        news_sentiment=NewsSentimentSnapshot(
            counts={},
            avg_sentiment={
                "macro": 0.0,            # F1.macro_sent / F2.macro_sent mean = 0.0
                "corporate": 0.0,
                "geopolitical": 0.0,
                "policy": 0.0,
                "market_commentary": 0.0,
            },
            dominant_category=None,
            sentiment_dispersion=0.3,    # F7.sentiment_dispersion mean = 0.3
            top_headline_per_category={},
            count_change_vs_7d={
                "corporate": 0.0,
                "geopolitical": 0.0,     # F7.geopolitical_surge mean = 0.0
                "policy": 0.0,
                "macro": 0.0,
                "market_commentary": 0.0,
            },
            rising_category=None,        # F9.rising_signal → 0.0 (ns exists)
        ),
        cb_speakers=SpeakerToneAggregate(
            fed_speakers_7d=[],
            bok_speakers_7d=[],
            other_speakers_7d=[],
            fed_tone_balance=0.0,        # F4.fed_tone_balance mean = 0.0
            bok_tone_balance=0.0,        # F6.bok_tone_balance mean = 0.0
            fed_voting_balance=0.0,      # F3.fed_voting_balance / F4 mean = 0.0
        ),
    )


# ---------------------------- fixtures ----------------------------


@pytest.fixture
def real_stage1_baseline() -> dict[str, Any]:
    """모든 9 factor 의 component 가 readable 한 real Stage 1 state.

    State shape 는 productions Stage 1 와 동일 — dict with 4 reports + summaries.
    각 report 는 pydantic-validated *real* instance.
    """
    return {
        "macro_summary": "baseline",
        "risk_summary": "baseline",
        "technical_summary": "baseline",
        "news_summary": "baseline",
        "macro_report": _build_baseline_macro_report(),
        "risk_report": _build_baseline_risk_report(),
        "technical_report": _build_baseline_technical_report(),
        "news_report": _build_baseline_news_report(),
    }


# ---------------------------- sanity test ----------------------------


def test_baseline_helper_builds_valid_schema(real_stage1_baseline: dict[str, Any]) -> None:
    """First gate: pydantic validation pass — all 4 reports are real instances."""
    assert isinstance(real_stage1_baseline["macro_report"], MacroReport)
    assert isinstance(real_stage1_baseline["risk_report"], RiskReport)
    assert isinstance(real_stage1_baseline["technical_report"], TechnicalReport)
    assert isinstance(real_stage1_baseline["news_report"], NewsReport)


# ---------------------------- coverage / no silent path mismatch ----------------------------


@patch.object(fe, "fetch_krw_usd_level", return_value=1250.0)
@patch.object(fe, "fetch_sp_trailing_pe", return_value=18.0)
def test_compute_all_factors_with_real_schema_after_c1(
    _pe: Any, _krw: Any, real_stage1_baseline: dict[str, Any]
) -> None:
    """C1 (path fix only) 후 — 각 factor 의 expected coverage 충족.

    6 placeholder (cfnai, slope_5_30y, realized_vol, kospi_pbr, sector_dispersion,
    skew_change) 는 weight=0 이라 confidence 에서 제외.

    expected_min 은 *path fix only* (no placeholder activation) 상태 기준의
    보수적 threshold — 실측 보다 5-15% 마진.
    """
    scores = compute_all_factors(real_stage1_baseline)

    expected_min = {
        "growth_surprise":    0.60,
        "inflation_surprise": 0.80,
        "real_rate":          0.80,
        "term_premium":       0.55,
        "credit_cycle":       0.80,
        "krw_regime":         0.70,
        "equity_vol_regime":  0.60,
        "valuation":          0.40,
        "liquidity_regime":   0.30,
    }
    for factor_name, min_cov in expected_min.items():
        score = getattr(scores, factor_name)
        assert score.confidence >= min_cov, (
            f"{factor_name} confidence {score.confidence:.2f} < {min_cov} "
            f"(components: {list(score.components.keys())})"
        )


@patch.object(fe, "fetch_krw_usd_level", return_value=1250.0)
@patch.object(fe, "fetch_sp_trailing_pe", return_value=18.0)
def test_no_silent_path_mismatch(
    _pe: Any, _krw: Any, real_stage1_baseline: dict[str, Any]
) -> None:
    """모든 factor 가 *적어도 1 active component* (confidence > 0).

    silent broken state 의 직접 detector: path mismatch 가 1 개라도 있으면
    그 factor 의 confidence == 0 → fail.
    """
    scores = compute_all_factors(real_stage1_baseline)
    for factor_name in (
        "growth_surprise",
        "inflation_surprise",
        "real_rate",
        "term_premium",
        "credit_cycle",
        "krw_regime",
        "equity_vol_regime",
        "valuation",
        "liquidity_regime",
    ):
        score = getattr(scores, factor_name)
        assert score.confidence > 0, (
            f"{factor_name}: silent broken — 0 active components, "
            f"raw components dict={score.components}"
        )


@patch.object(fe, "fetch_krw_usd_level", return_value=1250.0)
@patch.object(fe, "fetch_sp_trailing_pe", return_value=18.0)
def test_extreme_inflation_propagates(
    _pe: Any, _krw: Any, real_stage1_baseline: dict[str, Any]
) -> None:
    """High inflation → F2 z 크게 positive (path 정확 작동 검증).

    perturbation 은 inflation 의 3 핵심 raw component (cpi_yoy, momentum_3mo,
    core_pce_yoy) 만 — schema path 가 정확히 wire 됐다면 F2 z 크게 positive.
    fed_path / breakeven 등 다른 component 는 baseline 유지하여 path 만 검증.
    """
    state = dict(real_stage1_baseline)
    # InflationSnapshot is pydantic; copy + replace fields via model_copy.
    macro = state["macro_report"]
    new_inflation = macro.inflation.model_copy(
        update={"cpi_yoy": 8.0, "momentum_3mo": 10.0, "core_pce_yoy": 5.0}
    )
    state["macro_report"] = macro.model_copy(update={"inflation": new_inflation})

    scores = compute_all_factors(state)
    assert scores.inflation_surprise.z_score > 1.0, (
        f"F2 should respond strongly to inflation, "
        f"got {scores.inflation_surprise.z_score:.2f}"
    )


@patch.object(fe, "fetch_krw_usd_level", return_value=1250.0)
@patch.object(fe, "fetch_sp_trailing_pe", return_value=18.0)
def test_extreme_vix_propagates_to_f7(
    _pe: Any, _krw: Any, real_stage1_baseline: dict[str, Any]
) -> None:
    """High VIX → F7 z 크게 positive."""
    state = dict(real_stage1_baseline)
    risk = state["risk_report"]
    new_vix = risk.vix.model_copy(
        update={"current_value": 45.0, "zscore_30d": 3.0}
    )
    state["risk_report"] = risk.model_copy(update={"vix": new_vix})

    scores = compute_all_factors(state)
    assert scores.equity_vol_regime.z_score > 0.5, (
        f"F7 should respond to high VIX, "
        f"got {scores.equity_vol_regime.z_score:.2f}"
    )
