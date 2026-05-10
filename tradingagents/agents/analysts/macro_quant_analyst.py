"""Macro/Quant Analyst — orchestrates 8 macro skills, composes MacroReport.

Per design §7.1: fixed pipeline (no LLM-driven skill ordering).
LLM only writes the ≤500-char narrative + 2KB summary.
"""
from datetime import date, timedelta

from tradingagents.schemas.macro import RegimeClassification, DivergenceScore
from tradingagents.schemas.reports import MacroReport
from tradingagents.skills.macro.calendar import fetch_central_bank_calendar_skill
from tradingagents.skills.macro.divergence import compute_kr_divergence
from tradingagents.skills.macro.ecos_fetcher import fetch_ecos_series_skill
from tradingagents.skills.macro.employment import compute_unemployment_trend
from tradingagents.skills.macro.fred_fetcher import fetch_fred_series_skill
from tradingagents.skills.macro.inflation import compute_inflation_trend
from tradingagents.skills.macro.regime_classifier import classify_regime
from tradingagents.skills.macro.yield_curve import compute_yield_curve


NARRATIVE_PROMPT = """\
You are summarizing a macro snapshot for an asset-allocation team.

Data:
- Regime: {regime_quadrant} (confidence {confidence:.2f})
- 10y-2y spread: {spread_2y_bps:.1f} bps (inverted {inverted_days} days)
- CPI YoY: {cpi:.1f}% (accelerating: {accelerating})
- Unemployment: {ur:.1f}% (Sahm: {sahm})
- Upcoming events: {events}

Write ≤500 chars in Korean. Be concrete. Cite numbers above only — do not invent."""


def create_macro_quant_analyst(quick_llm, deep_llm):
    def node(state):
        as_of = date.fromisoformat(state["as_of_date"])
        start_macro = as_of - timedelta(days=365 * 5)

        # All fetchers receive as_of_date for point-in-time truncation (D13)
        s_10y = fetch_fred_series_skill("us_10y", start_macro, as_of, as_of_date=as_of)
        s_2y = fetch_fred_series_skill("us_2y", start_macro, as_of, as_of_date=as_of)
        s_3m = fetch_fred_series_skill("us_3m", start_macro, as_of, as_of_date=as_of)
        yc = compute_yield_curve(s_10y, s_2y, s_3m, as_of=as_of)

        cpi = fetch_fred_series_skill("us_cpi", start_macro, as_of, as_of_date=as_of)
        core_cpi = fetch_fred_series_skill("us_core_cpi", start_macro, as_of, as_of_date=as_of)
        infl = compute_inflation_trend(cpi, core_cpi, as_of=as_of)

        ur = fetch_fred_series_skill("us_unrate", start_macro, as_of, as_of_date=as_of)
        payems = fetch_fred_series_skill("us_payems", start_macro, as_of, as_of_date=as_of)
        emp = compute_unemployment_trend(ur, payems, as_of=as_of)

        # KR divergence (best-effort — ECOS may fail)
        try:
            us_policy = fetch_fred_series_skill("us_policy_rate", start_macro, as_of, as_of_date=as_of)
            kr_rate = fetch_ecos_series_skill("kr_base_rate", start_macro, as_of, as_of_date=as_of)
            kr_cpi = fetch_ecos_series_skill("kr_cpi", start_macro, as_of, as_of_date=as_of)
            div = compute_kr_divergence(
                us_policy_rate=float(us_policy.iloc[-1]),
                kr_base_rate=float(kr_rate.iloc[-1]),
                us_cpi_yoy=infl.cpi_yoy,
                kr_cpi_yoy=float((kr_cpi.iloc[-1] / kr_cpi.iloc[-13] - 1) * 100) if len(kr_cpi) >= 13 else 0.0,
                as_of=as_of,
            )
        except Exception:
            div = DivergenceScore(us_kr_rate_gap_bps=0, us_kr_inflation_gap=0, score=0, source_date=as_of)

        events = fetch_central_bank_calendar_skill(as_of, days=90)

        regime: RegimeClassification = classify_regime(
            quick_llm, deep_llm,
            spread_10y_2y_bps=yc.spread_10y_2y_bps,
            inverted_days_count=yc.inverted_days_count,
            cpi_yoy=infl.cpi_yoy,
            momentum_3mo=infl.momentum_3mo,
            accelerating=infl.accelerating,
            unemployment_rate=emp.unemployment_rate,
            sahm_rule_triggered=emp.sahm_rule_triggered,
        )

        narrative_prompt = NARRATIVE_PROMPT.format(
            regime_quadrant=regime.quadrant, confidence=regime.confidence,
            spread_2y_bps=yc.spread_10y_2y_bps, inverted_days=yc.inverted_days_count,
            cpi=infl.cpi_yoy, accelerating=infl.accelerating,
            ur=emp.unemployment_rate, sahm=emp.sahm_rule_triggered,
            events=", ".join(f"{e.event_date} {e.bank}" for e in events[:3]) or "none",
        )
        narrative = quick_llm.invoke(narrative_prompt).content[:500]
        summary = (
            f"## Macro\n"
            f"Regime: **{regime.quadrant}** ({regime.confidence:.2f})\n"
            f"YC 10y-2y: {yc.spread_10y_2y_bps:.0f}bps, inverted {yc.inverted_days_count}d\n"
            f"CPI: {infl.cpi_yoy:.1f}% YoY ({'↑' if infl.accelerating else '↓'})\n"
            f"UR: {emp.unemployment_rate:.1f}% (Sahm: {emp.sahm_rule_triggered})\n"
            f"Drivers: {', '.join(regime.drivers[:3])}\n"
        )[:2000]

        report = MacroReport(
            yield_curve=yc, inflation=infl, employment=emp,
            kr_divergence=div, regime=regime,
            upcoming_events=events,
            narrative=narrative, summary_for_downstream=summary,
        )
        return {"macro_report": report, "macro_summary": summary}

    return node
