"""Market Risk Analyst — orchestrates 10 risk skills, composes RiskReport.

Tier-1 확장 (equity stress 깊이):
- vix_term_structure: VXVCLS vs VIXCLS (contango/backwardation)
- skew_index: CBOE ^SKEW (외가격 풋 헷지 수요)
- vxn: CBOE VXNCLS (NASDAQ-100 vol, 기술주 편중)
- breadth real: pykrx KOSPI200 + SP500 11 섹터 ETF proxy (stub 교체)
- volatility 강화: change_4w 추가
"""
from datetime import date, timedelta

import pandas as pd

from tradingagents.dataflows.equity_indices import fetch_equity_index_close
from tradingagents.dataflows.pykrx_data import fetch_credit_balance, fetch_market_index
from tradingagents.schemas.reports import RiskReport
from tradingagents.schemas.risk import (
    CreditQualitySnapshot, FundingStressSnapshot,
    KRCorpSpreadSnapshot, KRMarginDebtSnapshot, KRMarketTierSnapshot,
    KRYieldCurveSnapshot, RealYieldsSnapshot,
    SentimentSnapshot, SkewSnapshot, VIXTermStructureSnapshot, VxnSnapshot,
)
from tradingagents.skills.macro.ecos_fetcher import fetch_ecos_series_skill
from tradingagents.skills.macro.fred_fetcher import fetch_fred_series_skill
from tradingagents.skills.risk.breadth import compute_market_breadth
from tradingagents.skills.risk.correlation_pca import compute_correlation_concentration
from tradingagents.skills.risk.credit_quality import compute_credit_quality
from tradingagents.skills.risk.credit_spread import fetch_credit_spread
from tradingagents.skills.risk.fear_greed import fetch_fear_greed_index
from tradingagents.skills.risk.funding_stress import compute_funding_stress
from tradingagents.skills.risk.kr_corp_spread import compute_kr_corp_spread
from tradingagents.skills.risk.kr_margin_debt import compute_kr_margin_debt
from tradingagents.skills.risk.kr_market_tier import compute_kr_market_tier
from tradingagents.skills.risk.kr_yield_curve import compute_kr_yield_curve
from tradingagents.skills.risk.real_yields import compute_real_yields
from tradingagents.skills.risk.skew_index import compute_skew_index
from tradingagents.skills.risk.systemic_score import score_systemic_risk
from tradingagents.skills.risk.vix_term_structure import compute_vix_term_structure
from tradingagents.skills.risk.volatility import fetch_volatility_index
from tradingagents.skills.risk.vxn import compute_vxn


def _sentinel_vix_term(as_of: date) -> VIXTermStructureSnapshot:
    return VIXTermStructureSnapshot(
        vix_front=0.0, vix_3m=0.0, ratio=1.0, regime="flat",
        source_date=as_of, staleness_days=99,
    )


def _sentinel_skew(as_of: date) -> SkewSnapshot:
    return SkewSnapshot(
        skew_value=118.0, percentile_1y=0.5, tail_hedge_signal="normal",
        source_date=as_of, staleness_days=99,
    )


def _sentinel_vxn(as_of: date) -> VxnSnapshot:
    return VxnSnapshot(
        current_value=0.0, zscore_30d=0.0, percentile_5y=0.5, spread_vs_vix=0.0,
        source_date=as_of, staleness_days=99,
    )


def _sentinel_real_yields(as_of: date) -> RealYieldsSnapshot:
    return RealYieldsSnapshot(
        tips_10y=0.0, tips_5y=0.0, spread_10y_5y=0.0, regime="neutral",
        source_date=as_of, staleness_days=99,
    )


def _sentinel_funding(as_of: date) -> FundingStressSnapshot:
    return FundingStressSnapshot(
        sofr=0.0, tbill_3m=0.0, spread_bps=0.0, regime="calm",
        source_date=as_of, staleness_days=99,
    )


def _sentinel_credit_quality(as_of: date) -> CreditQualitySnapshot:
    return CreditQualitySnapshot(
        aaa_oas_bps=0.0, bbb_oas_bps=0.0, quality_spread_bps=0.0,
        percentile_5y=0.5, regime="calm",
        source_date=as_of, staleness_days=99,
    )


def _sentinel_kr_yield_curve(as_of: date) -> KRYieldCurveSnapshot:
    return KRYieldCurveSnapshot(
        treasury_3y=0.0, treasury_10y=0.0, spread_10y_3y_bps=0.0,
        inverted=False, regime="flat",
        source_date=as_of, staleness_days=99,
    )


def _sentinel_kr_corp_spread(as_of: date) -> KRCorpSpreadSnapshot:
    return KRCorpSpreadSnapshot(
        corp_yield_3y=0.0, treasury_3y=0.0, spread_bps=0.0,
        percentile_5y=0.5, regime="calm",
        source_date=as_of, staleness_days=99,
    )


def _sentinel_kr_margin(as_of: date) -> KRMarginDebtSnapshot:
    return KRMarginDebtSnapshot(
        balance_krw=0.0, change_20d_pct=0.0, percentile_1y=0.5, signal="normal",
        source_date=as_of, staleness_days=99,
    )


def _sentinel_kr_tier(as_of: date) -> KRMarketTierSnapshot:
    return KRMarketTierSnapshot(
        kospi_return_20d_pct=0.0, kosdaq_return_20d_pct=0.0,
        relative_perf_pct=0.0, signal="neutral",
        source_date=as_of, staleness_days=99,
    )


def create_market_risk_analyst(quick_llm, deep_llm):
    def node(state):
        as_of = date.fromisoformat(state["as_of_date"])
        start_vol = as_of - timedelta(days=400)
        start_5y = as_of - timedelta(days=365 * 5 + 30)

        vix = fetch_volatility_index("VIX", as_of)
        vkospi = fetch_volatility_index("VKOSPI", as_of)
        ig = fetch_credit_spread("US_IG", as_of)
        hy = fetch_credit_spread("US_HY", as_of)
        fg = fetch_fear_greed_index(as_of)  # may be None
        breadth_kr = compute_market_breadth("KOSPI200", as_of)
        breadth_us = compute_market_breadth("SP500", as_of)

        # Correlation concentration via PCA (synthetic asset class returns for v1)
        synthetic = pd.DataFrame({
            "kospi": [0.001, -0.002, 0.003, -0.001, 0.002] * 50,
            "spy": [0.002, -0.001, 0.002, 0.0, 0.001] * 50,
            "tlt": [-0.001, 0.001, -0.002, 0.001, 0.0] * 50,
            "gld": [0.0, 0.001, 0.0, -0.001, 0.001] * 50,
        })
        pca = compute_correlation_concentration(synthetic, as_of)

        # Skip-with-note for fear_greed (D5 tier3)
        if fg is None:
            fg = SentimentSnapshot(
                index_name="fear_greed_cnn", current_value=50,
                label="neutral", trend_7d="flat", source_date=as_of,
                staleness_days=99,
            )

        # Tier-1: VIX term structure (FRED VXVCLS vs VIXCLS)
        try:
            vix_front_series = fetch_fred_series_skill(
                "vix_close", start_vol, as_of, as_of_date=as_of,
            )
            vix_3m_series = fetch_fred_series_skill(
                "vix_3m", start_vol, as_of, as_of_date=as_of,
            )
            vix_term = compute_vix_term_structure(
                vix_front_series.dropna(), vix_3m_series.dropna(), as_of=as_of,
            )
        except Exception:
            vix_term = _sentinel_vix_term(as_of)

        # Tier-1: SKEW (yfinance ^SKEW)
        try:
            skew_series = fetch_equity_index_close("skew", as_of - timedelta(days=400), as_of)
            skew = compute_skew_index(skew_series, as_of=as_of)
        except Exception:
            skew = _sentinel_skew(as_of)

        # Tier-1: VXN (FRED VXNCLS)
        try:
            vxn_series = fetch_fred_series_skill("vxn", start_5y, as_of, as_of_date=as_of)
            vix_series_for_spread = fetch_fred_series_skill(
                "vix_close", start_5y, as_of, as_of_date=as_of,
            )
            vxn = compute_vxn(vxn_series.dropna(), vix_series_for_spread.dropna(), as_of=as_of)
        except Exception:
            vxn = _sentinel_vxn(as_of)

        # Tier-2: TIPS 실질금리 (DFII10, DFII5)
        try:
            tips_10 = fetch_fred_series_skill(
                "us_tips_10y", start_5y, as_of, as_of_date=as_of,
            ).dropna()
            tips_5 = fetch_fred_series_skill(
                "us_tips_5y", start_5y, as_of, as_of_date=as_of,
            ).dropna()
            real_yields = compute_real_yields(tips_10, tips_5, as_of=as_of)
        except Exception:
            real_yields = _sentinel_real_yields(as_of)

        # Tier-2: Funding stress (SOFR vs 3m T-bill)
        try:
            sofr = fetch_fred_series_skill(
                "us_sofr", start_5y, as_of, as_of_date=as_of,
            ).dropna()
            tbill = fetch_fred_series_skill(
                "us_3m_tbill", start_5y, as_of, as_of_date=as_of,
            ).dropna()
            funding_stress = compute_funding_stress(sofr, tbill, as_of=as_of)
        except Exception:
            funding_stress = _sentinel_funding(as_of)

        # Tier-2: Credit quality (AAA vs BBB)
        try:
            aaa = fetch_fred_series_skill(
                "us_aaa_oas", start_5y, as_of, as_of_date=as_of,
            ).dropna()
            bbb = fetch_fred_series_skill(
                "us_bbb_oas", start_5y, as_of, as_of_date=as_of,
            ).dropna()
            credit_quality = compute_credit_quality(aaa, bbb, as_of=as_of)
        except Exception:
            credit_quality = _sentinel_credit_quality(as_of)

        # Tier-3: KR yield curve (ECOS 국고채 3y/10y)
        try:
            kr_3y = fetch_ecos_series_skill(
                "kr_treasury_3y", start_5y, as_of, freq="D", as_of_date=as_of,
            ).dropna()
            kr_10y = fetch_ecos_series_skill(
                "kr_treasury_10y", start_5y, as_of, freq="D", as_of_date=as_of,
            ).dropna()
            kr_yield_curve = compute_kr_yield_curve(kr_3y, kr_10y, as_of=as_of)
        except Exception:
            kr_yield_curve = _sentinel_kr_yield_curve(as_of)

        # Tier-3: KR corporate spread (AA- 3y vs 국고채 3y)
        try:
            kr_corp = fetch_ecos_series_skill(
                "kr_corp_aa_3y", start_5y, as_of, freq="D", as_of_date=as_of,
            ).dropna()
            # kr_3y는 위에서 fetch했지만 sentinel일 수 있으므로 별도 fetch (or reuse)
            kr_corp_spread = compute_kr_corp_spread(
                kr_corp, kr_3y if not kr_yield_curve.staleness_days >= 99 else pd.Series(dtype=float),
                as_of=as_of,
            )
        except Exception:
            kr_corp_spread = _sentinel_kr_corp_spread(as_of)

        # Tier-3: KR 신용잔고 (KRX pykrx)
        try:
            margin = fetch_credit_balance(as_of - timedelta(days=400), as_of)
            kr_margin = compute_kr_margin_debt(margin, as_of=as_of)
        except Exception:
            kr_margin = _sentinel_kr_margin(as_of)

        # Tier-3: KOSPI vs KOSDAQ (pykrx index)
        try:
            kospi_idx = fetch_market_index(
                "1001", as_of - timedelta(days=60), as_of,
            )
            kosdaq_idx = fetch_market_index(
                "2001", as_of - timedelta(days=60), as_of,
            )
            kr_market_tier = compute_kr_market_tier(kospi_idx, kosdaq_idx, as_of=as_of)
        except Exception:
            kr_market_tier = _sentinel_kr_tier(as_of)

        systemic = score_systemic_risk(
            quick_llm, deep_llm,
            vix=vix.current_value, vix_z=vix.zscore_30d, vix_pct=vix.percentile_5y,
            vix_change_4w=vix.change_4w,
            vkospi=vkospi.current_value, vkospi_change_4w=vkospi.change_4w,
            ig_bps=ig.current_bps, ig_pct=ig.percentile_5y,
            ig_momentum_z=ig.momentum_zscore,
            hy_bps=hy.current_bps, hy_widening=hy.widening,
            hy_momentum_z=hy.momentum_zscore,
            fg_label=fg.label, fg_value=fg.current_value,
            breadth_kr_adv=breadth_kr.advancing_pct,
            breadth_us_adv=breadth_us.advancing_pct,
            pca_first_share=pca.first_eigenvalue_share,
            pca_concentrated=pca.is_concentrated,
            # Tier-1 신규 inputs
            vix_term_ratio=vix_term.ratio, vix_term_regime=vix_term.regime,
            skew_value=skew.skew_value, skew_signal=skew.tail_hedge_signal,
            vxn=vxn.current_value, vxn_spread_vs_vix=vxn.spread_vs_vix,
            # Tier-2 신규 inputs
            tips_10y=real_yields.tips_10y, real_yields_regime=real_yields.regime,
            funding_spread_bps=funding_stress.spread_bps,
            funding_regime=funding_stress.regime,
            credit_quality_spread_bps=credit_quality.quality_spread_bps,
            credit_quality_regime=credit_quality.regime,
            # Tier-3 신규 inputs (KR-specific)
            kr_yc_spread_bps=kr_yield_curve.spread_10y_3y_bps,
            kr_yc_inverted=kr_yield_curve.inverted,
            kr_yc_regime=kr_yield_curve.regime,
            kr_corp_spread_bps=kr_corp_spread.spread_bps,
            kr_corp_regime=kr_corp_spread.regime,
            kr_margin_change_20d=kr_margin.change_20d_pct,
            kr_margin_signal=kr_margin.signal,
            kr_tier_relative_perf=kr_market_tier.relative_perf_pct,
            kr_tier_signal=kr_market_tier.signal,
        )

        narrative = quick_llm.invoke(
            f"Summarize market risk in ≤500 Korean chars. "
            f"Score {systemic.score}/10 ({systemic.regime}). "
            f"VIX {vix.current_value:.1f} (term {vix_term.regime}), "
            f"SKEW {skew.skew_value:.0f} ({skew.tail_hedge_signal}), "
            f"drivers: {systemic.drivers}"
        ).content[:500]
        summary = (
            f"## Risk\nScore: **{systemic.score:.1f}/10** ({systemic.regime})\n"
            f"VIX: {vix.current_value:.1f} (z={vix.zscore_30d:.2f}, 4w {vix.change_4w:+.1f})\n"
            f"VKOSPI: {vkospi.current_value:.1f} (4w {vkospi.change_4w:+.1f})\n"
            f"VIX term: ratio {vix_term.ratio:.2f} ({vix_term.regime})\n"
            f"SKEW: {skew.skew_value:.0f} ({skew.tail_hedge_signal})\n"
            f"VXN: {vxn.current_value:.1f} (spread vs VIX {vxn.spread_vs_vix:+.1f})\n"
            f"HY OAS: {hy.current_bps:.0f}bps {'(widening)' if hy.widening else ''} (mom z {hy.momentum_zscore:+.2f})\n"
            f"Breadth KR: {breadth_kr.advancing_pct:.0%}, US: {breadth_us.advancing_pct:.0%}\n"
            f"PCA 1st: {pca.first_eigenvalue_share:.2f} {'(concentrated)' if pca.is_concentrated else ''}\n"
            f"TIPS 10y: {real_yields.tips_10y:.2f}% ({real_yields.regime})\n"
            f"Funding: SOFR-Tbill {funding_stress.spread_bps:+.0f}bps ({funding_stress.regime})\n"
            f"Credit quality: BBB-AAA {credit_quality.quality_spread_bps:.0f}bps ({credit_quality.regime})\n"
            f"KR yield curve: 10y-3y {kr_yield_curve.spread_10y_3y_bps:+.0f}bps ({kr_yield_curve.regime})\n"
            f"KR corp spread: {kr_corp_spread.spread_bps:+.0f}bps ({kr_corp_spread.regime})\n"
            f"KR margin: 20d {kr_margin.change_20d_pct:+.1f}% ({kr_margin.signal})\n"
            f"KR tier: KOSDAQ-KOSPI {kr_market_tier.relative_perf_pct:+.1f}% ({kr_market_tier.signal})\n"
        )[:2000]

        report = RiskReport(
            vix=vix, vkospi=vkospi, credit_spread_us_ig=ig, credit_spread_us_hy=hy,
            fear_greed=fg, breadth_kr=breadth_kr, breadth_us=breadth_us,
            correlation_concentration=pca, systemic_score=systemic,
            vix_term=vix_term, skew=skew, vxn=vxn,
            real_yields=real_yields, funding_stress=funding_stress,
            credit_quality=credit_quality,
            kr_yield_curve=kr_yield_curve, kr_corp_spread=kr_corp_spread,
            kr_margin_debt=kr_margin, kr_market_tier=kr_market_tier,
            narrative=narrative, summary_for_downstream=summary,
        )
        return {"risk_report": report, "risk_summary": summary}

    return node
