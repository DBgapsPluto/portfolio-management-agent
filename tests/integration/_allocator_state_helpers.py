"""Allocator state mocking helpers (Phase 2b followup).

allocator node 가 read 하는 state dict 합성. 외부 의존성 없이
풀 파이프라인 통합 테스트 enable.
"""
from __future__ import annotations

import math
from datetime import date

import numpy as np
import pandas as pd

from tradingagents.dataflows.universe import ETFEntry, Universe
from tradingagents.schemas.portfolio import BucketTarget
from tradingagents.skills.portfolio.factor_scorer import FactorPanel


BUCKET_CATEGORIES: dict[str, tuple[str, str, str | None]] = {
    "kr_equity":     ("국내주식_지수",         "위험", None),
    "global_equity": ("해외주식_지수",         "위험", None),
    "fx_commodity":  ("FX 및 원자재",          "위험", "gold"),
    "bond":          ("국내채권_종합",         "안전", "nominal"),
    "cash_mmf":      ("금리연계형/초단기채권", "안전", None),
}


def make_synthetic_universe(
    n_per_bucket: int = 4,
    base_aum: float = 50_000_000_000,
) -> Universe:
    """5 bucket × n_per_bucket ETFs."""
    etfs: list[ETFEntry] = []
    for bucket_name, (category, risk, sub_cat) in BUCKET_CATEGORIES.items():
        prefix = bucket_name[:2].upper()
        for i in range(n_per_bucket):
            etfs.append(ETFEntry(
                ticker=f"A_{prefix}{i:02d}",
                name=f"{bucket_name}_{i}",
                aum_krw=base_aum * (i + 1),
                underlying_index=f"{prefix}_idx_{i}",
                bucket=risk,
                category=category,
                sub_category=sub_cat,
            ))
    return Universe(version="test", etfs=etfs)


def make_synthetic_returns(
    tickers: list[str],
    n_days: int = 252,
    vol: float = 0.02,
    seed: int = 42,
) -> pd.DataFrame:
    """일별 returns DataFrame (uncorrelated)."""
    rng = np.random.default_rng(seed)
    data = rng.normal(0.0, vol, size=(n_days, len(tickers)))
    return pd.DataFrame(data, columns=tickers)


def make_factor_panel(
    tickers: list[str],
    aum_by_ticker: dict[str, float] | None = None,
    alpha_overrides: dict[str, float] | None = None,
) -> dict[str, FactorPanel]:
    """FactorPanel dict. alpha 는 skip1m mom 으로 표현.

    rank_normalize 가 동일 값에서 0 을 반환하는 특성 때문에, override 가 없는 ticker
    는 소폭 다른 alpha (base + i * 0.001) 를 부여해 정렬 구별을 보장한다.
    """
    aum_by_ticker = aum_by_ticker or {}
    alpha_overrides = alpha_overrides or {}
    panels: dict[str, FactorPanel] = {}
    base_alpha = 0.05
    for i, t in enumerate(tickers):
        aum = aum_by_ticker.get(t, 50_000_000_000)
        # override 없는 경우 소폭 차이를 둬 rank_normalize 가 0 을 반환하지 않게 함
        alpha = alpha_overrides.get(t, base_alpha + i * 0.001)
        panels[t] = FactorPanel(
            skip1m_mom_3m=alpha,
            skip1m_mom_6m=alpha,
            skip1m_mom_12m=alpha,
            realized_vol_60d=0.10,
            sharpe_60d=0.5 + i * 0.01,
            log_aum=math.log(aum),
        )
    return panels


def make_bucket_target(
    *,
    kr_equity: float = 0.20,
    global_equity: float = 0.20,
    fx_commodity: float = 0.15,
    bond: float = 0.30,
    cash_mmf: float = 0.15,
    bond_tips_share: float = 0.0,
    rationale: str = "test",
) -> BucketTarget:
    """합 검증된 BucketTarget."""
    total = kr_equity + global_equity + fx_commodity + bond + cash_mmf
    assert abs(total - 1.0) < 1e-9, f"bucket weights sum {total} != 1.0"
    return BucketTarget(
        kr_equity=kr_equity, global_equity=global_equity,
        fx_commodity=fx_commodity, bond=bond, cash_mmf=cash_mmf,
        bond_tips_share=bond_tips_share, rationale=rationale,
    )


def make_research_decision(
    *,
    conviction: str = "medium",
    dominant_scenario: str = "goldilocks",
    factor_scores: dict[str, float] | None = None,
    bucket_target: BucketTarget | None = None,
):
    """ResearchDecision mock."""
    from tradingagents.schemas.research import ResearchDecision
    bt = bucket_target or make_bucket_target()
    return ResearchDecision(
        bucket_target=bt,
        conviction=conviction,
        dominant_scenario=dominant_scenario,
        factor_scores=factor_scores or {},
        factor_contributions={},
        baseline_bucket={},
        safety_diagnostics={},
    )


def make_macro_report(
    *,
    regime_quadrant: str = "growth_disinflation",
    regime_confidence: float = 0.6,
    staleness_days: int = 1,
):
    """MacroReport with RegimeClassification."""
    from tradingagents.schemas.reports import MacroReport
    from tradingagents.schemas.macro import (
        YieldCurveSnapshot, InflationSnapshot, EmploymentSnapshot,
        DivergenceScore, RegimeClassification, KRExportSnapshot,
        KRLeadingIndexSnapshot, KRBusinessSurveySnapshot, USLeadingIndexSnapshot,
        GDPNowSnapshot, FinancialConditionsSnapshot, InflationExpectationsSnapshot,
        FedPathSnapshot, FXSnapshot, RiskAppetiteSnapshot, ChinaLeadingSnapshot,
        ForeignFlowSnapshot, PolicyUncertaintySnapshot, TailRiskSnapshot,
    )
    sd = staleness_days
    return MacroReport(
        narrative="test macro narrative",
        summary_for_downstream="test macro summary",
        yield_curve=YieldCurveSnapshot(
            spread_10y_2y_bps=50.0, spread_10y_3m_bps=30.0,
            inverted_days_count=0, percentile_5y=0.5, staleness_days=sd,
        ),
        inflation=InflationSnapshot(
            cpi_yoy=2.5, core_cpi_yoy=2.3, momentum_3mo=2.4, momentum_6mo=2.3,
            accelerating=False, staleness_days=sd,
        ),
        employment=EmploymentSnapshot(
            unemployment_rate=4.0, rate_change_3mo=0.0, sahm_rule_triggered=False,
            non_farm_payrolls_3mo_avg=200.0, staleness_days=sd,
        ),
        kr_divergence=DivergenceScore(
            us_kr_rate_gap_bps=150.0, us_kr_inflation_gap=0.5, score=2.0,
            staleness_days=sd,
        ),
        regime=RegimeClassification(
            quadrant=regime_quadrant,
            confidence=regime_confidence,
            drivers=["growth"],
            reasoning="test",
            staleness_days=sd,
        ),
        upcoming_events=[],
        kr_export=KRExportSnapshot(
            yoy_pct=5.0, momentum_3mo_pct=4.0, momentum_6mo_pct=3.0,
            accelerating=True, staleness_days=sd,
        ),
        kr_leading=KRLeadingIndexSnapshot(
            cli_value=101.0, change_3mo=0.5, change_6mo=1.0,
            phase="expansion", staleness_days=sd,
        ),
        kr_business_survey=KRBusinessSurveySnapshot(
            mfg_bsi=90.0, change_3mo=2.0, contraction_signal=False,
            staleness_days=sd,
        ),
        us_leading=USLeadingIndexSnapshot(
            cfnai_value=0.1, cfnai_ma3=0.05, recession_signal=False,
            staleness_days=sd,
        ),
        gdp_nowcast=GDPNowSnapshot(
            nowcast_pct=2.5, change_from_prior=0.1, staleness_days=sd,
        ),
        financial_conditions=FinancialConditionsSnapshot(
            nfci=-0.2, anfci=-0.1, regime="neutral", tightening=False,
            staleness_days=sd,
        ),
        inflation_expectations=InflationExpectationsSnapshot(
            breakeven_5y5y=2.3, michigan_1y=3.0, anchored=True,
            unanchored_direction="none", staleness_days=sd,
        ),
        fed_path=FedPathSnapshot(
            current_rate_pct=5.25, implied_2y_rate_pct=4.80,
            path_bps=-45.0, market_view="hold", staleness_days=sd,
        ),
        fx=FXSnapshot(
            usd_krw=1330.0, dxy=104.0, krw_change_1m_pct=0.5,
            dxy_change_1m_pct=0.3, regime="neutral", staleness_days=sd,
        ),
        risk_appetite=RiskAppetiteSnapshot(
            copper_price=4.0, gold_price=2000.0, ratio=0.20,
            ratio_percentile_5y=0.55, signal="neutral", staleness_days=sd,
        ),
        china_leading=ChinaLeadingSnapshot(
            cli_value=100.5, change_3mo=0.3, phase="expansion",
            staleness_days=sd,
        ),
        foreign_flow=ForeignFlowSnapshot(
            net_5d_krw=200_000_000_000, net_20d_krw=500_000_000_000,
            signal="net_buying", staleness_days=sd,
        ),
        policy_uncertainty=PolicyUncertaintySnapshot(
            us_epu=120.0, global_epu=130.0, us_epu_percentile_5y=0.4,
            regime="normal", staleness_days=sd,
        ),
        tail_risk=TailRiskSnapshot(
            vvix=90.0, move=80.0, vvix_percentile_1y=0.3,
            move_percentile_1y=0.25, signal="calm", staleness_days=sd,
        ),
    )


def make_risk_report(
    *,
    systemic_score: float = 5.0,
    systemic_regime: str = "neutral",
    staleness_days: int = 1,
):
    """RiskReport with SystemicRiskScore."""
    from tradingagents.schemas.reports import RiskReport
    from tradingagents.schemas.risk import (
        VolatilitySnapshot, SpreadSnapshot, SentimentSnapshot,
        BreadthSnapshot, PCASnapshot, SystemicRiskScore, VIXTermStructureSnapshot,
        SkewSnapshot, VxnSnapshot, RealYieldsSnapshot, FundingStressSnapshot,
        CreditQualitySnapshot, KRYieldCurveSnapshot, KRCorpSpreadSnapshot,
        KRMarginDebtSnapshot, KRMarketTierSnapshot, EquityBondCorrelationSnapshot,
    )
    sd = staleness_days
    return RiskReport(
        narrative="test risk narrative",
        summary_for_downstream="test risk summary",
        vix=VolatilitySnapshot(
            index_name="VIX", current_value=15.0, zscore_30d=-0.5,
            percentile_5y=0.3, staleness_days=sd,
        ),
        vkospi=VolatilitySnapshot(
            index_name="VKOSPI", current_value=18.0, zscore_30d=-0.3,
            percentile_5y=0.35, staleness_days=sd,
        ),
        credit_spread_us_ig=SpreadSnapshot(
            region="US_IG", current_bps=90.0, percentile_5y=0.35,
            widening=False, staleness_days=sd,
        ),
        credit_spread_us_hy=SpreadSnapshot(
            region="US_HY", current_bps=350.0, percentile_5y=0.30,
            widening=False, staleness_days=sd,
        ),
        fear_greed=SentimentSnapshot(
            index_name="fear_greed_cnn", current_value=55, label="neutral",
            trend_7d="flat", staleness_days=sd,
        ),
        breadth_kr=BreadthSnapshot(
            market="KOSPI200", advancing_pct=0.55, declining_pct=0.40,
            new_highs_minus_lows=20, staleness_days=sd,
        ),
        breadth_us=BreadthSnapshot(
            market="SP500", advancing_pct=0.60, declining_pct=0.35,
            new_highs_minus_lows=50, staleness_days=sd,
        ),
        correlation_concentration=PCASnapshot(
            first_eigenvalue_share=0.45, n_assets_analyzed=20,
            is_concentrated=False, staleness_days=sd,
        ),
        systemic_score=SystemicRiskScore(
            score=systemic_score, regime=systemic_regime,
            drivers=["test"], reasoning="test", staleness_days=sd,
        ),
        vix_term=VIXTermStructureSnapshot(
            vix_front=15.0, vix_3m=16.0, ratio=1.07,
            regime="contango", staleness_days=sd,
        ),
        skew=SkewSnapshot(
            skew_value=125.0, percentile_1y=0.5,
            tail_hedge_signal="normal", staleness_days=sd,
        ),
        vxn=VxnSnapshot(
            current_value=18.0, zscore_30d=-0.2, percentile_5y=0.35,
            spread_vs_vix=3.0, staleness_days=sd,
        ),
        real_yields=RealYieldsSnapshot(
            tips_10y=1.8, tips_5y=1.5, spread_10y_5y=0.3,
            regime="tight", staleness_days=sd,
        ),
        funding_stress=FundingStressSnapshot(
            sofr=5.30, tbill_3m=5.25, spread_bps=5.0,
            regime="calm", staleness_days=sd,
        ),
        credit_quality=CreditQualitySnapshot(
            aaa_oas_bps=60.0, bbb_oas_bps=150.0, quality_spread_bps=90.0,
            percentile_5y=0.40, regime="calm", staleness_days=sd,
        ),
        kr_yield_curve=KRYieldCurveSnapshot(
            treasury_3y=3.5, treasury_10y=3.8, spread_10y_3y_bps=30.0,
            inverted=False, regime="normal", staleness_days=sd,
        ),
        kr_corp_spread=KRCorpSpreadSnapshot(
            corp_yield_3y=4.0, treasury_3y=3.5, spread_bps=50.0,
            percentile_5y=0.35, regime="calm", staleness_days=sd,
        ),
        kr_margin_debt=KRMarginDebtSnapshot(
            balance_krw=20_000_000_000_000, change_20d_pct=2.0,
            percentile_1y=0.45, signal="normal", staleness_days=sd,
        ),
        kr_market_tier=KRMarketTierSnapshot(
            kospi_return_20d_pct=1.5, kosdaq_return_20d_pct=2.0,
            relative_perf_pct=0.5, signal="neutral", staleness_days=sd,
        ),
        equity_bond_corr=EquityBondCorrelationSnapshot(
            correlation_120d=-0.2, change_3m=0.05,
            regime="normal_hedge", staleness_days=sd,
        ),
    )


def make_technical_report(
    factor_panel: dict[str, FactorPanel],
    *,
    correlation_clusters: list | None = None,
):
    """TechnicalReport with factor_panel."""
    from tradingagents.schemas.reports import TechnicalReport
    return TechnicalReport(
        narrative="test technical narrative",
        summary_for_downstream="test technical summary",
        asset_class_momentum={},
        individual_etf_states={},
        correlation_clusters=correlation_clusters or [],
        factor_panel=factor_panel,
        extended_indicators={},
        trend_quantification={},
        risk_adjusted={},
    )


def make_allocator_state(
    *,
    as_of: date,
    universe_path: str,
    bucket_target: BucketTarget,
    technical_report,
    macro_report,
    risk_report,
    research_decision,
    capital_krw: float = 1_000_000_000,
    allocation_feedback: list | None = None,
    allocation_attempts: int = 0,
) -> dict:
    """allocator node 가 read 하는 state dict."""
    return {
        "as_of_date": as_of.isoformat(),
        "universe_path": str(universe_path),
        "bucket_target": bucket_target,
        "technical_report": technical_report,
        "macro_report": macro_report,
        "risk_report": risk_report,
        "research_decision": research_decision,
        "capital_krw": capital_krw,
        "allocation_feedback": allocation_feedback or [],
        "allocation_attempts": allocation_attempts,
    }
