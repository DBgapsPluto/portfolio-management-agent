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
from tradingagents.schemas.reports import RiskReport
from tradingagents.schemas.risk import (
    SentimentSnapshot, SkewSnapshot, VIXTermStructureSnapshot, VxnSnapshot,
)
from tradingagents.skills.macro.fred_fetcher import fetch_fred_series_skill
from tradingagents.skills.risk.breadth import compute_market_breadth
from tradingagents.skills.risk.correlation_pca import compute_correlation_concentration
from tradingagents.skills.risk.credit_spread import fetch_credit_spread
from tradingagents.skills.risk.fear_greed import fetch_fear_greed_index
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

        systemic = score_systemic_risk(
            quick_llm, deep_llm,
            vix=vix.current_value, vix_z=vix.zscore_30d, vix_pct=vix.percentile_5y,
            vix_change_4w=vix.change_4w,
            vkospi=vkospi.current_value, vkospi_change_4w=vkospi.change_4w,
            ig_bps=ig.current_bps, ig_pct=ig.percentile_5y,
            hy_bps=hy.current_bps, hy_widening=hy.widening,
            fg_label=fg.label, fg_value=fg.current_value,
            breadth_kr_adv=breadth_kr.advancing_pct,
            breadth_us_adv=breadth_us.advancing_pct,
            pca_first_share=pca.first_eigenvalue_share,
            pca_concentrated=pca.is_concentrated,
            # Tier-1 신규 inputs
            vix_term_ratio=vix_term.ratio, vix_term_regime=vix_term.regime,
            skew_value=skew.skew_value, skew_signal=skew.tail_hedge_signal,
            vxn=vxn.current_value, vxn_spread_vs_vix=vxn.spread_vs_vix,
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
            f"HY OAS: {hy.current_bps:.0f}bps {'(widening)' if hy.widening else ''}\n"
            f"Breadth KR: {breadth_kr.advancing_pct:.0%}, US: {breadth_us.advancing_pct:.0%}\n"
            f"PCA 1st: {pca.first_eigenvalue_share:.2f} {'(concentrated)' if pca.is_concentrated else ''}\n"
        )[:2000]

        report = RiskReport(
            vix=vix, vkospi=vkospi, credit_spread_us_ig=ig, credit_spread_us_hy=hy,
            fear_greed=fg, breadth_kr=breadth_kr, breadth_us=breadth_us,
            correlation_concentration=pca, systemic_score=systemic,
            vix_term=vix_term, skew=skew, vxn=vxn,
            narrative=narrative, summary_for_downstream=summary,
        )
        return {"risk_report": report, "risk_summary": summary}

    return node
