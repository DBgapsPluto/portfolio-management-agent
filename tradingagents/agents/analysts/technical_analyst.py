"""Technical Analyst — orchestrates technical skills, composes TechnicalReport."""
from datetime import date, timedelta
from pathlib import Path


def _summarize_extended(panels: dict) -> str:
    """Compress Tier-1 ExtendedIndicatorPanel dict into ≤~400-char markdown.

    LLM-facing aggregate over the universe + outlier ETFs only (top-N).
    """
    if not panels:
        return ""
    n = len(panels)
    strong_trend = sum(1 for p in panels.values() if p.adx > 25)
    squeeze = sum(1 for p in panels.values() if p.bb_bandwidth < 0.05)
    overbought_b = sum(1 for p in panels.values() if p.bb_percent_b > 1.0)
    oversold_b = sum(1 for p in panels.values() if p.bb_percent_b < 0.0)
    mfi_hot = sum(1 for p in panels.values() if p.mfi > 80)
    mfi_cold = sum(1 for p in panels.values() if p.mfi < 20)
    bearish_div = [t for t, p in panels.items() if p.rsi_divergence == "bearish" or p.macd_divergence == "bearish"]
    bullish_div = [t for t, p in panels.items() if p.rsi_divergence == "bullish" or p.macd_divergence == "bullish"]
    weekly_up = sum(1 for p in panels.values() if p.weekly_trend == "up")
    weekly_down = sum(1 for p in panels.values() if p.weekly_trend == "down")
    return (
        f"Tier-1 (188 ETF aggregate):\n"
        f"  ADX>25 (강한 추세): {strong_trend}/{n}\n"
        f"  Bollinger 압축 (bw<5%): {squeeze}/{n}\n"
        f"  %B>1 과매수: {overbought_b}, %B<0 과매도: {oversold_b}\n"
        f"  MFI>80: {mfi_hot}, MFI<20: {mfi_cold}\n"
        f"  Bearish divergence: {len(bearish_div)} (예: {bearish_div[:3]})\n"
        f"  Bullish divergence: {len(bullish_div)} (예: {bullish_div[:3]})\n"
        f"  Weekly trend up/down: {weekly_up}/{weekly_down}\n"
    )

from tradingagents.dataflows.equity_indices import fetch_equity_index_close
from tradingagents.dataflows.universe import load_universe
from tradingagents.schemas.reports import TechnicalReport
from tradingagents.skills.portfolio.factor_scorer import compute_factor_panel
from tradingagents.skills.technical.correlation_cluster import find_correlation_clusters
from tradingagents.skills.technical.extended_indicators import compute_extended_indicators
from tradingagents.skills.technical.momentum_ranker import rank_momentum
from tradingagents.skills.technical.price_batch import fetch_etf_price_batch
from tradingagents.skills.technical.ta_indicators import compute_ta_indicators
from tradingagents.skills.technical.trend_quantification import quantify_trend
from tradingagents.skills.technical.trend_state import detect_trend_state


def _benchmark_for_category(category: str) -> str:
    """국내_* → KOSPI200, 그 외 → SPY."""
    return "KOSPI200" if category.startswith("국내") else "SPY"


def _summarize_trend_quant(panels: dict) -> str:
    """Tier-2 압축: 분포 통계 + top-3 leader/laggard by score."""
    if not panels:
        return ""
    n = len(panels)
    strong_up = sum(1 for p in panels.values() if p.trend_strength_score > 0.5)
    strong_dn = sum(1 for p in panels.values() if p.trend_strength_score < -0.5)
    accel_pos = sum(1 for p in panels.values() if p.momentum_acceleration > 0)
    rel_winners = sum(1 for p in panels.values() if p.momentum_12m_rel > 0)
    leaders = sorted(panels.items(), key=lambda kv: -kv[1].trend_strength_score)[:3]
    laggards = sorted(panels.items(), key=lambda kv: kv[1].trend_strength_score)[:3]
    leader_str = ", ".join(
        f"{t}({p.trend_strength_score:+.2f}, rel_12m {p.momentum_12m_rel*100:+.1f}%)"
        for t, p in leaders
    )
    laggard_str = ", ".join(
        f"{t}({p.trend_strength_score:+.2f})" for t, p in laggards
    )
    return (
        f"Tier-2 (trend quant, n={n}):\n"
        f"  strength>+0.5: {strong_up}, <-0.5: {strong_dn}\n"
        f"  Accelerating (mom_3m_ann > 12m): {accel_pos}/{n}\n"
        f"  벤치마크 outperform 12m: {rel_winners}/{n}\n"
        f"  Top: {leader_str}\n"
        f"  Bot: {laggard_str}\n"
    )


def create_technical_analyst(quick_llm, deep_llm, cache_path: str | None = None):
    def node(state):
        as_of = date.fromisoformat(state["as_of_date"])
        universe = load_universe(Path(state["universe_path"]))
        tickers = [e.ticker for e in universe.etfs]

        start = as_of - timedelta(days=365 * 3 + 30)
        prices = fetch_etf_price_batch(tickers, start, as_of, cache_path=cache_path)
        if prices.empty:
            raise RuntimeError("No price data fetched")

        rankings = rank_momentum(prices, universe)

        # Universe-wide raw factor panel (skip-1m momentum + vol + Sharpe + log AUM).
        # Z-scoring / regime blend happens in Stage 3 candidate selector — this is
        # just the ticker-intrinsic measurement step done once here so allocator
        # doesn't recompute.
        pivot_full = prices.pivot(index="date", columns="ticker", values="close")
        returns_full = pivot_full.pct_change().dropna(how="all")
        aum_lookup = {e.ticker: e.aum_krw for e in universe.etfs}
        factor_panel = {}
        for t in returns_full.columns:
            factor_panel[t] = compute_factor_panel(
                returns_full[t], aum_lookup.get(t, 0.0),
            )

        # Top-tier ETFs only get TA indicators (cost reduction)
        # Top-5 per category, with ties at the boundary included
        # (rank_in_category uses competition ranking, so ties share rank)
        top_tickers: list[str] = []
        for cat_rankings in rankings.values():
            top_tickers.extend([r.ticker for r in cat_rankings if r.rank_in_category <= 5])
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

        # Tier-1: extended indicators for every ETF with sufficient history.
        extended_indicators = {}
        for t in returns_full.columns:
            sub = prices[prices["ticker"] == t]
            if len(sub) < 200:
                continue
            try:
                extended_indicators[t] = compute_extended_indicators(prices, t)
            except Exception:
                continue

        ext_summary = _summarize_extended(extended_indicators)

        # Tier-2: trend quantification with dual-momentum benchmarks.
        try:
            bench_kospi = fetch_equity_index_close("kospi200", start, as_of)
        except Exception:
            bench_kospi = None
        try:
            bench_spy = fetch_equity_index_close("spy", start, as_of)
        except Exception:
            bench_spy = None

        cat_lookup = {e.ticker: e.category for e in universe.etfs}
        trend_quant = {}
        for t in returns_full.columns:
            sub = prices[prices["ticker"] == t]
            if len(sub) < 252:
                continue
            label = _benchmark_for_category(cat_lookup.get(t, ""))
            bench_close = bench_kospi if label == "KOSPI200" else bench_spy
            if bench_close is None or bench_close.empty:
                bench_close, label = None, "none"
            try:
                trend_quant[t] = quantify_trend(
                    prices, t, benchmark_close=bench_close, benchmark_label=label,
                )
            except Exception:
                continue

        trend_quant_summary = _summarize_trend_quant(trend_quant)

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
            f"{ext_summary}"
            f"{trend_quant_summary}"
        )[:2000]

        report = TechnicalReport(
            asset_class_momentum=rankings,
            individual_etf_states=trend_states,
            correlation_clusters=clusters,
            factor_panel=factor_panel,
            extended_indicators=extended_indicators,
            trend_quantification=trend_quant,
            narrative=narrative, summary_for_downstream=summary,
        )
        return {
            "technical_report": report, "technical_summary": summary,
            "correlation_clusters": clusters,
        }

    return node
