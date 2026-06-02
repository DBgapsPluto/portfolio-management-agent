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
    KRValuationSnapshot,
    PolicyUncertaintySnapshot,
    RegimeClassification,
    RiskAppetiteSnapshot,
    TailRiskSnapshot,
    USEquityValuationSnapshot,
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
    ExcessBondPremiumSnapshot,
    FundingStressSnapshot,
    KRCorpSpreadSnapshot,
    KRMarginDebtSnapshot,
    KRMarketTierSnapshot,
    KRYieldCurveSnapshot,
    PCASnapshot,
    RealVolSnapshot,
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
            spread_30y_5y_bps=80.0,     # ★ NEW (C4) — F4.slope_5_30y baseline mean = 80.0
            acm_term_premium_10y_pct=0.5,  # ★ NEW (C8) — F4.acm_term_premium_10y baseline mean = 0.5
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
        us_indpro_yoy_pct=2.0,         # ★ NEW (C8) — F1.indpro_yoy baseline mean = 2.0
        us_real_pce_yoy_pct=2.5,       # ★ NEW (C8) — F1.real_pce_yoy baseline mean = 2.5
        us_equity_valuation=USEquityValuationSnapshot(
            cape=20.0,                 # ★ NEW (C8) — F8.us_cape baseline mean = 20.0
        ),
        financial_conditions=FinancialConditionsSnapshot(
            nfci=0.0,                   # F1.nfci → -nfci = 0.0 (mean 0)
            anfci=0.0,
            regime="neutral",
            tightening=False,
            cfnai=0.0,                  # ★ NEW (C3) — F1.cfnai baseline mean = 0.0
            cfnai_3m_avg=0.0,           # ★ NEW (C3) — F1.cfnai_3m baseline mean = 0.0
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
            ratio_percentile_5y=0.5,
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
        # ★ NEW (C5) — F8.kospi_pbr baseline mean = 1.0
        kr_valuation=KRValuationSnapshot(
            kospi_pbr=1.0,
            kospi_per=12.0,
            kospi_div_yield=2.0,
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
        excess_bond_premium=ExcessBondPremiumSnapshot(
            ebp=0.0,                    # ★ NEW (C8) — F5.gz_ebp baseline mean = 0.0
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
            sector_return_dispersion=0.05,  # ★ NEW (C7) — F9 baseline mean = 0.05
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
            change_1m_z=0.0,            # ★ NEW (C7.5) — F7.skew_change baseline mean = 0.0
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
            correlation_120d=-0.2,       # F9.eq_bond_corr mean = -0.2
            change_3m=0.0,
            regime="normal_hedge",
        ),
        # ★ NEW (C6) — F7.realized_vol_60d mean = 0.15, F9.vrp mean = 0.0
        real_vol=RealVolSnapshot(
            realized_vol_60d=0.15,
            realized_vol_20d=0.13,
            vrp_60d=0.0,
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
        "market_dispersion":   0.30,
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
        "market_dispersion",
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


# ---------------------------- C9 post-C8 coverage tests ----------------------------


@patch.object(fe, "fetch_krw_usd_level", return_value=1250.0)
@patch.object(fe, "fetch_sp_trailing_pe", return_value=18.0)
def test_compute_all_factors_with_real_schema_after_c8(
    _pe: Any, _krw: Any, real_stage1_baseline: dict[str, Any]
) -> None:
    """C8 후 — 6 placeholder 활성화 후의 per-factor coverage 검증.

    Helper 가 6 신규 schema field (cfnai, spread_30y_5y_bps, kospi_pbr,
    realized_vol_60d/vrp_60d, sector_return_dispersion, skew change_1m_z) 를
    채우므로 모든 factor confidence 가 C1 보다 상승. krw=0.80 외 모두 ≥0.85.
    """
    scores = compute_all_factors(real_stage1_baseline)

    expected_min = {
        "growth_surprise":    0.85,
        "inflation_surprise": 0.85,
        "real_rate":          0.85,
        "term_premium":       0.85,
        "credit_cycle":       0.85,
        "krw_regime":         0.80,
        "equity_vol_regime":  0.85,
        "valuation":          0.85,
        "market_dispersion":   0.85,
    }
    for factor_name, min_cov in expected_min.items():
        score = getattr(scores, factor_name)
        assert score.confidence >= min_cov, (
            f"{factor_name} confidence {score.confidence:.2f} < {min_cov} "
            f"(components: {list(score.components.keys())})"
        )


@patch.object(fe, "fetch_krw_usd_level", return_value=1250.0)
@patch.object(fe, "fetch_sp_trailing_pe", return_value=18.0)
def test_cfnai_affects_growth_factor(
    _pe: Any, _krw: Any, real_stage1_baseline: dict[str, Any]
) -> None:
    """CFNAI = +1.5 perturbation → F1 z 증가 (C8 활성화 검증).

    cfnai (weight=0.10) + cfnai_3m (weight=0.08), baseline (0, sd=0.5) 이므로
    +1.5 → z=+3.0, +1.0 → z=+2.0. 가중합 contribution ≈ 0.10*3 + 0.08*2 = 0.46.
    """
    state = dict(real_stage1_baseline)
    baseline_scores = compute_all_factors(state)
    baseline_f1 = baseline_scores.growth_surprise.z_score

    macro = state["macro_report"]
    macro.financial_conditions.cfnai = +1.5
    macro.financial_conditions.cfnai_3m_avg = +1.0
    state["macro_report"] = macro

    new_scores = compute_all_factors(state)
    assert new_scores.growth_surprise.z_score > baseline_f1 + 0.05, (
        f"F1 should respond to CFNAI perturbation, "
        f"baseline {baseline_f1:.2f} → new {new_scores.growth_surprise.z_score:.2f}"
    )


@patch.object(fe, "fetch_krw_usd_level", return_value=1250.0)
@patch.object(fe, "fetch_sp_trailing_pe", return_value=18.0)
def test_realized_vol_affects_vol_and_liquidity(
    _pe: Any, _krw: Any, real_stage1_baseline: dict[str, Any]
) -> None:
    """High realized_vol → F7 + F9 (VRP) 영향 (C8 활성화 검증)."""
    state = dict(real_stage1_baseline)
    baseline_scores = compute_all_factors(state)

    risk = state["risk_report"]
    risk.real_vol.realized_vol_60d = 0.40   # very high realized vol
    risk.real_vol.vrp_60d = -800            # negative VRP (rare — realized > implied)
    state["risk_report"] = risk

    new_scores = compute_all_factors(state)
    # F7 should respond (high realized_vol → +z)
    assert new_scores.equity_vol_regime.z_score > baseline_scores.equity_vol_regime.z_score, (
        f"F7 should respond to high realized_vol, "
        f"baseline {baseline_scores.equity_vol_regime.z_score:.2f} → "
        f"new {new_scores.equity_vol_regime.z_score:.2f}"
    )
    # F9 VRP component should respond — sign convention 의존 — *값 자체 의 변화* 검증.
    assert (new_scores.market_dispersion.z_score
            != baseline_scores.market_dispersion.z_score), (
        f"F9 should respond to VRP change, "
        f"baseline={baseline_scores.market_dispersion.z_score:.2f} "
        f"new={new_scores.market_dispersion.z_score:.2f}"
    )


@patch.object(fe, "fetch_krw_usd_level", return_value=1250.0)
@patch.object(fe, "fetch_sp_trailing_pe", return_value=18.0)
def test_kospi_pbr_affects_valuation(
    _pe: Any, _krw: Any, real_stage1_baseline: dict[str, Any]
) -> None:
    """Low KOSPI PBR (deep value) perturbation → F8 z 변화 (C8 활성화 검증)."""
    state = dict(real_stage1_baseline)
    baseline_scores = compute_all_factors(state)

    macro = state["macro_report"]
    # KOSPI PBR 0.5 (extreme deep value) — sign convention 따라 영향
    macro.kr_valuation.kospi_pbr = 0.5
    state["macro_report"] = macro

    new_scores = compute_all_factors(state)
    # 값 변화 만 검증 (sign 은 design 의존)
    assert (
        new_scores.valuation.z_score != baseline_scores.valuation.z_score
    ), (
        f"F8 should respond to kospi_pbr perturbation, "
        f"baseline={baseline_scores.valuation.z_score:.2f} "
        f"new={new_scores.valuation.z_score:.2f}"
    )


@patch.object(fe, "fetch_krw_usd_level", return_value=1250.0)
@patch.object(fe, "fetch_sp_trailing_pe", return_value=18.0)
def test_sector_dispersion_affects_liquidity(
    _pe: Any, _krw: Any, real_stage1_baseline: dict[str, Any]
) -> None:
    """High sector dispersion (broad market) perturbation → F9 z 변화 (C8 활성화 검증)."""
    state = dict(real_stage1_baseline)
    baseline_scores = compute_all_factors(state)

    risk = state["risk_report"]
    risk.breadth_us.sector_return_dispersion = 0.20  # very wide spread
    state["risk_report"] = risk

    new_scores = compute_all_factors(state)
    assert (
        new_scores.market_dispersion.z_score != baseline_scores.market_dispersion.z_score
    ), (
        f"F9 should respond to sector_dispersion perturbation, "
        f"baseline={baseline_scores.market_dispersion.z_score:.2f} "
        f"new={new_scores.market_dispersion.z_score:.2f}"
    )


# ---------------------- Stage 1 audit (2026-05-26 Task 0/5) ----------------------


@patch.object(fe, "fetch_krw_usd_level", return_value=1250.0)
@patch.object(fe, "fetch_sp_trailing_pe", return_value=18.0)
def test_sentinel_snapshot_drops_components(
    _pe: Any, _krw: Any, real_stage1_baseline: dict[str, Any]
) -> None:
    """Stage 1 audit Task 0: fetch 실패 snapshot(staleness_days=99) 을 _safe_get 가
    드롭하는지 통합 검증. inflation snapshot 을 sentinel 로 강제 → F2 inflation_surprise
    의 components 에서 cpi/core_pce 가 누락되고 confidence 감소.
    """
    baseline_scores = compute_all_factors(real_stage1_baseline)
    baseline_inflation_components = set(baseline_scores.inflation_surprise.components.keys())
    baseline_conf = baseline_scores.inflation_surprise.confidence

    # inflation snapshot 을 sentinel(staleness=99)로 교체.
    state = dict(real_stage1_baseline)
    macro = state["macro_report"]
    macro.inflation = macro.inflation.model_copy(update={"staleness_days": 99})
    state["macro_report"] = macro

    new_scores = compute_all_factors(state)
    new_inflation_components = set(new_scores.inflation_surprise.components.keys())

    # inflation-derived components (cpi_yoy, momentum_3m, core_pce, breakeven_5y5y 등의
    # 일부)가 sentinel guard 로 drop됨. components set 감소 또는 confidence 감소 검증.
    assert new_scores.inflation_surprise.confidence < baseline_conf, (
        f"sentinel 적용 후 confidence 가 감소해야 함 "
        f"(baseline={baseline_conf:.3f}, new={new_scores.inflation_surprise.confidence:.3f})"
    )
    # 적어도 하나는 빠져야 함.
    assert new_inflation_components != baseline_inflation_components, (
        f"sentinel 적용 후 components set 이 변해야 함 "
        f"(baseline={baseline_inflation_components}, new={new_inflation_components})"
    )


def test_sentinel_guard_constant() -> None:
    """STALENESS_SENTINEL_DAYS=99 invariant — analysts 의 fetch-fail marker 와 일치."""
    assert fe.STALENESS_SENTINEL_DAYS == 99


# ---------------------- Stage 2 audit (2026-05-26 Task 5) ----------------------


@patch.object(fe, "fetch_krw_usd_level", return_value=1250.0)
@patch.object(fe, "fetch_sp_trailing_pe", return_value=18.0)
def test_multiple_sentinels_yield_low_conviction(
    _pe: Any, _krw: Any, real_stage1_baseline: dict[str, Any]
) -> None:
    """Stage 2 audit Task 5: Stage 1 의 여러 snapshot 동시 sentinel →
    factor confidence 동시 감소 → conviction 자동 하향 검증.

    여러 snapshot 을 강제 sentinel 화 했을 때 ResearchDecision 의 conviction 이
    여전히 "high" 면 위험 (가짜 신호로 high conviction 결정). low/medium 으로
    하향되거나 최소한 baseline conviction 과 같거나 낮아야 함.
    """
    from tradingagents.agents.managers.research_manager import (
        derive_conviction,
    )

    baseline_scores = compute_all_factors(real_stage1_baseline)
    baseline_conv = derive_conviction(baseline_scores)

    # 여러 snapshot 강제 sentinel: inflation, employment, fci (3개 동시).
    state = dict(real_stage1_baseline)
    macro = state["macro_report"]
    macro.inflation = macro.inflation.model_copy(update={"staleness_days": 99})
    macro.employment = macro.employment.model_copy(update={"staleness_days": 99})
    macro.financial_conditions = macro.financial_conditions.model_copy(
        update={"staleness_days": 99}
    )
    state["macro_report"] = macro

    degraded_scores = compute_all_factors(state)
    degraded_conv = derive_conviction(degraded_scores)

    # total_mag 가 감소 (3 sentinel → F1/F2 components 일부 drop → |z| 합 ↓)
    baseline_mag = sum(abs(z) for z in baseline_scores.to_dict().values())
    degraded_mag = sum(abs(z) for z in degraded_scores.to_dict().values())
    assert degraded_mag <= baseline_mag, (
        f"sentinel 추가 후 total |z| 감소 기대 "
        f"(baseline={baseline_mag:.3f}, degraded={degraded_mag:.3f})"
    )

    # conviction 은 동등 또는 하향 (절대 high 로 upgrade 되지 않음)
    rank = {"low": 0, "medium": 1, "high": 2}
    assert rank[degraded_conv] <= rank[baseline_conv], (
        f"sentinel 추가 후 conviction upgrade 발생 — 위험 "
        f"(baseline={baseline_conv}, degraded={degraded_conv})"
    )


@patch.object(fe, "fetch_krw_usd_level", return_value=1250.0)
@patch.object(fe, "fetch_sp_trailing_pe", return_value=18.0)
def test_scenario_threshold_no_hysteresis(
    _pe: Any, _krw: Any, real_stage1_baseline: dict[str, Any]
) -> None:
    """Stage 2 audit Task 5: derive_dominant_scenario 의 hysteresis 부재를 reproduce.

    F1 z-score 가 threshold 근처에서 미세하게 어느 쪽에 있는지에 따라 scenario 가
    jump 함을 통합 테스트로 입증. fix 는 본 audit 외 (별도 brainstorm).
    """
    from tradingagents.agents.managers.research_manager import (
        SCENARIO_CYCLE_THRESHOLD, derive_dominant_scenario,
    )
    from tradingagents.skills.research.factor_estimators import (
        FactorScore, FactorScores,
    )

    def _make_scores(f1: float, f2: float) -> FactorScores:
        """F1, F2 직접 설정. 나머지 0 (default goldilocks 영역)."""
        def _fs(name: str, z: float) -> FactorScore:
            return FactorScore(
                name=name, z_score=z, components={}, component_weights={},
                confidence=1.0, interpretation="",
            )
        return FactorScores(
            growth_surprise=_fs("F1_growth", f1),
            inflation_surprise=_fs("F2_inflation", f2),
            real_rate=_fs("F3_real_rate", 0.0),
            term_premium=_fs("F4_term_premium", 0.0),
            credit_cycle=_fs("F5_credit_cycle", 0.0),
            krw_regime=_fs("F6_krw_regime", 0.0),
            equity_vol_regime=_fs("F7_equity_vol_regime", 0.0),
            valuation=_fs("F8_valuation", 0.0),
            market_dispersion=_fs("F9_market_dispersion", 0.0),
        )

    # threshold = 0.5. 둘 다 0.49 → both-neutral goldilocks default;
    # 둘 다 0.51 → overheating. (단일 factor 만 decisive 하면 더 이상 goldilocks
    # 가 아니므로 — single-decisive 버그 fix — 양쪽 factor 를 함께 넘긴다.)
    just_below = _make_scores(f1=SCENARIO_CYCLE_THRESHOLD - 0.01,
                              f2=SCENARIO_CYCLE_THRESHOLD - 0.01)
    just_above = _make_scores(f1=SCENARIO_CYCLE_THRESHOLD + 0.01,
                              f2=SCENARIO_CYCLE_THRESHOLD + 0.01)
    s_below = derive_dominant_scenario(just_below)
    s_above = derive_dominant_scenario(just_above)
    # 0.02 차이로 scenario jump — hysteresis 없음 확인
    assert s_below != s_above, (
        f"hysteresis 없음 기대 (0.02 z 차이로 scenario jump). "
        f"below={s_below}, above={s_above}"
    )
    assert s_below == "goldilocks"          # default 영역
    assert s_above == "overheating"          # F1>0.5 AND F2>0.5


def test_stage2_named_constants_present() -> None:
    """Stage 2 audit Task 1: scenario/conviction threshold 가 const 화 됐는지."""
    from tradingagents.agents.managers import research_manager as rm
    assert hasattr(rm, "SCENARIO_CYCLE_THRESHOLD")
    assert hasattr(rm, "SCENARIO_KR_THRESHOLD")
    assert hasattr(rm, "SCENARIO_VOL_THRESHOLD")
    assert hasattr(rm, "SCENARIO_CREDIT_THRESHOLD")
    assert hasattr(rm, "CONVICTION_HIGH_MAG")
    assert hasattr(rm, "CONVICTION_MED_MAG")
    assert hasattr(rm, "CONVICTION_HIGH_ALIGN")
    assert hasattr(rm, "CONVICTION_MED_ALIGN")


def test_factor_to_bucket_cap_hits_diagnostic() -> None:
    """Stage 2 audit Task 2: extreme z 입력 시 cap_hits diagnostic 발동."""
    from tradingagents.skills.research.factor_to_bucket import (
        apply_factor_model_with_safety,
    )
    # extreme F1 = 5.0 → β·z 가 ±0.10 cap 에 닿을 가능성.
    extreme_z = {
        "F1_growth": 5.0, "F2_inflation": 0.0, "F3_real_rate": 0.0,
        "F4_term_premium": 0.0, "F5_credit_cycle": 0.0, "F6_krw_regime": 0.0,
        "F7_equity_vol_regime": 0.0, "F8_valuation": 0.0,
        "F9_market_dispersion": 0.0,
    }
    _bucket, _tips, _contribs, diag = apply_factor_model_with_safety(extreme_z)
    assert "cap_hits" in diag
    assert "cap_hits_detail" in diag
    assert diag["cap_hits"] >= 1, (
        f"extreme F1=5.0 에서 적어도 1 cap hit 기대 (cap_hits={diag['cap_hits']})"
    )
    assert diag["extreme_factor_active"] is True


# ---------- Backtest prep (2026-05-26) ----------


def test_scenario_hysteresis_prevents_jump_at_threshold():
    """Backtest prep #1: prior_scenario='overheating' (F1>0.5, F2>0.5) 일 때
    F1 = 0.46 (band 안) 으로 떨어져도 overheating 유지 검증.

    Stage 2 audit Task 5 의 test_scenario_threshold_no_hysteresis 와 짝.
    이전 test 는 hysteresis 부재 입증, 이번 test 는 hysteresis 정상 작동 입증.
    """
    from tradingagents.agents.managers.research_manager import (
        SCENARIO_CYCLE_THRESHOLD, SCENARIO_HYSTERESIS_BAND,
        derive_dominant_scenario,
    )
    from tradingagents.skills.research.factor_estimators import (
        FactorScore, FactorScores,
    )

    def _make_scores(f1: float, f2: float) -> FactorScores:
        def _fs(name: str, z: float) -> FactorScore:
            return FactorScore(
                name=name, z_score=z, components={}, component_weights={},
                confidence=1.0, interpretation="",
            )
        return FactorScores(
            growth_surprise=_fs("F1_growth", f1),
            inflation_surprise=_fs("F2_inflation", f2),
            real_rate=_fs("F3_real_rate", 0.0),
            term_premium=_fs("F4_term_premium", 0.0),
            credit_cycle=_fs("F5_credit_cycle", 0.0),
            krw_regime=_fs("F6_krw_regime", 0.0),
            equity_vol_regime=_fs("F7_equity_vol_regime", 0.0),
            valuation=_fs("F8_valuation", 0.0),
            market_dispersion=_fs("F9_market_dispersion", 0.0),
        )

    # threshold = 0.5, band = 0.05. 정상 entry: f1>0.5 AND f2>0.5 → overheating.
    # (f1, f2 를 lockstep 으로 움직여 — single-decisive fix 이후 한 factor 만
    # neutral 이면 더 이상 goldilocks default 가 아니므로.)
    just_below_entry = _make_scores(
        f1=SCENARIO_CYCLE_THRESHOLD - 0.04,   # 0.46 (band 안)
        f2=SCENARIO_CYCLE_THRESHOLD - 0.04,
    )

    # prior 없으면: 0.46 < 0.5 → goldilocks (both-neutral default)
    no_prior = derive_dominant_scenario(just_below_entry, prior_scenario=None)
    assert no_prior == "goldilocks"

    # prior=overheating 이면: hysteresis 발동 — relaxed threshold (0.45) 까지는
    # 유지. 0.46 > 0.45 → overheating 유지.
    with_prior = derive_dominant_scenario(
        just_below_entry, prior_scenario="overheating",
        hysteresis_band=SCENARIO_HYSTERESIS_BAND,
    )
    assert with_prior == "overheating", (
        f"hysteresis 발동 기대 (0.46 ∈ [0.45, 0.5] band), got {with_prior}"
    )

    # band 밖 (0.40) — hysteresis 도 잡지 못함 → overheating 탈출.
    way_below = _make_scores(
        f1=SCENARIO_CYCLE_THRESHOLD - 0.10,
        f2=SCENARIO_CYCLE_THRESHOLD - 0.10,
    )
    exited = derive_dominant_scenario(way_below, prior_scenario="overheating")
    assert exited == "goldilocks"


def test_scenario_hysteresis_allows_immediate_upgrade_to_urgent():
    """Backtest prep #1: prior=goldilocks 이고 F7+F5 가 globalcredit 진입 시
    hysteresis 무시 + 즉시 switch (더 urgent state 로는 항상 즉시 전환).
    """
    from tradingagents.agents.managers.research_manager import (
        derive_dominant_scenario,
    )
    from tradingagents.skills.research.factor_estimators import (
        FactorScore, FactorScores,
    )

    def _fs(name: str, z: float) -> FactorScore:
        return FactorScore(
            name=name, z_score=z, components={}, component_weights={},
            confidence=1.0, interpretation="",
        )
    scores = FactorScores(
        growth_surprise=_fs("F1_growth", 0.0),
        inflation_surprise=_fs("F2_inflation", 0.0),
        real_rate=_fs("F3_real_rate", 0.0),
        term_premium=_fs("F4_term_premium", 0.0),
        credit_cycle=_fs("F5_credit_cycle", 2.0),   # > 1.0
        krw_regime=_fs("F6_krw_regime", 0.0),
        equity_vol_regime=_fs("F7_equity_vol_regime", 2.0),  # > 1.5
        valuation=_fs("F8_valuation", 0.0),
        market_dispersion=_fs("F9_market_dispersion", 0.0),
    )
    out = derive_dominant_scenario(scores, prior_scenario="goldilocks")
    assert out == "global_credit", (
        "더 urgent state 로 전환은 hysteresis 무시 (즉시 switch) 기대"
    )
