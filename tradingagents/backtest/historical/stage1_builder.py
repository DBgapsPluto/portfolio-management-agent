"""Date-parameterized minimal-proxy Stage 1 builder.

PR1 C2 의 `_build_baseline_*_report()` 패턴 (tests/integration/
test_factor_estimators_real_schema.py) 의 date-parameterized 확장. 본 builder
는 quarterly indicator panel 의 한 row 를 받아 4 개 _AnalystReport pydantic
instance (MacroReport / RiskReport / TechnicalReport / NewsReport) 를 반환.

Strategy:
- Production schema 와 100% 일치하는 *self-contained baseline* 을 inline 으로
  구성 (test 파일의 _build_baseline_* 와 동일 구조 — 의도적 중복, tests→
  production 역의존성 회피).
- quarterly panel 의 column 값으로 baseline 의 일부 field 만 override
  (pydantic model_copy with update).
- News-derived field 는 영구 baseline (sentinel) — historical LLM 재현 불가.
  factor_estimators 가 mode="historical" 로 호출되면 news weight 가 자동 0 +
  quant weight renormalize → factor z magnitude 가 production scale 매치.
"""
from __future__ import annotations

import logging
from datetime import date
from typing import Any

import pandas as pd

from tradingagents.schemas.macro import (
    ChinaLeadingSnapshot, DivergenceScore, FXSnapshot, FedPathSnapshot,
    FinancialConditionsSnapshot, ForeignFlowSnapshot, GDPNowSnapshot,
    InflationExpectationsSnapshot, InflationSnapshot, KRBusinessSurveySnapshot,
    KRExportSnapshot, KRLeadingIndexSnapshot, KRValuationSnapshot,
    PolicyUncertaintySnapshot, RegimeClassification, RiskAppetiteSnapshot,
    TailRiskSnapshot, USLeadingIndexSnapshot, EmploymentSnapshot,
    YieldCurveSnapshot,
)
from tradingagents.schemas.news import (
    GlobalOvernightSnapshot, NewsSentimentSnapshot, OvernightMove,
    ReleaseSurpriseSnapshot, SpeakerToneAggregate,
)
from tradingagents.schemas.reports import (
    MacroReport, NewsReport, RiskReport, TechnicalReport,
)
from tradingagents.schemas.risk import (
    BreadthSnapshot, CreditQualitySnapshot, EquityBondCorrelationSnapshot,
    FundingStressSnapshot, KRCorpSpreadSnapshot, KRMarginDebtSnapshot,
    KRMarketTierSnapshot, KRYieldCurveSnapshot, PCASnapshot, RealVolSnapshot,
    RealYieldsSnapshot, SentimentSnapshot, SkewSnapshot, SpreadSnapshot,
    SystemicRiskScore, VIXTermStructureSnapshot, VolatilitySnapshot,
    VxnSnapshot,
)

logger = logging.getLogger(__name__)


def _g(row: dict, key: str, default: Any = 0.0) -> Any:
    """Safe get from indicator row; None or NaN → default."""
    val = row.get(key, default)
    if val is None:
        return default
    if isinstance(val, float) and pd.isna(val):
        return default
    return val


def _build_baseline_macro_report() -> MacroReport:
    """모든 required field 채움; factor estimator 가 *읽는* field 는
    LONG_RUN_BASELINE 의 mean 값 (z=0).
    """
    return MacroReport(
        narrative="historical baseline",
        summary_for_downstream="historical baseline macro",
        yield_curve=YieldCurveSnapshot(
            spread_10y_2y_bps=80.0, spread_10y_3m_bps=120.0,
            inverted_days_count=0, percentile_5y=0.5,
            spread_30y_5y_bps=80.0,
        ),
        inflation=InflationSnapshot(
            cpi_yoy=2.5, core_cpi_yoy=2.5,
            momentum_3mo=2.5, momentum_6mo=2.5, accelerating=False,
            pce_yoy=2.0, core_pce_yoy=2.0, pce_momentum_3mo=2.0,
        ),
        employment=EmploymentSnapshot(
            unemployment_rate=4.0, rate_change_3mo=0.0,
            sahm_rule_triggered=False, non_farm_payrolls_3mo_avg=150.0,
            job_openings_3mo_avg=8000.0, quits_rate=2.5, quits_rate_change_6mo=0.0,
        ),
        kr_divergence=DivergenceScore(
            us_kr_rate_gap_bps=-100.0, us_kr_inflation_gap=0.0, score=0.0,
        ),
        regime=RegimeClassification(
            quadrant="growth_disinflation", confidence=0.7,
            drivers=["historical baseline"], reasoning="historical reconstruction",
        ),
        upcoming_events=[],
        kr_export=KRExportSnapshot(
            yoy_pct=5.0, momentum_3mo_pct=5.0, momentum_6mo_pct=5.0,
            accelerating=False,
        ),
        kr_leading=KRLeadingIndexSnapshot(
            cli_value=100.0, change_3mo=0.0, change_6mo=0.0, phase="expansion",
        ),
        kr_business_survey=KRBusinessSurveySnapshot(
            mfg_bsi=90.0, change_3mo=0.0, contraction_signal=False,
        ),
        us_leading=USLeadingIndexSnapshot(
            cfnai_value=0.0, cfnai_ma3=0.0,
            recession_signal=False, recession_severity="none",
        ),
        gdp_nowcast=GDPNowSnapshot(nowcast_pct=2.0, change_from_prior=0.0),
        financial_conditions=FinancialConditionsSnapshot(
            nfci=0.0, anfci=0.0, regime="neutral", tightening=False,
            cfnai=0.0, cfnai_3m_avg=0.0,
        ),
        inflation_expectations=InflationExpectationsSnapshot(
            breakeven_5y5y=2.3, michigan_1y=3.0,
            anchored=True, unanchored_direction="none",
        ),
        fed_path=FedPathSnapshot(
            current_rate_pct=5.0, implied_2y_rate_pct=5.0,
            path_bps=0.0, market_view="hold",
        ),
        fx=FXSnapshot(
            usd_krw=1250.0, dxy=100.0,
            krw_change_1m_pct=0.0, dxy_change_1m_pct=0.0, regime="neutral",
        ),
        risk_appetite=RiskAppetiteSnapshot(
            copper_price=4.0, gold_price=2000.0, ratio=0.2,
            ratio_percentile_1y=0.5, signal="neutral",
        ),
        china_leading=ChinaLeadingSnapshot(
            cli_value=100.0, change_3mo=0.0, phase="expansion",
        ),
        foreign_flow=ForeignFlowSnapshot(
            net_5d_krw=0.0, net_20d_krw=0.0, signal="neutral",
        ),
        policy_uncertainty=PolicyUncertaintySnapshot(
            us_epu=120.0, global_epu=120.0,
            us_epu_percentile_5y=0.5, regime="normal",
        ),
        tail_risk=TailRiskSnapshot(
            vvix=90.0, move=90.0,
            vvix_percentile_1y=0.5, move_percentile_1y=0.5, signal="calm",
        ),
        kr_valuation=KRValuationSnapshot(
            kospi_pbr=1.0, kospi_per=12.0, kospi_div_yield=2.0,
        ),
    )


def _build_baseline_risk_report() -> RiskReport:
    """RiskReport baseline — VIX 20, hy_oas 400 bps, real_yields tips_10y 0.5 등."""
    return RiskReport(
        narrative="historical baseline",
        summary_for_downstream="historical baseline risk",
        vix=VolatilitySnapshot(
            index_name="VIX", current_value=20.0, zscore_30d=0.0,
            percentile_5y=0.5, change_4w=0.0,
        ),
        vkospi=VolatilitySnapshot(
            index_name="VKOSPI", current_value=20.0, zscore_30d=0.0,
            percentile_5y=0.5, change_4w=0.0,
        ),
        credit_spread_us_ig=SpreadSnapshot(
            region="US_IG", current_bps=120.0, percentile_5y=0.5,
            widening=False, momentum_zscore=0.0,
        ),
        credit_spread_us_hy=SpreadSnapshot(
            region="US_HY", current_bps=400.0, percentile_5y=0.5,
            widening=False, momentum_zscore=0.0,
        ),
        fear_greed=SentimentSnapshot(
            index_name="fear_greed_cnn", current_value=50,
            label="neutral", trend_7d="flat",
        ),
        breadth_kr=BreadthSnapshot(
            market="KOSPI200", advancing_pct=0.55, declining_pct=0.45,
            new_highs_minus_lows=0,
        ),
        breadth_us=BreadthSnapshot(
            market="SP500", advancing_pct=0.55, declining_pct=0.45,
            new_highs_minus_lows=0, sector_return_dispersion=0.05,
        ),
        correlation_concentration=PCASnapshot(
            first_eigenvalue_share=0.4, n_assets_analyzed=20,
            is_concentrated=False,
        ),
        systemic_score=SystemicRiskScore(
            score=5.0, regime="neutral",
            drivers=["historical baseline"], reasoning="historical reconstruction",
        ),
        vix_term=VIXTermStructureSnapshot(
            vix_front=20.0, vix_3m=20.0, ratio=1.0, regime="flat",
        ),
        skew=SkewSnapshot(
            skew_value=118.0, percentile_1y=0.5,
            tail_hedge_signal="normal", change_1m_z=0.0,
        ),
        vxn=VxnSnapshot(
            current_value=22.0, zscore_30d=0.0, percentile_5y=0.5,
            spread_vs_vix=2.0, tech_focused_stress=False,
        ),
        real_yields=RealYieldsSnapshot(
            tips_10y=0.5, tips_5y=0.3, spread_10y_5y=0.2, regime="neutral",
        ),
        funding_stress=FundingStressSnapshot(
            sofr=5.3, tbill_3m=5.2, spread_bps=10.0, regime="calm",
        ),
        credit_quality=CreditQualitySnapshot(
            aaa_oas_bps=60.0, bbb_oas_bps=150.0,
            quality_spread_bps=90.0, percentile_5y=0.5, regime="calm",
        ),
        kr_yield_curve=KRYieldCurveSnapshot(
            treasury_3y=3.5, treasury_10y=4.0,
            spread_10y_3y_bps=50.0, inverted=False, regime="flat",
        ),
        kr_corp_spread=KRCorpSpreadSnapshot(
            corp_yield_3y=4.5, treasury_3y=3.5, spread_bps=100.0,
            percentile_5y=0.5, regime="calm",
        ),
        kr_margin_debt=KRMarginDebtSnapshot(
            balance_krw=20e12, change_20d_pct=0.0,
            percentile_1y=0.5, signal="normal",
        ),
        kr_market_tier=KRMarketTierSnapshot(
            kospi_return_20d_pct=0.0, kosdaq_return_20d_pct=0.0,
            relative_perf_pct=0.0, signal="neutral",
        ),
        equity_bond_corr=EquityBondCorrelationSnapshot(
            correlation_60d=-0.2, change_3m=0.0, regime="normal_hedge",
        ),
        real_vol=RealVolSnapshot(
            realized_vol_60d=0.15, realized_vol_20d=0.13, vrp_60d=0.0,
        ),
    )


def _build_baseline_technical_report() -> TechnicalReport:
    """factor_estimators 는 technical_report 의 어떤 field 도 직접 읽지 않음 — empty OK."""
    return TechnicalReport(
        narrative="historical baseline",
        summary_for_downstream="historical baseline technical",
        asset_class_momentum={}, individual_etf_states={}, correlation_clusters=[],
    )


def _build_baseline_news_report() -> NewsReport:
    """NewsReport — release_surprise / news_sentiment / cb_speakers / global_overnight
    의 baseline value 채움 (factor estimator 호출 가능).
    """
    krw_move = OvernightMove(
        name="USDKRW", ticker="KRW=X", value=1250.0, prior=1250.0,
        change_abs=0.0, change_pct=0.0, direction="flat",
    )
    return NewsReport(
        narrative="historical baseline",
        summary_for_downstream="historical baseline news",
        upcoming_events=[], ranked_news=[],
        global_overnight=GlobalOvernightSnapshot(
            europe={}, asia={}, commodities={}, krw=krw_move,
            risk_regime_overnight="mixed", narrative_seed="historical",
            fetched_count=1,
        ),
        release_surprise=ReleaseSurpriseSnapshot(
            today_releases=[], last_5d_releases=[],
            surprise_index_30d=0.0, high_importance_today=2, bias_30d="balanced",
        ),
        news_sentiment=NewsSentimentSnapshot(
            counts={},
            avg_sentiment={"macro": 0.0, "corporate": 0.0, "geopolitical": 0.0,
                           "policy": 0.0, "market_commentary": 0.0},
            dominant_category=None, sentiment_dispersion=0.3,
            top_headline_per_category={},
            count_change_vs_7d={"corporate": 0.0, "geopolitical": 0.0,
                                "policy": 0.0, "macro": 0.0,
                                "market_commentary": 0.0},
            rising_category=None,
        ),
        cb_speakers=SpeakerToneAggregate(
            fed_speakers_7d=[], bok_speakers_7d=[], other_speakers_7d=[],
            fed_tone_balance=0.0, bok_tone_balance=0.0, fed_voting_balance=0.0,
        ),
    )


def build_historical_stage1(
    as_of: date,
    indicators_q: pd.DataFrame,
) -> dict:
    """Build 4 _AnalystReport pydantic instances for one quarter, from quarterly panel.

    Args:
        as_of: quarter-end date (e.g., 2010-03-31).
        indicators_q: quarterly panel from aggregate.assemble_quarterly_panel.

    Returns:
        dict {macro_report, risk_report, technical_report, news_report}.
    """
    ts = pd.Timestamp(as_of)
    if ts not in indicators_q.index:
        raise KeyError(f"Quarter {as_of} not in indicators_q")
    row = indicators_q.loc[ts].to_dict()

    macro = _build_baseline_macro_report()
    risk = _build_baseline_risk_report()
    technical = _build_baseline_technical_report()
    news = _build_baseline_news_report()

    # ---------- MacroReport overrides from panel ----------
    macro = macro.model_copy(update={
        "yield_curve": macro.yield_curve.model_copy(update={
            "spread_10y_2y_bps": float(_g(row, "spread_10y_2y_bps", 80.0)),
            "spread_30y_5y_bps": float(_g(row, "spread_30y_5y_bps", 80.0)),
        }),
        "inflation": macro.inflation.model_copy(update={
            "cpi_yoy": float(_g(row, "cpi_yoy", 2.5)),
            "core_cpi_yoy": float(_g(row, "core_cpi_yoy", 2.5)),
            "momentum_3mo": float(_g(row, "cpi_3mo_ann", 2.5)),
            "pce_yoy": float(_g(row, "pce_yoy", 2.0)),
            "core_pce_yoy": float(_g(row, "core_pce_yoy", 2.0)),
            "pce_momentum_3mo": float(_g(row, "core_pce_yoy", 2.0)),
        }),
        "employment": macro.employment.model_copy(update={
            "unemployment_rate": float(_g(row, "unrate", 4.0)),
            "sahm_rule_triggered": bool(_g(row, "sahm_rule_triggered", 0.0) > 0.5),
        }),
        "financial_conditions": macro.financial_conditions.model_copy(update={
            "nfci": float(_g(row, "nfci", 0.0)),
            "anfci": float(_g(row, "anfci", 0.0)),
            "cfnai": float(_g(row, "cfnai", 0.0)),
            "cfnai_3m_avg": float(_g(row, "cfnai_3m_avg", 0.0)),
        }),
        "gdp_nowcast": macro.gdp_nowcast.model_copy(update={
            "nowcast_pct": float(_g(row, "gdp_nowcast", 2.0)),
        }),
        "inflation_expectations": macro.inflation_expectations.model_copy(update={
            "breakeven_5y5y": float(_g(row, "breakeven_5y5y", 2.3)),
            "michigan_1y": float(_g(row, "michigan_1y", 3.0)),
        }),
        "fed_path": macro.fed_path.model_copy(update={
            "current_rate_pct": float(_g(row, "tb3ms_pct", 5.0)),
            "implied_2y_rate_pct": float(_g(row, "dgs2_pct", 5.0)),
        }),
        "fx": macro.fx.model_copy(update={
            "usd_krw": float(_g(row, "usdkrw", 1250.0)),
            "dxy": float(_g(row, "dxy_dtwexm", 100.0)),
        }),
        "foreign_flow": macro.foreign_flow.model_copy(update={
            "net_20d_krw": float(_g(row, "foreign_flow_z", 0.0)),
        }),
    })

    # kr_valuation override if panel has KOSPI200 valuation
    pbr = _g(row, "kospi200_pbr", None)
    if pbr is not None and not (isinstance(pbr, float) and pd.isna(pbr)) and pbr > 0:
        macro = macro.model_copy(update={
            "kr_valuation": KRValuationSnapshot(
                kospi_pbr=float(_g(row, "kospi200_pbr", 1.0)),
                kospi_per=float(_g(row, "kospi200_per", 12.0)),
                kospi_div_yield=float(_g(row, "kospi200_div_yield", 2.0)),
            ),
        })

    # ---------- RiskReport overrides ----------
    risk = risk.model_copy(update={
        "vix": risk.vix.model_copy(update={
            "current_value": float(_g(row, "vix", 20.0)),
        }),
        "credit_spread_us_hy": risk.credit_spread_us_hy.model_copy(update={
            "current_bps": float(_g(row, "baa_10y_bps", 400.0)),
        }),
        "credit_spread_us_ig": risk.credit_spread_us_ig.model_copy(update={
            "current_bps": float(_g(row, "baa_aaa_bps", 120.0)),
        }),
        "skew": risk.skew.model_copy(update={
            "skew_value": float(_g(row, "skew", 118.0)),
        }),
        "real_yields": risk.real_yields.model_copy(update={
            "tips_10y": float(_g(row, "real_yield_10y_pct", 0.5)),
        }),
        "breadth_us": risk.breadth_us.model_copy(update={
            "sector_return_dispersion": float(_g(row, "sector_dispersion", 0.05)),
        }),
        "real_vol": risk.real_vol.model_copy(update={
            "realized_vol_60d": float(_g(row, "realized_vol_60d_spx_pct", 15.0)) / 100.0,
            "vrp_60d": float(_g(row, "vrp_pct", 0.0)),
        }) if risk.real_vol else None,
    })

    return {
        "macro_report": macro,
        "risk_report": risk,
        "technical_report": technical,
        "news_report": news,
    }
