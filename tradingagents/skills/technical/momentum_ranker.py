import pandas as pd

from tradingagents.dataflows.universe import Universe
from tradingagents.schemas.technical import ETFRanking
from tradingagents.skills.registry import register_skill


@register_skill(name="rank_momentum", category="technical")
def rank_momentum(
    prices: pd.DataFrame, universe: Universe, lookback_months: int = 6,
) -> dict[str, list[ETFRanking]]:
    """Group by category, rank by lookback momentum."""
    name_lookup = {e.ticker: e.name for e in universe.etfs}
    cat_lookup = {e.ticker: e.category for e in universe.etfs}

    grouped: dict[str, list[ETFRanking]] = {}
    for ticker, sub in prices.groupby("ticker"):
        sub = sub.sort_values("date")
        if len(sub) < lookback_months * 21:
            continue
        end = float(sub["close"].iloc[-1])
        start = float(sub["close"].iloc[-(lookback_months * 21)])
        m_lookback = (end / start) - 1

        m3 = (end / float(sub["close"].iloc[-63])) - 1 if len(sub) >= 63 else 0.0
        m12 = (end / float(sub["close"].iloc[-252])) - 1 if len(sub) >= 252 else m_lookback

        category = cat_lookup.get(ticker, "기타")
        grouped.setdefault(category, []).append(ETFRanking(
            ticker=ticker, name=name_lookup.get(ticker, ticker),
            momentum_3m=m3, momentum_6m=m_lookback, momentum_12m=m12,
            rank_in_category=1,  # placeholder, ranked next
        ))

    for cat, items in grouped.items():
        items.sort(key=lambda r: r.momentum_6m, reverse=True)
        for i, item in enumerate(items, start=1):
            item.rank_in_category = i

    return grouped
