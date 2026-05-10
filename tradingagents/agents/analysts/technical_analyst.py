"""Technical Analyst — orchestrates 5 technical skills, composes TechnicalReport."""
from datetime import date, timedelta
from pathlib import Path

from tradingagents.dataflows.universe import load_universe
from tradingagents.schemas.reports import TechnicalReport
from tradingagents.skills.technical.correlation_cluster import find_correlation_clusters
from tradingagents.skills.technical.momentum_ranker import rank_momentum
from tradingagents.skills.technical.price_batch import fetch_etf_price_batch
from tradingagents.skills.technical.ta_indicators import compute_ta_indicators
from tradingagents.skills.technical.trend_state import detect_trend_state


def create_technical_analyst(quick_llm, deep_llm, cache_path: str | None = None):
    def node(state):
        as_of = date.fromisoformat(state["as_of_date"])
        universe = load_universe(Path(state["universe_path"]))
        tickers = [e.ticker for e in universe.etfs]

        start = as_of - timedelta(days=365 * 3 + 30)
        prices = fetch_etf_price_batch(tickers, start, as_of, cache_path=cache_path)
        if prices.empty:
            raise RuntimeError("No price data fetched")

        rankings = rank_momentum(prices, universe, lookback_months=6)

        # Top-tier ETFs only get TA indicators (cost reduction)
        top_tickers: list[str] = []
        for cat_rankings in rankings.values():
            top_tickers.extend([r.ticker for r in cat_rankings[:5]])
        top_tickers = list(set(top_tickers))

        trend_states = {}
        for t in top_tickers:
            sub = prices[prices["ticker"] == t]
            if len(sub) < 200:
                continue
            try:
                panel = compute_ta_indicators(prices, t)
                current_price = float(sub["close"].iloc[-1])
                trend_states[t] = detect_trend_state(panel, current_price)
            except Exception:
                continue

        # Correlation clusters from top-tier returns
        pivot = prices.pivot(index="date", columns="ticker", values="close")
        returns = pivot.pct_change().dropna(how="all").tail(252)
        returns_top = returns[[c for c in returns.columns if c in top_tickers]].dropna(axis=1, how="any")

        name_lookup = {e.ticker: e.name for e in universe.etfs}
        clusters = find_correlation_clusters(returns_top, threshold=0.7, universe_lookup=name_lookup)

        narrative = quick_llm.invoke(
            f"Summarize 188-ETF technical scan in ≤500 Korean chars. "
            f"Top momentum categories: {list(rankings.keys())[:5]}. "
            f"Found {len(clusters)} correlation clusters."
        ).content[:500]
        largest_cluster_label = (
            max(clusters, key=lambda x: len(x.members)).category_label
            if clusters else "none"
        )
        summary = (
            f"## Technical\n"
            f"Categories scanned: {len(rankings)}\n"
            f"Trend states: {sum(1 for v in trend_states.values() if 'uptrend' in v.value)} uptrending of {len(trend_states)}\n"
            f"Clusters: {len(clusters)} (largest: {largest_cluster_label})\n"
        )[:2000]

        report = TechnicalReport(
            asset_class_momentum=rankings,
            individual_etf_states=trend_states,
            correlation_clusters=clusters,
            narrative=narrative, summary_for_downstream=summary,
        )
        return {
            "technical_report": report, "technical_summary": summary,
            "correlation_clusters": clusters,
        }

    return node
