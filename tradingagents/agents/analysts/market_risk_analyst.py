"""Market Risk Analyst — orchestrates 6 risk skills, composes RiskReport."""
from datetime import date

import pandas as pd

from tradingagents.schemas.reports import RiskReport
from tradingagents.schemas.risk import SentimentSnapshot
from tradingagents.skills.risk.breadth import compute_market_breadth
from tradingagents.skills.risk.correlation_pca import compute_correlation_concentration
from tradingagents.skills.risk.credit_spread import fetch_credit_spread
from tradingagents.skills.risk.fear_greed import fetch_fear_greed_index
from tradingagents.skills.risk.systemic_score import score_systemic_risk
from tradingagents.skills.risk.volatility import fetch_volatility_index


def create_market_risk_analyst(quick_llm, deep_llm):
    def node(state):
        as_of = date.fromisoformat(state["as_of_date"])

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
                staleness_days=99,  # Mark as missing
            )

        systemic = score_systemic_risk(
            quick_llm, deep_llm,
            vix=vix.current_value, vix_z=vix.zscore_30d, vix_pct=vix.percentile_5y,
            vkospi=vkospi.current_value,
            ig_bps=ig.current_bps, ig_pct=ig.percentile_5y,
            hy_bps=hy.current_bps, hy_widening=hy.widening,
            fg_label=fg.label, fg_value=fg.current_value,
            breadth_kr_adv=breadth_kr.advancing_pct,
            breadth_us_adv=breadth_us.advancing_pct,
            pca_first_share=pca.first_eigenvalue_share,
            pca_concentrated=pca.is_concentrated,
        )

        narrative = quick_llm.invoke(
            f"Summarize market risk in ≤500 Korean chars. "
            f"Score {systemic.score}/10 ({systemic.regime}). "
            f"VIX {vix.current_value:.1f}, drivers: {systemic.drivers}"
        ).content[:500]
        summary = (
            f"## Risk\nScore: **{systemic.score:.1f}/10** ({systemic.regime})\n"
            f"VIX: {vix.current_value:.1f} (z={vix.zscore_30d:.2f})\n"
            f"VKOSPI: {vkospi.current_value:.1f}\n"
            f"HY OAS: {hy.current_bps:.0f}bps {'(widening)' if hy.widening else ''}\n"
            f"PCA 1st: {pca.first_eigenvalue_share:.2f} {'(concentrated)' if pca.is_concentrated else ''}\n"
        )[:2000]

        report = RiskReport(
            vix=vix, vkospi=vkospi, credit_spread_us_ig=ig, credit_spread_us_hy=hy,
            fear_greed=fg, breadth_kr=breadth_kr, breadth_us=breadth_us,
            correlation_concentration=pca, systemic_score=systemic,
            narrative=narrative, summary_for_downstream=summary,
        )
        return {"risk_report": report, "risk_summary": summary}

    return node
